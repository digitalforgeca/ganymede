import structlog
import json
import asyncio
from typing import Any
from google.antigravity.hooks import PreToolCallDecideHook, HookContext
from google.antigravity.types import HookResult, ToolCall
from ganymede.core import ContextKey
from ganymede.config import AppConfig

logger = structlog.get_logger()
active_adapter = None


class BaseApprovalProvider:
    """Abstract base class for platform-specific approval providers."""
    
    async def request_approval(self, context: ContextKey, data: ToolCall, original_desc: str) -> bool:
        """Prompt user for approval. Returns True if approved, False otherwise."""
        raise NotImplementedError()

    async def update_status(self, context: ContextKey, status_text: str) -> None:
        """Optional: Update the platform's execution status indicator."""
        pass


class ConsoleApprovalProvider(BaseApprovalProvider):
    """Fallback console-based provider that logs tool executions and auto-approves."""
    
    async def request_approval(self, context: ContextKey, data: ToolCall, original_desc: str) -> bool:
        logger.info("Console Approval Hook triggered (auto-approving)", tool=data.name, args=data.args)
        return True

    async def update_status(self, context: ContextKey, status_text: str) -> None:
        logger.info(f"Status update: {status_text}", context=context)


class ApprovalHook(PreToolCallDecideHook):
    """Core platform-agnostic safety hook for tool execution approvals."""

    def __init__(self, context_key: ContextKey, config: AppConfig, provider: BaseApprovalProvider | None = None):
        self.context_key = context_key
        self.config = config
        self.provider = provider or ConsoleApprovalProvider()

    async def run(self, context: HookContext, data: ToolCall) -> HookResult:
        tool_name = str(data.name)
        base_name = tool_name.split(":")[-1] if ":" in tool_name else tool_name

        # 1. Update real-time tool execution status
        try:
            from ganymede.core.status import format_tool_status
            status_text = format_tool_status(data.name, data.args or {})
            # Route to provider (non-blocking task)
            asyncio.create_task(self.provider.update_status(self.context_key, status_text))
        except Exception as e:
            logger.debug("Failed to invoke provider update_status", error=str(e))

        # 2. Check global safety approval requirement toggle
        if not getattr(self.config.agent, "require_approval", True):
            return HookResult(allow=True)

        # 3. Check tool whitelist
        auto_approved = getattr(self.config.agent, "auto_approve_tools", [])
        if base_name in auto_approved:
            return HookResult(allow=True)

        # 4. Check active author elevation status (if supported by provider)
        if hasattr(self.provider, "adapter") and self.provider.adapter:
            adapter = self.provider.adapter
            if adapter.router and adapter.router.agent_manager:
                author_id = adapter.router.agent_manager.get_active_author(self.context_key)
                elevated_users = getattr(self.config.agent, "elevated_users", [])
                if author_id and author_id in elevated_users:
                    logger.info("Auto-approving tool call for elevated developer", user_id=author_id, tool=tool_name)
                    return HookResult(allow=True)

        # 5. Format parameters desc for approval prompt
        args_str = json.dumps(data.args, indent=2)
        if len(args_str) > 1500:
            args_str = args_str[:1500] + "\n... (truncated)"
        
        original_desc = f"**Tool**: `{tool_name}`\n**Arguments**:\n```json\n{args_str}\n```"

        # 6. Request approval from provider
        allowed = await self.provider.request_approval(self.context_key, data, original_desc)
        if allowed:
            return HookResult(allow=True)
        else:
            return HookResult(allow=False, message="Tool call denied.")

