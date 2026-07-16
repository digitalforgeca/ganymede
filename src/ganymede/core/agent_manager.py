import asyncio
import time
import os
import json
import structlog
from typing import Any
from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig
from google.antigravity.types import Text, ToolCall, ToolResult, Thought
from ganymede.core import ContextKey
from ganymede.config import AppConfig
from ganymede.core.quota import QuotaTracker

logger = structlog.get_logger()


class ManagedAgent:
    """Wraps a persistent conversation channel context mapped to an Antigravity SDK Agent session."""

    def __init__(self, context_key: ContextKey, config: AppConfig, conversation_id: str, bot_namespace: str = "ganymede", ipc_port: int | None = None):
        self.context_key = context_key
        self.config = config
        self.last_active = time.time()
        self._lock = asyncio.Lock()
        self.conversation_id = conversation_id
        self.bot_namespace = bot_namespace
        self.ipc_port = ipc_port
        self.agent: Agent | None = None

    async def _init_agent(self):
        """Initializes the SDK agent if not already connected."""
        if self.agent and self.agent.is_started:
            return

        brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{self.conversation_id}")
        
        # Check model override
        model_override = None
        model_path = os.path.join(brain_dir, "model.txt")
        if os.path.exists(model_path):
            try:
                with open(model_path, "r") as f:
                    model_override = f.read().strip()
            except Exception:
                pass
        if not model_override and hasattr(self.config.agent, "model"):
            model_override = self.config.agent.model

        # Build system instructions
        sys_inst = ""
        if hasattr(self.config.agent, "system_instructions") and self.config.agent.system_instructions:
            sys_inst = self.config.agent.system_instructions
            sys_inst = sys_inst.replace("{bot_name}", getattr(self, "bot_namespace", "Agent"))
            sys_inst = sys_inst.replace("{model_name}", model_override or "default model")
            user_id = getattr(self.context_key, 'user_id', 'Unknown')
            sys_inst = sys_inst.replace("{user_name}", f"User {user_id}")
            sys_inst = sys_inst.replace("{mission_statement}", getattr(self.config.agent, "mission_statement", "assisting the user"))

        workspace_dir = os.path.expanduser(self.config.agent.workspace)
        os.makedirs(workspace_dir, exist_ok=True)
        
        # NOTE: We switched from the `agy` CLI subprocess to the Antigravity Python SDK
        # This native integration prevents the 'bubbletea: error opening TTY' crash and allows
        # true async background tasks that won't panic the gateway when upstream servers restart!
        if getattr(self, "ipc_port", None):
            os.environ["GANYMEDE_IPC_PORT"] = str(self.ipc_port)
            
        # Ensure conversation_id conforms to Antigravity's regex: [a-zA-Z0-9-]
        sanitized_conv_id = self.conversation_id.replace("_", "-")
            
        agent_config = LocalAgentConfig(
            system_instructions=sys_inst,
            capabilities=CapabilitiesConfig(),
            workspace=workspace_dir,
            conversation_id=sanitized_conv_id,
            app_data_dir=os.path.expanduser("~/.gemini/antigravity-cli")
        )
        
        # Note: LocalAgentConfig expects ModelTarget objects for model routing, but the SDK
        # also supports string fallbacks natively in the connection initialization. 
        # For simplicity, if model_override exists we pass it via kwargs or assume default.
        
        self.agent = Agent(agent_config)
        await self.agent.__aenter__()

    async def chat(self, prompt: str) -> Any:
        self.last_active = time.time()
        async with self._lock:
            await self._init_agent()
            response = await self.agent.chat(prompt)
            # The ChatResponse yields `.chunks` which is natively consumed by Router._stream_response_chunks!
            return response

    async def terminate(self) -> None:
        """Forcefully terminate the active SDK agent session if running."""
        if self.agent and self.agent.is_started:
            logger.info("Terminating active SDK agent session", conversation_id=self.conversation_id)
            try:
                await self.agent.__aexit__(None, None, None)
            except Exception as e:
                logger.error("Error terminating SDK agent", error=str(e))
            finally:
                self.agent = None

    async def close(self):
        await self.terminate()


class AgentManager:
    """Manages channel-to-conversation mapping and SDK execution instances."""

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
                conversation_id = f"ganymede-{context.platform}-{context.channel_id}"
                if context.thread_id:
                    conversation_id += f"-{context.thread_id}"
                
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
