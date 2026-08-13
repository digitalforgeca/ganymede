import asyncio
import time
import os
import json
import re
import uuid
import structlog
from typing import Any
from google.antigravity.types import Text
from ganymede.core import ContextKey
from ganymede.config import AppConfig
from ganymede.core.quota import QuotaTracker

logger = structlog.get_logger()

async def async_run(*args, capture_output=False, text=True, check=False, env=None, input=None):
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE if capture_output else None,
        stderr=asyncio.subprocess.PIPE if capture_output else None,
        stdin=asyncio.subprocess.PIPE if input is not None else None,
        env=env
    )
    if input is not None:
        stdout, stderr = await proc.communicate(input=input.encode() if text else input)
    else:
        stdout, stderr = await proc.communicate()
    
    if text and stdout is not None:
        stdout = stdout.decode('utf-8')
    if text and stderr is not None:
        stderr = stderr.decode('utf-8')
        
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command {' '.join(args)} failed with return code {proc.returncode}")
        
    class _Res:
        def __init__(self, rc, out, err):
            self.returncode = rc
            self.stdout = out
            self.stderr = err
            
    return _Res(proc.returncode, stdout, stderr)

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

class Thought:
    def __init__(self, text: str):
        self.text = text

class ToolCall:
    def __init__(self, name: str, args: dict):
        self.name = name
        self.args = args

class ToolResult:
    def __init__(self, name: str, result: Any = None, error: str = None):
        self.name = name
        self.result = result
        self.error = error


class CliResponse:
    """Wrapper around agy subprocess to be compatible with Router chunks interface.
    
    ARCHITECTURE: The PTY is ONLY for injecting input. Output is read via Chalice telemetry.
    Turn completion is signaled when handle_telemetry detects any of:
      - event_type == "Stop" (the Chalice Stop hook fired)
      - payload.fullyIdle == true (agent is fully idle and waiting for input)
      - state == "waiting_for_messages" (agent has background tasks running)
      - Interactive tool detected (ask_question / ask_permission)
    The Stop hook provides the transcriptPath to the child conversation's JSONL
    transcript. We read the agent's response from there.
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
        attempts = 0
        max_attempts = 2
        chalice_error = None
        
        while attempts < max_attempts:
            attempts += 1
            
            # Clear the event before we wait
            self.agent.turn_completed_event.clear()
            self.agent.aborted = False
            
            try:
                # Wait for Chalice to fire the Stop hook signaling generation is done.
                # Check for activity exactly as requested: 15 minute wait, then 2 minute grace period if silent.
                activity_timeout = 900  # 15 minutes
                grace_period = 120      # 2 minutes
                hard_ceiling = 7200     # 2 hours hard cap
                start_wait = time.time()
                
                while True:
                    now = time.time()
                    if now - start_wait > hard_ceiling:
                        logger.error("Agent hit hard ceiling timeout", conversation_id=self.agent.conversation_id)
                        yield Text(text="[Error: Agent hit hard 2-hour maximum execution limit]", step_index=0)
                        return

                    try:
                        # Sleep for the primary check interval (15 minutes)
                        chunk = await asyncio.wait_for(self.agent.chunk_queue.get(), timeout=activity_timeout)
                        if chunk is None:
                            break  # Turn completed successfully
                        yield chunk
                    except asyncio.TimeoutError:
                        now = time.time()
                        
                        # Has the agent emitted telemetry in the last 15 minutes?
                        if now - self.agent.last_active <= activity_timeout:
                            # Yes! It's active. The loop continues and waits another 15 minutes.
                            continue
                            
                        # No telemetry in 15 minutes. Enter the grace period.
                        logger.warning("Agent appears inactive, entering 2-minute grace period", conversation_id=self.agent.conversation_id)
                        
                        try:
                            # Give it 2 more minutes
                            chunk = await asyncio.wait_for(self.agent.chunk_queue.get(), timeout=grace_period)
                            if chunk is None:
                                break  # Turn completed during grace period
                            yield chunk
                        except asyncio.TimeoutError:
                            now = time.time()
                            # Check one last time before calling it
                            if now - self.agent.last_active <= (activity_timeout + grace_period):
                                # It came back alive during the grace period!
                                continue
                                
                            logger.error("Agent failed grace period and timed out", conversation_id=self.agent.conversation_id)
                            yield Text(text="[Error: Agent timed out (no activity detected for 17 minutes)]", step_index=0)
                            return
            except Exception as e:
                logger.error("Error waiting for agent turn completion", error=str(e), conversation_id=self.agent.conversation_id)
                yield Text(text="[Error: Internal wait error]", step_index=0)
                return

            # Check if we were woken by an abort (/stop) rather than clean completion
            if self.agent.aborted:
                logger.info("Agent turn aborted by /stop", conversation_id=self.agent.conversation_id)
                return

            # Check if the Stop hook carried an error (e.g., API rate limit / quota exhaustion).
            # Surface it immediately so the user sees what went wrong.
            chalice_error = self.agent._chalice_error
            self.agent._chalice_error = None  # Consume the error
            
            if chalice_error and "429" in str(chalice_error) and ("RESOURCE_EXHAUSTED" in str(chalice_error) or "quota" in str(chalice_error).lower()) and attempts < max_attempts:
                fallback_model = "gemini-3.1-pro-high"
                yield await self._handle_429_fallback(fallback_model)
                continue
            
            break

        # Turn is complete. Read the clean output from the transcript path
        transcript_path = self.agent._chalice_transcript_path
        if not transcript_path:
            transcript_path = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{self.agent.sdk_conversation_id}/.system_generated/logs/transcript.jsonl")
            
        if not transcript_path or not os.path.exists(transcript_path):
            error_msg = chalice_error or "No transcript available from agent"
            logger.error("No transcript path from Chalice telemetry",
                         conversation_id=self.agent.conversation_id,
                         transcript_path=transcript_path,
                         chalice_error=chalice_error)
            yield Text(text=f"⚠️ {error_msg}", step_index=0)
            return
            
        final_text, artifacts_created = self._parse_transcript(transcript_path)

        # Process syncing and generating the Discord notification
        if artifacts_created:
            port = getattr(self.agent.config, "dashboard_port", 8180)
            dash_url = f"http://127.0.0.1:{port}"
            art_text = "**📄 Artifacts Requiring Review:**\n"
            
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
            final_text = (final_text + "\n\n" + art_text) if final_text else art_text.strip()
            
        # Clear telemetry capture for next turn
        self.agent._artifacts_this_turn = []
        
        self.artifacts_count = len(artifacts_created)
        self.artifact_files = [os.path.join(channel_brain_dir, os.path.basename(a["file"])) for a in artifacts_created]
        self.tasks_count = getattr(self.agent, "_chalice_tasks_count", 0)
        self.subagents_count = getattr(self.agent, "_chalice_subagents_count", 0)
            
        # If the transcript had no model response but we got an API error, surface it
        if not final_text and chalice_error:
            final_text = f"⚠️ {chalice_error}"
        
        self.response_text = final_text
        yield Text(text=final_text, step_index=0)
        
        self.usage_metadata.total_token_count = (len(self.prompt) + len(final_text)) // 4

    async def _handle_429_fallback(self, fallback_model: str) -> Text:
        """Handles 429 quota exhaustion by injecting fallback model override and restarting agent."""
        app_data = os.path.expanduser("~/.gemini/antigravity-cli")
        sdk_brain_dir = os.path.join(app_data, "brain", self.agent.sdk_conversation_id)
        os.makedirs(sdk_brain_dir, exist_ok=True)
        model_txt_path = os.path.join(sdk_brain_dir, "model.txt")
        
        current_model = None
        if os.path.exists(model_txt_path):
            with open(model_txt_path, "r") as f:
                current_model = f.read().strip().strip("\"'")
                
        if current_model != fallback_model:
            logger.warning(f"Detected 429 quota exhaustion. Falling back to {fallback_model}.", conversation_id=self.agent.conversation_id)
            
            with open(model_txt_path, "w") as f:
                f.write(fallback_model)
                
            await self.agent.terminate()
            await self.agent.ensure_running()
            
            import uuid
            buf_name = f"buf-{uuid.uuid4().hex[:8]}"
            await async_run("tmux", "load-buffer", "-b", buf_name, "-", input=self.prompt + '\r')
            await async_run("tmux", "paste-buffer", "-r", "-b", buf_name, "-t", f"ganymede-{self.agent.sdk_conversation_id}")
            await async_run("tmux", "delete-buffer", "-b", buf_name)
            
            return Text(text=f"⚠️ *Model quota exhausted! Falling back to `{fallback_model}` and retrying your request...*\n", step_index=0)
        return Text(text="⚠️ *Model quota exhausted, but already using fallback model.*", step_index=0)

    def _parse_transcript(self, transcript_path: str) -> tuple[str, list]:
        """Parses the agent JSONL transcript to extract final text and tool calls."""
        final_text = ""
        current_turn_tool_calls = []
        try:
            with open(transcript_path, 'r') as f:
                lines = f.readlines()
                
            # Iterate backwards to find the last USER_INPUT to bound the turn
            start_idx = 0
            for i in range(len(lines)-1, -1, -1):
                try:
                    import json
                    data = json.loads(lines[i])
                    if data.get("type") == "USER_INPUT":
                        start_idx = i
                        break
                except Exception:
                    continue
                    
            # Collect all tool calls and the last non-empty final_text
            for i in range(start_idx, len(lines)):
                try:
                    import json
                    data = json.loads(lines[i])
                    if data.get("type") in ("PLANNER_RESPONSE", "TEXT_RESPONSE"):
                        content = data.get("content", "")
                        if content:
                            final_text = content
                        if data.get("tool_calls"):
                            current_turn_tool_calls.extend(data.get("tool_calls"))
                except Exception:
                    continue
        except Exception as e:
            logger.error("Failed to parse agent transcript", error=str(e), path=transcript_path)

        # Build message with tool calls formatting
        agent_message = final_text
        artifacts_created = []
        
        if current_turn_tool_calls:
            tool_text = ""
            for t in current_turn_tool_calls:
                t_name = t.get("name", "tool")
                args = t.get("args", {})
                args_formatted = ""
                args_obj = {}
                try:
                    import json
                    if isinstance(args, str):
                        args_obj = json.loads(args)
                        args_formatted = json.dumps(args_obj, indent=2)
                    else:
                        args_obj = args
                        args_formatted = json.dumps(args, indent=2)
                        
                    if t_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
                        metadata = args_obj.get("ArtifactMetadata", {})
                        if metadata and (metadata.get("UserFacing") or metadata.get("RequestFeedback")):
                            target_file = args_obj.get("TargetFile", "Unknown File")
                            summary = metadata.get("Summary", "")
                            if not any(a["file"] == target_file for a in artifacts_created):
                                artifacts_created.append({"file": target_file, "summary": summary})
                except Exception:
                    args_formatted = str(args)
                    
                if "ask_question" in t_name or "ask_permission" in t_name:
                    if not hasattr(self, "interactive_tools"):
                        self.interactive_tools = []
                    self.interactive_tools.append({"name": t_name, "args": args_obj})
                    continue

                tool_text += f"<details><summary><code>{t_name}</code></summary>\n\n```json\n{args_formatted}\n```\n\n</details>\n"
            
            final_text = tool_text.strip()
        else:
            final_text = ""

        # Merge artifacts globally captured from telemetry (which covers subagents!)
        captured_artifacts = getattr(self.agent, "_artifacts_this_turn", [])
        for art in captured_artifacts:
            if not any(a["file"] == art["file"] for a in artifacts_created):
                artifacts_created.append(art)

        if agent_message:
            final_text = (final_text + "\n\n" + agent_message) if final_text else agent_message
                
        return final_text, artifacts_created

    @property
    def chunks(self):
        return self._chunks_generator


class ManagedAgent:
    """Wraps a persistent conversation channel context mapped to an agy CLI session.
    
    IMPORTANT: This class spawns `agy` as a CLI subprocess. It does NOT use the
    Antigravity Python SDK directly. See CliResponse docstring for rationale.
    """
    
    # Serializes spawns that swap the model in agy's global settings.json.
    # Only one spawn can modify settings.json at a time to prevent races.
    _settings_lock = asyncio.Lock()


    def __init__(self, context_key: ContextKey, config: AppConfig, conversation_id: str, bot_namespace: str = "ganymede", ipc_port: int | None = None, manager=None):
        self.manager = manager
        self.context_key = context_key
        self.config = config
        self.last_active = time.time()
        self._lock = asyncio.Lock()
        self.conversation_id = conversation_id
        self.bot_namespace = bot_namespace
        self.ipc_port = ipc_port
        self.sdk_conversation_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, self.conversation_id))
        self.turn_completed_event = asyncio.Event()
        self.chunk_queue = asyncio.Queue()
        self.aborted = False
        self._chalice_transcript_path = None  # Set by handle_telemetry when Stop fires
        self._chalice_error = None  # Set by handle_telemetry if Stop fires with an error

    async def ensure_running(self):

        db_dir = os.path.expanduser("~/.gemini/antigravity-cli/conversations")
        db_path = os.path.join(db_dir, f"{self.sdk_conversation_id}.db")
        is_new_conversation = not os.path.exists(db_path)

        args = ["agy", "--conversation", self.sdk_conversation_id]
        
        project_name = self.context_key.project_name
            
        brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{self.conversation_id}")
        app_data = os.path.expanduser("~/.gemini/antigravity-cli")
        sdk_brain_dir = os.path.join(app_data, "brain", self.sdk_conversation_id)
        os.makedirs(brain_dir, exist_ok=True)
        if not os.path.exists(sdk_brain_dir):
            os.symlink(brain_dir, sdk_brain_dir)
            
        base_workspace = os.path.expanduser(getattr(self.config.agent, 'workspace', '~/.ganymede/workspace'))
        workspace_dir = os.path.join(base_workspace, project_name)
        os.makedirs(workspace_dir, exist_ok=True)
            
        if is_new_conversation:
            args.extend(["--new-project", project_name])
        else:
            args.extend(["--project", project_name])
            
        args.extend(["--mode", "accept-edits"])
            
        # Model resolution — ALWAYS pass --model to prevent agy's global
        # settings.json from applying its own model (which may be Opus/Claude).
        # Priority: model.txt (per-channel /model override) > config.agent.model
        model_txt = os.path.join(sdk_brain_dir, "model.txt")
        if os.path.exists(model_txt):
            with open(model_txt, "r") as f:
                resolved_model = f.read().strip().strip("\"'")
            if not resolved_model:
                resolved_model = self.config.agent.model
        else:
            resolved_model = self.config.agent.model

        # Reverse map human-readable names to agy slugs
        reverse_map = {
            "Gemini 3.1 Pro (High)": "gemini-3.1-pro-high",
            "Gemini 3.1 Pro (Low)": "gemini-3.1-pro-low",
            "Gemini Flash": "gemini-pro-agent",
            "Gemini 3.5 Flash (High)": "gemini-3.5-flash-high",
            "Gemini 3.5 Flash (Medium)": "gemini-3.5-flash-medium",
            "Gemini 3.5 Flash (Low)": "gemini-3.5-flash-low",
            "Gemini 3.6 Flash (High)": "gemini-3.6-flash-high",
            "Gemini 3.6 Flash (Medium)": "gemini-3.6-flash-medium",
            "Gemini 3.6 Flash (Low)": "gemini-3.6-flash-low",
            "Claude 3.5 Sonnet (4-6)": "claude-sonnet-4-6",
            "Claude Opus (Thinking)": "claude-opus-4-6-thinking",
        }
        resolved_model = reverse_map.get(resolved_model, resolved_model)

        args.extend(["--model", resolved_model])
            
        if getattr(self.config.agent, "skip_permissions", True):
            args.append("--dangerously-skip-permissions")
            
        session_name = f"ganymede-{self.sdk_conversation_id}"
        
        try:
            res = await async_run("tmux", "has-session", "-t", session_name, capture_output=True)
            if res.returncode == 0:
                logger.info("Found existing decoupled agy session, reattaching", session=session_name)
                # Fetch the PID of the pane to map to chalice
                res_pid = await async_run("tmux", "display-message", "-p", "-t", session_name, "#{pane_pid}", capture_output=True, text=True, check=False)
                pane_pid = res_pid.stdout.strip()
                if pane_pid:
                    self.pane_pid = int(pane_pid)
                    self.tmux_session_name = session_name
                    # Write PID map so broadcast.py can resolve our conv ID after restart
                    pid_map_dir = os.path.expanduser("~/.ganymede/data/pid_map")
                    os.makedirs(pid_map_dir, exist_ok=True)
                    with open(os.path.join(pid_map_dir, pane_pid), "w") as f:
                        f.write(self.conversation_id)
                return
        except Exception:
            pass

        subprocess_env = os.environ.copy()
        subprocess_env["SULCUS_NAMESPACE"] = getattr(self, "bot_namespace", "ganymede")
        subprocess_env["NO_COLOR"] = "1"
        subprocess_env["PYTHONUNBUFFERED"] = "1"
        subprocess_env["TERM"] = "dumb"
        subprocess_env["GANYMEDE_PORT"] = str(getattr(self.config.agent, "dashboard_port", 8180))
        if getattr(self, "ipc_port", None):
            subprocess_env["GANYMEDE_IPC_PORT"] = str(self.ipc_port)

        import shlex
        cmd = shlex.join(args)
        
        logger.info("Spawning decoupled agy in tmux", command=cmd, session=session_name, model=resolved_model, context=self.context_key)
        
        # Temporarily override the model in agy's global settings.json.
        # agy's --model flag is unreliable: settings.json takes precedence.
        # We serialize spawns with _settings_lock so concurrent sessions don't
        # clobber each other, and restore the original model after agy boots.
        settings_path = os.path.expanduser("~/.gemini/antigravity-cli/settings.json")
        async with ManagedAgent._settings_lock:
            original_model = None
            try:
                with open(settings_path, "r") as f:
                    settings = json.load(f)
                original_model = settings.get("model")
                settings_changed = False
                
                # Swap model if needed
                if original_model != resolved_model:
                    settings["model"] = resolved_model
                    settings_changed = True
                    logger.info("Swapped agy settings.json model for spawn", from_model=original_model, to_model=resolved_model)
                
                # Pre-trust the workspace so agy doesn't show a blocking trust dialog
                trusted = settings.get("trustedWorkspaces", [])
                if workspace_dir not in trusted:
                    trusted.append(workspace_dir)
                    settings["trustedWorkspaces"] = trusted
                    settings_changed = True
                    logger.info("Pre-trusted workspace in settings.json", path=workspace_dir)
                
                if settings_changed:
                    with open(settings_path, "w") as f:
                        json.dump(settings, f, indent=4)
            except (FileNotFoundError, json.JSONDecodeError):
                original_model = None
            
            await async_run("tmux", "new-session", "-d", "-s", session_name, "-c", workspace_dir, cmd, env=subprocess_env, check=True)
            
            # Fetch the PID of the pane to map to chalice
            res = await async_run("tmux", "display-message", "-p", "-t", session_name, "#{pane_pid}", capture_output=True, text=True, check=False)
            pane_pid = res.stdout.strip()
            if not pane_pid:
                raise RuntimeError(f"Failed to start agy: tmux session {session_name} exited immediately. Command: {cmd}")
            self.pane_pid = int(pane_pid)
            self.tmux_session_name = session_name
            
            pid_map_dir = os.path.expanduser("~/.ganymede/data/pid_map")
            os.makedirs(pid_map_dir, exist_ok=True)
            pid_map_file = os.path.join(pid_map_dir, pane_pid)
            with open(pid_map_file, "w") as f:
                f.write(self.conversation_id)
            
            # Wait for agy to boot up and display its interactive prompt.
            # We look for "? for shortcuts" which only appears on the real interactive
            # prompt, not on the trust dialog (which also contains ">").
            # If we see "trust" in the pane, auto-accept it with Enter.
            for _ in range(40):  # Wait up to 20 seconds
                res = await async_run("tmux", "capture-pane", "-p", "-S", "-", "-t", session_name, capture_output=True, text=True)
                pane_text = res.stdout
                
                # Detect and auto-dismiss the trust prompt
                if "Do you trust" in pane_text or "I trust this folder" in pane_text:
                    logger.warning("Trust prompt detected, auto-accepting", session=session_name)
                    await async_run("tmux", "send-keys", "-t", session_name, "Enter")
                    await asyncio.sleep(1)
                    continue
                
                if "? for shortcuts" in pane_text or "Error" in pane_text:
                    await asyncio.sleep(0.5)  # Give it just a moment to settle
                    break
                await asyncio.sleep(0.5)
            
            # Restore the original model so the user's IDE sessions aren't affected
            if original_model is not None and original_model != resolved_model:
                try:
                    with open(settings_path, "r") as f:
                        settings = json.load(f)
                    settings["model"] = original_model
                    with open(settings_path, "w") as f:
                        json.dump(settings, f, indent=4)
                except Exception:
                    pass


    async def chat(self, prompt: str) -> CliResponse:
        self.last_active = time.time()
        
        async with self._lock:
            prompt_stripped = prompt.strip()
            
            # Intercept /models
            if prompt_stripped == "/models":
                try:
                    result = await async_run("agy", "models", capture_output=True, text=True, check=True)
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
            if is_new and hasattr(self.config.bot, "identity") and self.config.bot.identity:
                sys_inst = self.config.bot.identity.replace("{bot_name}", self.bot_namespace)
                sys_inst = sys_inst.replace("{model_name}", self.config.agent.model)
                mission = getattr(self.config.agent, "mission_statement", "to be of help")
                sys_inst = sys_inst.replace("{mission_statement}", mission)
                
                user_name = "user"
                if self.manager:
                    user_name = self.manager.get_active_author_name(self.context_key) or "user"
                sys_inst = sys_inst.replace("{user_name}", user_name)
                
                # Allow plugins to inject context dynamically
                from ganymede.core.hooks import hooks
                sys_inst = await hooks.modify("on_agent_system_prompt", sys_inst, context=self.context_key)
                
                if prompt.startswith("/"):
                    parts = prompt.split(" ", 1)
                    cmd = parts[0]
                    rest = parts[1] if len(parts) > 1 else ""
                    final_prompt = f"{cmd} System Instructions:\n{sys_inst}\n\nUser Request:\n{rest}"
                else:
                    final_prompt = f"System Instructions:\n{sys_inst}\n\nUser Request:\n{prompt}"
            
            # Write prompt as simulated keystrokes to tmux session.
            import uuid
            buf_name = f"buf-{uuid.uuid4().hex[:8]}"
            await async_run("tmux", "load-buffer", "-b", buf_name, "-", input=final_prompt)
            
            session_target = f"ganymede-{self.sdk_conversation_id}"
            await async_run("tmux", "paste-buffer", "-r", "-b", buf_name, "-t", session_target)
            await async_run("tmux", "delete-buffer", "-b", buf_name)
            # Submit the pasted prompt. A raw Enter (C-m) submits in prompt_toolkit.
            await async_run("tmux", "send-keys", "-t", session_target, "Enter")
            
            return CliResponse(self, prompt)

    async def terminate(self) -> None:
        """Gracefully terminate the active agy CLI subprocess, falling back to force kill."""
        # Signal abort FIRST so the blocked CliResponse generator wakes up immediately
        self.aborted = True
        self.turn_completed_event.set()

        if getattr(self, "tmux_session_name", None):
            logger.info("Gracefully closing decoupled tmux session", session=self.tmux_session_name)
            try:
                # Send the /exit command to the CLI to gracefully shut down plugins, server, and telemetry
                await async_run("tmux", "send-keys", "-t", self.tmux_session_name, "/exit", "Enter")
                
                # Wait up to 5 seconds for it to exit gracefully
                for _ in range(10):
                    await asyncio.sleep(0.5)
                    out, err, code = await async_run("tmux", "has-session", "-t", self.tmux_session_name, capture_output=True)
                    if code != 0:
                        break # Session is dead!
                else:
                    logger.warning("Session did not close gracefully in time, force killing", session=self.tmux_session_name)
                    await async_run("tmux", "kill-session", "-t", self.tmux_session_name, capture_output=True)
            except Exception as e:
                logger.error("Error terminating tmux session", error=str(e))
                # Fallback force kill
                try:
                    await async_run("tmux", "kill-session", "-t", self.tmux_session_name, capture_output=True)
                except:
                    pass
            finally:
                if getattr(self, "pane_pid", None):
                    pid_map_file = os.path.join(
                        os.path.expanduser("~/.ganymede/data/pid_map"),
                        str(self.pane_pid))
                    try:
                        os.remove(pid_map_file)
                    except FileNotFoundError:
                        pass
                self.tmux_session_name = None
                self.pane_pid = None

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
        valid_events = ("Agent Lifecycle Hook", "PreToolUse", "PostToolUse", "Stop", "AgentLifecycle", "PreInvocation")
        if data.get("event") not in valid_events:
            return
            
        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            return
        
        # Match on our GANYMEDE_CONV_ID, not agy's internal conversation ID
        ganymede_conv_id = data.get("ganymede_conv_id")
        if not ganymede_conv_id:
            return
        
        # Only process telemetry that matches a ganymede-managed agent.
        # Unrelated agy sessions (IDE, other CLI) also broadcast via Chalice
        # but don't have matching agents — skip them silently.
        has_match = any(a.conversation_id == ganymede_conv_id for a in self._agents.values())
        if not has_match:
            # Only log mismatch for ganymede-prefixed IDs (genuine PID map issues).
            # Non-prefixed IDs are just unrelated IDE/CLI sessions — silently ignore.
            if ganymede_conv_id.startswith("ganymede_"):
                expected = [a.conversation_id for a in self._agents.values()]
                logger.warning("Telemetry conv_id mismatch — ganymede session not matched",
                               received=ganymede_conv_id,
                               expected=expected)
            return
            
        # Update activity timestamp to prevent idle reaping during long tasks
        for agent in self._agents.values():
            if agent.conversation_id == ganymede_conv_id:
                agent.last_active = time.time()
                logger.debug("Telemetry matched managed agent", telemetry_event=data.get("event"), ganymede_conv_id=ganymede_conv_id)
                
        tool_call = payload.get("toolCall", {})
        if isinstance(tool_call, str):
            tool_call = {}
            
        is_interactive_tool = False
        event_type = data.get("event", "")
        if not payload.get("error") and event_type == "PreToolUse":
            tool_name = tool_call.get("name", "")
            if tool_name in ("default_api:ask_question", "default_api:ask_permission", "ask_question", "ask_permission"):
                is_interactive_tool = True

        state = payload.get("state", "")
        # Wake up the stream if fully idle, waiting for messages, interactive tool, or if the event is literally "Stop"
        is_turn_complete = event_type == "Stop" or payload.get("fullyIdle") or state == "waiting_for_messages" or is_interactive_tool

        if is_turn_complete:
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
                    agent.chunk_queue.put_nowait(None)
                    return
                    
        # Catch live tool calls globally (captures subagent artifacts)
        for agent in self._agents.values():
            if agent.conversation_id == ganymede_conv_id:
                if not hasattr(agent, "_artifacts_this_turn"):
                    agent._artifacts_this_turn = []
                tool_call = payload.get("toolCall")
                
                # Yield intermediate chunks to the queue for realtime Discord streaming
                if event_type == "PreToolUse":
                    if isinstance(tool_call, dict):
                        t_name = tool_call.get("name", "")
                        t_args = tool_call.get("args", {})
                        if isinstance(t_args, str):
                            try:
                                t_args = json.loads(t_args)
                            except Exception:
                                t_args = {}
                        agent.chunk_queue.put_nowait(ToolCall(t_name, t_args))
                elif event_type == "PostToolUse":
                    if isinstance(tool_call, dict):
                        t_name = tool_call.get("name", "")
                        t_err = payload.get("error")
                        t_res = payload.get("result")
                        agent.chunk_queue.put_nowait(ToolResult(t_name, t_res, t_err))
                
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
