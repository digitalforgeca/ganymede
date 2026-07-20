import asyncio
import time
import os
import json
import re
import uuid
import pty
import structlog
from typing import Any
from google.antigravity.types import Text
from ganymede.core import ContextKey
from ganymede.config import AppConfig
from ganymede.core.quota import QuotaTracker

logger = structlog.get_logger()

# Regex to strip ANSI/VT escape sequences that bubbletea emits through the PTY.
# We need the PTY so bubbletea can open /dev/tty (otherwise it fatally crashes),
# but we don't want the TUI rendering garbage leaking into Discord messages.
_ANSI_ESCAPE = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|\([A-Z0-9])')

# MANDATORY default model for all CLI invocations.
# Ganymede must ALWAYS pass --model to agy; without it, agy falls back to its
# own global settings.json which the human user may have set to a third-party
# model (e.g. Opus).  Gemini models have effectively unlimited API quotas;
# third-party models do not and must only be used when the human explicitly
# configures a per-channel override via /model or model.txt.



class MockUsage:
    def __init__(self):
        self.total_token_count = 0


class CliResponse:
    """Wrapper around agy subprocess to be compatible with Router chunks interface.
    
    ARCHITECTURE: The PTY is ONLY for injecting input. Output is read via Chalice telemetry.
    When the Chalice Stop hook fires (fullyIdle=true), it provides the transcriptPath
    to the child conversation's JSONL transcript. We read the agent's response from there.
    """

    def __init__(self, agent_instance, prompt: str, direct_text: str = None):
        self.agent = agent_instance
        self.prompt = prompt
        self.response_text = direct_text or ""
        self.usage_metadata = MockUsage()
        if direct_text is not None:
            self._chunks_generator = self._direct_chunks()
        else:
            self._chunks_generator = self._read_chunks()

    async def _direct_chunks(self):
        yield Text(text=self.response_text, step_index=0)

    async def _read_chunks(self):
        # Clear the event before we wait
        self.agent.turn_completed_event.clear()
        self.agent.aborted = False
        
        try:
            # Wait for Chalice to fire the Stop hook signaling generation is done
            await asyncio.wait_for(self.agent.turn_completed_event.wait(), timeout=600)
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for agent to finish turn", conversation_id=self.agent.conversation_id)
            yield Text(text="[Error: Agent timed out while generating response]", step_index=0)
            return

        # Check if we were woken by an abort (/stop) rather than clean completion
        if self.agent.aborted:
            logger.info("Agent turn aborted by /stop", conversation_id=self.agent.conversation_id)
            return

        # Check if the Stop hook carried an error (e.g., API rate limit / quota exhaustion).
        # Surface it immediately so the user sees what went wrong.
        chalice_error = self.agent._chalice_error
        self.agent._chalice_error = None  # Consume the error

        # Turn is complete. Read the clean output from the transcript path
        # provided by the Chalice Stop hook payload (stored on the agent).
        transcript_path = self.agent._chalice_transcript_path
        if not transcript_path or not os.path.exists(transcript_path):
            error_msg = chalice_error or "No transcript available from agent"
            logger.error("No transcript path from Chalice telemetry",
                         conversation_id=self.agent.conversation_id,
                         transcript_path=transcript_path,
                         chalice_error=chalice_error)
            yield Text(text=f"⚠️ {error_msg}", step_index=0)
            return
            
        final_text = ""
        current_turn_tool_calls = []
        try:
            with open(transcript_path, 'r') as f:
                lines = f.readlines()
                
            # Iterate backwards to find the last USER_INPUT to bound the turn
            start_idx = 0
            for i in range(len(lines)-1, -1, -1):
                try:
                    data = json.loads(lines[i])
                    if data.get("type") == "USER_INPUT":
                        start_idx = i
                        break
                except json.JSONDecodeError:
                    continue
                    
            # Collect all tool calls and the last non-empty final_text
            for i in range(start_idx, len(lines)):
                try:
                    data = json.loads(lines[i])
                    if data.get("type") in ("PLANNER_RESPONSE", "TEXT_RESPONSE"):
                        content = data.get("content", "")
                        if content:
                            final_text = content
                        if data.get("tool_calls"):
                            current_turn_tool_calls.extend(data.get("tool_calls"))
                except json.JSONDecodeError:
                    continue
                            
            artifacts_created = []
            if current_turn_tool_calls:
                tool_text = "\n\n*⚒️ Tools Used:*\n"
                for t in current_turn_tool_calls:
                    t_name = t.get('name') or t.get('function', {}).get('name') or 'tool'
                    args = t.get('args') or t.get('function', {}).get('arguments') or {}
                    try:
                        args_obj = json.loads(args) if isinstance(args, str) else args
                        args_formatted = json.dumps(args_obj, indent=2)
                        
                        # Detect artifacts
                        if t_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
                            metadata = args_obj.get("ArtifactMetadata", {})
                            if metadata and (metadata.get("UserFacing") or metadata.get("RequestFeedback")):
                                target_file = args_obj.get("TargetFile", "Unknown File")
                                summary = metadata.get("Summary", "")
                                if not any(a["file"] == target_file for a in artifacts_created):
                                    artifacts_created.append({"file": target_file, "summary": summary})
                    except Exception:
                        args_formatted = str(args)
                        
                    tool_text += f"<details><summary><code>{t_name}</code></summary>\n\n```json\n{args_formatted}\n```\n\n</details>\n"
                
                final_text = (final_text + tool_text) if final_text else tool_text.strip()

            # Merge artifacts globally captured from telemetry (which covers subagents!)
            captured_artifacts = getattr(self.agent, "_artifacts_this_turn", [])
            for art in captured_artifacts:
                if not any(a["file"] == art["file"] for a in artifacts_created):
                    artifacts_created.append(art)
                    
            # Process syncing and generating the Discord notification
            if artifacts_created:
                port = getattr(self.agent.config, "dashboard_port", 8180)
                dash_url = f"http://127.0.0.1:{port}"
                art_text = "\n\n**📄 Artifacts Requiring Review:**\n"
                
                channel_brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{self.agent.conversation_id}")
                os.makedirs(channel_brain_dir, exist_ok=True)
                
                import shutil
                for art in artifacts_created:
                    target_file = art["file"]
                    name = os.path.basename(target_file)
                    
                    # Sync artifact from isolated subagent directory back to channel's root brain directory
                    if os.path.exists(target_file):
                        dest_file = os.path.join(channel_brain_dir, name)
                        if target_file != dest_file:
                            try:
                                shutil.copy2(target_file, dest_file)
                            except Exception as e:
                                logger.error("Failed to sync subagent artifact", error=str(e))
                                
                    art_text += f"- **{name}**: {art['summary']}\n"
                    
                art_text += f"\n👉 [Open Ganymede Dashboard to review]({dash_url})"
                final_text = (final_text + art_text) if final_text else art_text.strip()
                
            # Clear telemetry capture for next turn
            self.agent._artifacts_this_turn = []
            
            self.artifacts_count = len(artifacts_created)
            self.tasks_count = getattr(self.agent, "_chalice_tasks_count", 0)
            self.subagents_count = getattr(self.agent, "_chalice_subagents_count", 0)
                
            # If the transcript had no model response but we got an API error, surface it
            if not final_text and chalice_error:
                final_text = f"⚠️ {chalice_error}"
            
            self.response_text = final_text
            yield Text(text=final_text, step_index=0)
            
            self.usage_metadata.total_token_count = (len(self.prompt) + len(final_text)) // 4
        except Exception as e:
            logger.error("Failed to read transcript for output", error=str(e),
                         transcript_path=transcript_path)
            yield Text(text="[Error: Failed to parse agent transcript]", step_index=0)

    @property
    def chunks(self):
        return self._chunks_generator


class ManagedAgent:
    """Wraps a persistent conversation channel context mapped to an agy CLI session.
    
    IMPORTANT: This class spawns `agy` as a CLI subprocess. It does NOT use the
    Antigravity Python SDK directly. See CliResponse docstring for rationale.
    """

    def __init__(self, context_key: ContextKey, config: AppConfig, conversation_id: str, bot_namespace: str = "ganymede", ipc_port: int | None = None, manager=None):
        self.manager = manager
        self.context_key = context_key
        self.config = config
        self.last_active = time.time()
        self._lock = asyncio.Lock()
        self.conversation_id = conversation_id
        self.bot_namespace = bot_namespace
        self.ipc_port = ipc_port
        self.current_process: asyncio.subprocess.Process | None = None
        self.master_fd: int | None = None
        self.sdk_conversation_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, self.conversation_id))
        self.turn_completed_event = asyncio.Event()
        self.aborted = False
        self._chalice_transcript_path = None  # Set by handle_telemetry when Stop fires
        self._chalice_error = None  # Set by handle_telemetry if Stop fires with an error

    async def _sink_pty_output(self):
        """Read and discard the PTY output in the background so the buffer doesn't fill up."""
        loop = asyncio.get_running_loop()
        def read_pty():
            import select
            try:
                r, _, _ = select.select([self.master_fd], [], [], 1.0)
                if r:
                    return os.read(self.master_fd, 4096)
            except OSError:
                pass
            return b''
            
        while self.current_process and self.current_process.returncode is None:
            chunk = await loop.run_in_executor(None, read_pty)
            if not chunk:
                await asyncio.sleep(0.1)

    async def ensure_running(self):
        if self.current_process and self.current_process.returncode is None:
            return

        db_dir = os.path.expanduser("~/.gemini/antigravity-cli/conversations")
        db_path = os.path.join(db_dir, f"{self.sdk_conversation_id}.db")
        is_new_conversation = not os.path.exists(db_path)

        args = ["agy", "--continue", "--conversation", self.sdk_conversation_id]
        
        project_name = self.context_key.project_name
            
        brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{self.conversation_id}")
        app_data = os.path.expanduser("~/.gemini/antigravity-cli")
        sdk_brain_dir = os.path.join(app_data, "brain", self.sdk_conversation_id)
        os.makedirs(brain_dir, exist_ok=True)
        if not os.path.exists(sdk_brain_dir):
            os.symlink(brain_dir, sdk_brain_dir)
            
        if is_new_conversation:
            args.extend(["--new-project", project_name])
            
        # Model resolution — ALWAYS pass --model to prevent agy's global
        # settings.json from applying its own model (which may be Opus/Claude).
        # Priority: model.txt (per-channel /model override) > config.agent.model
        model_txt = os.path.join(sdk_brain_dir, "model.txt")
        if os.path.exists(model_txt):
            with open(model_txt, "r") as f:
                resolved_model = f.read().strip()
            if not resolved_model:
                resolved_model = self.config.agent.model
        else:
            resolved_model = self.config.agent.model

        args.extend(["--model", resolved_model])
            
        if getattr(self.config.agent, "skip_permissions", True):
            args.append("--dangerously-skip-permissions")
            
        workspace_dir = os.path.expanduser(self.config.agent.workspace)
        os.makedirs(workspace_dir, exist_ok=True)
        
        master_fd, slave_fd = pty.openpty()
        self.master_fd = master_fd
        
        subprocess_env = os.environ.copy()
        subprocess_env["SULCUS_NAMESPACE"] = getattr(self, "bot_namespace", "ganymede")
        subprocess_env["NO_COLOR"] = "1"
        subprocess_env["PYTHONUNBUFFERED"] = "1"
        subprocess_env["TERM"] = "dumb"
        if getattr(self, "ipc_port", None):
            subprocess_env["GANYMEDE_IPC_PORT"] = str(self.ipc_port)

        import fcntl, termios
        def _setup_ctty():
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

        logger.info("Spawning agy subprocess", command=" ".join(args), model=resolved_model, context=self.context_key)
        self.current_process = await asyncio.create_subprocess_exec(
            *args,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=workspace_dir,
            env=subprocess_env,
            preexec_fn=_setup_ctty,
        )
        os.close(slave_fd)
        
        # Write PID→conversation_id mapping so Chalice broadcast.py can correlate
        # telemetry events back to this ManagedAgent. We can't use env vars because
        # agy sanitizes the subprocess environment before running hook commands.
        pid_map_dir = os.path.expanduser("~/.ganymede/data/pid_map")
        os.makedirs(pid_map_dir, exist_ok=True)
        pid_map_file = os.path.join(pid_map_dir, str(self.current_process.pid))
        with open(pid_map_file, "w") as f:
            f.write(self.conversation_id)
        
        # Start background sink
        asyncio.create_task(self._sink_pty_output())
        
        # Wait a moment for agy to boot up before injecting initial input
        await asyncio.sleep(2)

    async def chat(self, prompt: str) -> CliResponse:
        self.last_active = time.time()
        
        async with self._lock:
            prompt_stripped = prompt.strip()
            
            # Intercept /models
            if prompt_stripped == "/models":
                import subprocess
                try:
                    result = subprocess.run(["agy", "models"], capture_output=True, text=True, check=True)
                    out = _ANSI_ESCAPE.sub('', result.stdout).strip()
                    return CliResponse(self, prompt, direct_text=f"```\n{out}\n```")
                except Exception as e:
                    return CliResponse(self, prompt, direct_text=f"❌ Error listing models: {e}")
            
            # Intercept /model <name>
            if prompt_stripped.startswith("/model "):
                model_name = prompt_stripped[7:].strip()
                if (model_name.startswith('"') and model_name.endswith('"')) or (model_name.startswith("'") and model_name.endswith("'")):
                    model_name = model_name[1:-1]
                
                # Write to model.txt in the conversation's brain dir
                app_data = os.path.expanduser("~/.gemini/antigravity-cli")
                sdk_brain_dir = os.path.join(app_data, "brain", self.sdk_conversation_id)
                os.makedirs(sdk_brain_dir, exist_ok=True)
                with open(os.path.join(sdk_brain_dir, "model.txt"), "w") as f:
                    f.write(model_name)
                    
                # Terminate the current PTY process so it restarts with the new model on next message
                await self.terminate()
                return CliResponse(self, prompt, direct_text=f"✅ Model successfully switched to `{model_name}` for this channel.\n*(It will take effect on your next message)*")

            await self.ensure_running()
            
            # Inject system instructions for new conversations as a compound prompt
            db_dir = os.path.expanduser("~/.gemini/antigravity-cli/conversations")
            is_new = not os.path.exists(os.path.join(db_dir, f"{self.sdk_conversation_id}.db"))
            
            final_prompt = prompt
            if is_new and hasattr(self.config.agent, "system_instructions") and self.config.agent.system_instructions:
                sys_inst = self.config.agent.system_instructions.replace("{bot_name}", self.bot_namespace)
                sys_inst = sys_inst.replace("{model_name}", self.config.agent.model)
                mission = getattr(self.config.agent, "mission_statement", "to be of help")
                sys_inst = sys_inst.replace("{mission_statement}", mission)
                
                user_name = "user"
                if self.manager:
                    user_name = self.manager.get_active_author_name(self.context_key) or "user"
                sys_inst = sys_inst.replace("{user_name}", user_name)
                
                final_prompt = f"System Instructions:\n{sys_inst}\n\nUser Request:\n{prompt}"
            
            # Write prompt as simulated keystrokes to the PTY.
            # \r is required to trigger bubbletea's Enter key (submit action) in raw mode.
            # Output reading is handled entirely by Chalice telemetry, not the PTY.
            os.write(self.master_fd, (final_prompt + '\r').encode('utf-8'))
            
            return CliResponse(self, prompt)

    async def terminate(self) -> None:
        """Forcefully terminate the active agy CLI subprocess if running."""
        # Signal abort FIRST so the blocked CliResponse generator wakes up immediately
        self.aborted = True
        self.turn_completed_event.set()

        if self.current_process:
            logger.info("Terminating active agy subprocess and its process group", conversation_id=self.conversation_id)
            try:
                import signal
                try:
                    os.killpg(self.current_process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                    
                try:
                    await asyncio.wait_for(self.current_process.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    logger.warn("Subprocess did not exit gracefully, killing process group", conversation_id=self.conversation_id)
                    try:
                        os.killpg(self.current_process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await self.current_process.wait()
            except Exception as e:
                logger.error("Error terminating agy subprocess", error=str(e))
            finally:
                # Clean up PID mapping file
                if self.current_process:
                    pid_map_file = os.path.join(
                        os.path.expanduser("~/.ganymede/data/pid_map"),
                        str(self.current_process.pid))
                    try:
                        os.remove(pid_map_file)
                    except FileNotFoundError:
                        pass
                self.current_process = None
                if self.master_fd is not None:
                    try:
                        os.close(self.master_fd)
                    except Exception:
                        pass
                    self.master_fd = None

    async def close(self):
        await self.terminate()


class AgentManager:
    """Manages channel-to-conversation mapping and CLI execution instances.
    
    ARCHITECTURE: Ganymede is a multiplexing gateway over the `agy` CLI binary.
    It does NOT call the Antigravity API directly. The CLI handles authentication,
    rate limiting, model routing, and session persistence. The Chalice plugin provides
    telemetry hooks that fire during CLI execution.
    
    DO NOT replace this with direct Python SDK calls — that bypasses the CLI's
    infrastructure and immediately hits free-tier API rate limits.
    """

    def __init__(self, config: AppConfig, quota_tracker: QuotaTracker = None, db: Any = None):
        self.config = config
        self.quota_tracker = quota_tracker
        self.db = db
        self._agents: dict[ContextKey, ManagedAgent] = {}
        self._active_authors: dict[ContextKey, str] = {}
        self._active_author_names: dict[ContextKey, str] = {}
        self.adapter = None
        self._telemetry_registered = False
        self._sweeper_task = asyncio.create_task(self._idle_sweeper())

    async def _idle_sweeper(self):
        """Background task that reaps idle CLI sessions that haven't shown activity."""
        while True:
            await asyncio.sleep(600)  # Check every 10 mins
            now = time.time()
            to_remove = []
            for ctx, agent in self._agents.items():
                if now - agent.last_active > 1800:  # 30 minutes of no telemetry activity
                    to_remove.append(ctx)
            for ctx in to_remove:
                logger.info("Sweeping idle agent session to free memory/PTY", context=ctx)
                await self.destroy(ctx)

    async def handle_telemetry(self, data: dict):
        """Wake up ManagedAgent when Chalice signals turn completion.
        
        Correlation: Each agy subprocess has GANYMEDE_CONV_ID set in its env.
        broadcast.py includes this as 'ganymede_conv_id' in the telemetry payload.
        We match on this field (our internal conversation ID) rather than the
        agy-internal conversationId, which changes per child conversation.
        
        The Chalice payload also provides transcriptPath pointing to the child
        conversation's JSONL file — CliResponse reads the response from there.
        """
        if data.get("event") != "Agent Lifecycle Hook":
            return
            
        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            return
        
        # Match on our GANYMEDE_CONV_ID, not agy's internal conversation ID
        ganymede_conv_id = data.get("ganymede_conv_id")
        if not ganymede_conv_id:
            return
            
        # Update activity timestamp to prevent idle reaping during long tasks
        for agent in self._agents.values():
            if agent.conversation_id == ganymede_conv_id:
                agent.last_active = time.time()
                
        if payload.get("fullyIdle"):
            for agent in self._agents.values():
                if agent.conversation_id == ganymede_conv_id:
                    # Store transcript path from Chalice so CliResponse can read it
                    transcript_path = payload.get("transcriptPath")
                    if transcript_path:
                        agent._chalice_transcript_path = transcript_path
                    # Store error from the Stop hook (e.g., API quota exhaustion)
                    # so CliResponse can surface it to the user instead of showing nothing
                    error_text = payload.get("error", "")
                    if error_text:
                        agent._chalice_error = error_text
                        
                    agent._chalice_tasks_count = payload.get("activeTasks", payload.get("tasksCount", 0))
                    agent._chalice_subagents_count = payload.get("activeSubagents", payload.get("subagentsCount", 0))
                    logger.info("Chalice signaled turn complete",
                                ganymede_conv_id=ganymede_conv_id,
                                agy_conv_id=payload.get("conversationId"),
                                transcript_path=transcript_path,
                                reason=payload.get("terminationReason"),
                                error=error_text or None)
                    agent.turn_completed_event.set()
                    return
                    
        # Catch live tool calls globally (captures subagent artifacts)
        for agent in self._agents.values():
            if agent.conversation_id == ganymede_conv_id:
                if not hasattr(agent, "_artifacts_this_turn"):
                    agent._artifacts_this_turn = []
                tool_call = payload.get("toolCall")
                if isinstance(tool_call, dict):
                    t_name = tool_call.get("name", "")
                    if t_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
                        args = tool_call.get("args", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                args = {}
                        if isinstance(args, dict):
                            metadata = args.get("ArtifactMetadata", {})
                            if metadata and (metadata.get("UserFacing") or metadata.get("RequestFeedback")):
                                target_file = args.get("TargetFile")
                                summary = metadata.get("Summary", "")
                                if target_file and not any(a["file"] == target_file for a in agent._artifacts_this_turn):
                                    agent._artifacts_this_turn.append({
                                        "file": target_file,
                                        "summary": summary
                                    })
                return

    def set_active_author(self, context: ContextKey, author_id: str, author_name: str = None) -> None:
        self._active_authors[context] = author_id
        if author_name:
            self._active_author_names[context] = author_name

    def get_active_author(self, context: ContextKey) -> str | None:
        return self._active_authors.get(context)

    def get_active_author_name(self, context: ContextKey) -> str | None:
        return self._active_author_names.get(context)

    def set_adapter(self, adapter) -> None:
        self.adapter = adapter

    def _register_telemetry_listener(self):
        """Lazily register telemetry listener with dashboard (avoids init race)."""
        if self._telemetry_registered:
            return
        from ganymede.core.web import dashboard_instance
        if dashboard_instance:
            if not hasattr(dashboard_instance, "telemetry_listeners"):
                dashboard_instance.telemetry_listeners = []
            dashboard_instance.telemetry_listeners.append(self.handle_telemetry)
            self._telemetry_registered = True
            logger.info("Registered Chalice telemetry listener with dashboard")

    async def get_or_create(self, context: ContextKey) -> ManagedAgent:
        self._register_telemetry_listener()

        if context in self._agents:
            managed = self._agents[context]
            managed.last_active = time.time()
            return managed

        # Check budget first
        if self.quota_tracker:
            allowed = await self.quota_tracker.check_budget(context)
            if not allowed:
                raise RuntimeError("Request blocked due to token/request budget exhaustion.")

        # Resolve or generate a persistent conversation ID
        conversation_id = None
        if self.db:
            conversation_id = await self.db.get_conversation_id_by_context(context)
        
        if not conversation_id:
            if self.adapter:
                conversation_id = self.adapter.get_conversation_id(context)
            else:
                # DO NOT change this naming scheme. The CLI gets a derived UUID, not this ID directly.
                conversation_id = context.ganymede_conv_id
                
            if self.db:
                await self.db.save_conversation_mapping(conversation_id, context)

        bot_namespace = "ganymede"
        ipc_port = None
        if self.adapter:
            if hasattr(self.adapter, "get_bot_namespace"):
                bot_namespace = self.adapter.get_bot_namespace()
            if hasattr(self.adapter, "ipc_server") and self.adapter.ipc_server and hasattr(self.adapter.ipc_server, "port"):
                ipc_port = self.adapter.ipc_server.port

        managed = ManagedAgent(context, self.config, conversation_id, bot_namespace, ipc_port, manager=self)
        self._agents[context] = managed
        return managed

    async def destroy(self, context: ContextKey) -> None:
        """Terminates an active session gracefully and removes it from the pool."""
        if managed := self._agents.pop(context, None):
            await managed.terminate()
            logger.info("Session destroyed and removed from pool", context=context)

    async def destroy_all(self) -> None:
        """Terminates all active sessions."""
        logger.info("Terminating all active agent sessions")
        keys = list(self._agents.keys())
        for k in keys:
            await self.destroy(k)
