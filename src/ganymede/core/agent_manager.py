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


class MockUsage:
    def __init__(self):
        self.total_token_count = 0


class CliResponse:
    """Wrapper around agy subprocess to be compatible with Router chunks interface.
    
    Instead of scraping the PTY output, we rely on the Chalice plugin's 'Stop' telemetry
    event to signal completion, and then we parse the clean output from the JSONL transcript.
    """

    def __init__(self, agent_instance, prompt: str, transcript_path: str):
        self.agent = agent_instance
        self.prompt = prompt
        self.transcript_path = transcript_path
        self.response_text = ""
        self.usage_metadata = MockUsage()
        self._chunks_generator = self._read_chunks()

    async def _read_chunks(self):
        # Clear the event before we wait
        self.agent.turn_completed_event.clear()
        
        try:
            # Wait for Chalice to fire the Stop hook signaling generation is done
            await asyncio.wait_for(self.agent.turn_completed_event.wait(), timeout=600)
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for agent to finish turn", conversation_id=self.agent.conversation_id)
            yield Text(text="[Error: Agent timed out while generating response]", step_index=0)
            return

        # Turn is complete. Read the clean output from transcript_full.jsonl
        full_transcript = self.transcript_path.replace("transcript.jsonl", "transcript_full.jsonl")
        if not os.path.exists(full_transcript):
            full_transcript = self.transcript_path
            
        final_text = ""
        tool_calls = []
        try:
            if os.path.exists(full_transcript):
                with open(full_transcript, 'r') as f:
                    for line in f:
                        if not line.strip(): continue
                        try:
                            data = json.loads(line)
                            if data.get("type") in ("PLANNER_RESPONSE", "TEXT_RESPONSE"):
                                final_text = data.get("content", "")
                                tool_calls = data.get("tool_calls", [])
                        except json.JSONDecodeError:
                            continue
                            
            if tool_calls:
                tool_text = "\n\n*⚒️ Tools Used:*\n"
                for t in tool_calls:
                    t_name = t.get('name') or t.get('function', {}).get('name') or 'tool'
                    args = t.get('args') or t.get('function', {}).get('arguments') or {}
                    try:
                        args_formatted = json.dumps(json.loads(args) if isinstance(args, str) else args, indent=2)
                    except Exception:
                        args_formatted = str(args)
                    tool_text += f"<details><summary><code>{t_name}</code></summary>\n\n```json\n{args_formatted}\n```\n\n</details>\n"
                
                final_text = (final_text + tool_text) if final_text else tool_text.strip()
                
            self.response_text = final_text
            yield Text(text=final_text, step_index=0)
            
            self.usage_metadata.total_token_count = (len(self.prompt) + len(final_text)) // 4
        except Exception as e:
            logger.error("Failed to read transcript for output", error=str(e))
            yield Text(text="[Error: Failed to parse agent transcript]", step_index=0)

    @property
    def chunks(self):
        return self._chunks_generator


class ManagedAgent:
    """Wraps a persistent conversation channel context mapped to an agy CLI session.
    
    IMPORTANT: This class spawns `agy` as a CLI subprocess. It does NOT use the
    Antigravity Python SDK directly. See CliResponse docstring for rationale.
    """

    def __init__(self, context_key: ContextKey, config: AppConfig, conversation_id: str, bot_namespace: str = "ganymede", ipc_port: int | None = None):
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
        
        project_name = f"{self.context_key.platform}-{self.context_key.channel_id}"
        if self.context_key.thread_id:
            project_name += f"-{self.context_key.thread_id}"
            
        brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{self.conversation_id}")
        app_data = os.path.expanduser("~/.gemini/antigravity-cli")
        sdk_brain_dir = os.path.join(app_data, "brain", self.sdk_conversation_id)
        os.makedirs(brain_dir, exist_ok=True)
        if not os.path.exists(sdk_brain_dir):
            os.symlink(brain_dir, sdk_brain_dir)
            
        if is_new_conversation:
            args.extend(["--new-project", project_name])
            
        # Model, skip_permissions, etc
        if hasattr(self.config.agent, "model"):
            args.extend(["--model", self.config.agent.model])
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
        
        # Start background sink
        asyncio.create_task(self._sink_pty_output())
        
        # Wait a moment for agy to boot up before injecting initial input
        await asyncio.sleep(2)

    async def chat(self, prompt: str) -> CliResponse:
        self.last_active = time.time()
        
        async with self._lock:
            await self.ensure_running()
            
            # Inject system instructions for new conversations as a compound prompt
            db_dir = os.path.expanduser("~/.gemini/antigravity-cli/conversations")
            is_new = not os.path.exists(os.path.join(db_dir, f"{self.sdk_conversation_id}.db"))
            
            final_prompt = prompt
            if is_new and hasattr(self.config.agent, "system_instructions") and self.config.agent.system_instructions:
                sys_inst = self.config.agent.system_instructions.replace("{bot_name}", self.bot_namespace)
                sys_inst = sys_inst.replace("{model_name}", getattr(self.config.agent, "model", "default model"))
                final_prompt = f"System Instructions:\n{sys_inst}\n\nUser Request:\n{prompt}"
            
            # Write prompt as simulated keystrokes to the PTY
            os.write(self.master_fd, (final_prompt + '\n').encode('utf-8'))
            
            transcript_path = os.path.join(
                os.path.expanduser("~/.gemini/antigravity-cli/brain"), 
                self.sdk_conversation_id, 
                ".system_generated", "logs", "transcript.jsonl"
            )
            
            return CliResponse(self, prompt, transcript_path)

    async def terminate(self) -> None:
        """Forcefully terminate the active agy CLI subprocess if running."""
        if self.current_process:
            logger.info("Terminating active agy subprocess", conversation_id=self.conversation_id)
            try:
                self.current_process.terminate()
                try:
                    await asyncio.wait_for(self.current_process.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    logger.warn("Subprocess did not exit gracefully, killing it", conversation_id=self.conversation_id)
                    self.current_process.kill()
                    await self.current_process.wait()
            except Exception as e:
                logger.error("Error terminating agy subprocess", error=str(e))
            finally:
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

        # Register Chalice telemetry listener to wake up chat sessions
        from ganymede.core.web import dashboard_instance
        if dashboard_instance:
            if not hasattr(dashboard_instance, "telemetry_listeners"):
                dashboard_instance.telemetry_listeners = []
            dashboard_instance.telemetry_listeners.append(self.handle_telemetry)

    async def handle_telemetry(self, data: dict):
        """Wake up ManagedAgent when Chalice signals turn completion.
        
        Chalice sends all events as "Agent Lifecycle Hook". A completed turn
        is identified by payload.fullyIdle=true with a terminationReason present.
        The conversationId lives inside the payload dict, not at the top level.
        """
        if data.get("event") != "Agent Lifecycle Hook":
            return
            
        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            return
            
        if payload.get("fullyIdle"):
            conv_id = payload.get("conversationId")
            if conv_id:
                for agent in self._agents.values():
                    if agent.sdk_conversation_id == conv_id:
                        logger.info("Chalice signaled turn complete", conversation_id=conv_id, reason=payload.get("terminationReason"))
                        agent.turn_completed_event.set()

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

    async def get_or_create(self, context: ContextKey) -> ManagedAgent:
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
                conversation_id = f"ganymede_{context.platform}_{context.channel_id}"
                if context.thread_id:
                    conversation_id += f"_{context.thread_id}"
                
            if self.db:
                await self.db.save_conversation_mapping(conversation_id, context)

        bot_namespace = "ganymede"
        ipc_port = None
        if self.adapter:
            if hasattr(self.adapter, "get_bot_namespace"):
                bot_namespace = self.adapter.get_bot_namespace()
            if hasattr(self.adapter, "ipc_server") and self.adapter.ipc_server and hasattr(self.adapter.ipc_server, "port"):
                ipc_port = self.adapter.ipc_server.port

        managed = ManagedAgent(context, self.config, conversation_id, bot_namespace, ipc_port)
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
