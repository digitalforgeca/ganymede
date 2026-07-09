import asyncio
import time
import os
import structlog
from typing import Any
from google.antigravity.types import Text
from ganymede.core import ContextKey
from ganymede.config import AppConfig
from ganymede.core.quota import QuotaTracker

logger = structlog.get_logger()


class MockUsage:
    def __init__(self):
        self.total_token_count = 0


class CliResponse:
    """Wrapper around agy subprocess stdout stream to be compatible with Router chunks interface."""

    def __init__(self, process: asyncio.subprocess.Process, prompt: str):
        self.process = process
        self.prompt = prompt
        self.response_text = ""
        self.usage_metadata = MockUsage()
        self._chunks_generator = self._read_chunks()

    async def _read_chunks(self):
        # Read from stdout in chunks to provide real-time streaming feedback
        while True:
            data = await self.process.stdout.read(128)
            if not data:
                break
            text = data.decode(errors="replace")
            self.response_text += text
            yield Text(text=text, step_index=0)

        # Wait for the process to exit cleanly
        await self.process.wait()
        
        # Estimate total tokens based on prompt and response size (~4 characters per token)
        estimated_input_tokens = len(self.prompt) // 4
        estimated_output_tokens = len(self.response_text) // 4
        self.usage_metadata.total_token_count = estimated_input_tokens + estimated_output_tokens
        if self.process.returncode != 0:
            stderr_data = await self.process.stderr.read()
            err_msg = stderr_data.decode(errors="replace").strip()
            logger.error("agy CLI failed", code=self.process.returncode, error=err_msg)
            raise RuntimeError(f"agy error (code {self.process.returncode}): {err_msg}")

    @property
    def chunks(self):
        return self._chunks_generator


class ManagedAgent:
    """Wraps a persistent conversation channel context mapped to an agy CLI session."""

    def __init__(self, context_key: ContextKey, config: AppConfig, conversation_id: str, bot_namespace: str = "ganymede", ipc_port: int | None = None):
        self.context_key = context_key
        self.config = config
        self.last_active = time.time()
        self._lock = asyncio.Lock()
        self.conversation_id = conversation_id
        self.bot_namespace = bot_namespace
        self.ipc_port = ipc_port
        self.current_process: asyncio.subprocess.Process | None = None

    async def chat(self, prompt: str) -> CliResponse:
        self.last_active = time.time()
        
        async with self._lock:
            # Check if database already exists for this conversation
            db_dir = os.path.expanduser("~/.gemini/antigravity-cli/conversations")
            db_path = os.path.join(db_dir, f"{self.conversation_id}.db")
            needs_rename = not os.path.exists(db_path)
            
            before_files = set()
            if needs_rename and os.path.exists(db_dir):
                try:
                    before_files = set(os.listdir(db_dir))
                except Exception:
                    pass

            agy_path = "agy"
            
            args = [
                agy_path,
                "--conversation", self.conversation_id,
            ]
            
            # If yolo mode (require_approval is false), skip permission prompts
            if not getattr(self.config.agent, "require_approval", True):
                args.append("--dangerously-skip-permissions")
                
            args.extend(["--print", prompt])
            
            logger.info("Executing agy CLI subprocess", command=" ".join(args), context=self.context_key)
            
            # Build environment variables copy and inject SULCUS_NAMESPACE and GANYMEDE_IPC_PORT
            subprocess_env = os.environ.copy()
            subprocess_env["SULCUS_NAMESPACE"] = self.bot_namespace
            if self.ipc_port:
                subprocess_env["GANYMEDE_IPC_PORT"] = str(self.ipc_port)

            # Spawn the subprocess with stdin redirected to DEVNULL to prevent terminal TTY suspends (SIGTTIN)
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subprocess_env,
            )
            self.current_process = process
            
            response = CliResponse(process, prompt)
            if needs_rename:
                asyncio.create_task(self._post_chat_rename(response, db_dir, before_files))
                
            return response

    async def _post_chat_rename(self, response: CliResponse, db_dir: str, before_files: set[str]):
        try:
            # Wait for the process to exit cleanly
            await response.process.wait()
            
            if not os.path.exists(db_dir):
                return
                
            after_files = set(os.listdir(db_dir))
            new_files = after_files - before_files
            
            new_db_file = None
            for f in new_files:
                if f.endswith(".db") and f != f"{self.conversation_id}.db":
                    new_db_file = f
                    break
                    
            if new_db_file:
                old_base = new_db_file[:-3]
                old_path = os.path.join(db_dir, new_db_file)
                new_path = os.path.join(db_dir, f"{self.conversation_id}.db")
                
                logger.info("Renaming newly created agy database to friendly name", old=old_path, new=new_path)
                
                import aiosqlite
                async with aiosqlite.connect(old_path) as conn:
                    await conn.execute("UPDATE trajectory_meta SET cascade_id = ?", (self.conversation_id,))
                    await conn.commit()
                    
                os.rename(old_path, new_path)
                
                # Also rename shm and wal files if present
                for ext in (".db-shm", ".db-wal"):
                    old_ext_path = os.path.join(db_dir, f"{old_base}{ext}")
                    new_ext_path = os.path.join(db_dir, f"{self.conversation_id}{ext}")
                    if os.path.exists(old_ext_path):
                        try:
                            os.rename(old_ext_path, new_ext_path)
                        except Exception:
                            pass
        except Exception as e:
            logger.error("Failed to rename agy database to friendly name", error=str(e))

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

    async def close(self):
        await self.terminate()


class AgentManager:
    """Manages channel-to-conversation mapping and CLI execution instances."""

    def __init__(self, config: AppConfig, quota_tracker: QuotaTracker = None, db: Any = None):
        self.config = config
        self.quota_tracker = quota_tracker
        self.db = db
        self._agents: dict[ContextKey, ManagedAgent] = {}
        self._active_authors: dict[ContextKey, str] = {}
        self._active_author_names: dict[ContextKey, str] = {}
        self.adapter = None

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

    async def get_or_create(self, context: ContextKey, channel_name: str | None = None) -> ManagedAgent:
        if context in self._agents:
            managed = self._agents[context]
            managed.last_active = time.time()
            return managed

        # Check budget first
        if self.quota_tracker:
            allowed = await self.quota_tracker.check_budget(context)
            if not allowed:
                raise RuntimeError("Request blocked due to token/request budget exhaustion.")

        # Resolve or generate a persistent conversation ID that agy supports
        conversation_id = None
        if self.db:
            conversation_id = await self.db.get_conversation_id_by_context(context)
        
        if not conversation_id:
            # If not in DB, construct a friendly name from channel name
            import re
            
            # Sanitization helper
            def sanitize_name(name: str) -> str:
                if not name:
                    return "unknown"
                # Convert to lowercase and replace spaces/hyphens/special chars with underscores
                s = name.lower().replace(" ", "_").replace("-", "_")
                # Remove non-alphanumeric/non-underscore characters
                s = re.sub(r"[^a-z0-9_]", "", s)
                # Deduplicate underscores
                s = re.sub(r"_+", "_", s)
                return s.strip("_")
            
            # Fetch channel name if not provided
            if not channel_name and self.adapter:
                try:
                    channel = await self.adapter._resolve_channel(context)
                    if channel:
                        if hasattr(channel, "name"):
                            channel_name = channel.name
                        elif hasattr(channel, "recipient"):
                            channel_name = f"dm_{channel.recipient.name}"
                except Exception as e:
                    logger.warn("Failed to resolve channel name for friendly ID", error=str(e))
            
            friendly_name = sanitize_name(channel_name)
            
            conversation_id = f"ganymede_{context.platform}_{friendly_name}_{context.channel_id}"
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
        if managed := self._agents.pop(context, None):
            await managed.close()

    async def destroy_all(self) -> None:
        logger.info("Terminating all active agent sessions")
        keys = list(self._agents.keys())
        for k in keys:
            await self.destroy(k)
