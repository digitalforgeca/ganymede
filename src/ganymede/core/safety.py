import structlog
import discord
import json
import asyncio
from typing import Any
from google.antigravity.hooks import PreToolCallDecideHook, HookContext
from google.antigravity.types import HookResult, ToolCall
from ganymede.core import ContextKey
from ganymede.config import AppConfig

logger = structlog.get_logger()

class ApprovalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60.0)
        self.approved = None
        self.approver_name = None

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, custom_id="approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_perms = getattr(interaction.user, "guild_permissions", None)
        is_admin = False
        if user_perms:
            is_admin = user_perms.administrator or user_perms.manage_guild
        elif interaction.guild is None:
            is_admin = True

        if not is_admin:
            await interaction.response.send_message("❌ You are not authorized to approve this tool call.", ephemeral=True)
            return

        self.approved = True
        self.approver_name = interaction.user.name
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.red, custom_id="deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_perms = getattr(interaction.user, "guild_permissions", None)
        is_admin = False
        if user_perms:
            is_admin = user_perms.administrator or user_perms.manage_guild
        elif interaction.guild is None:
            is_admin = True

        if not is_admin:
            await interaction.response.send_message("❌ You are not authorized to approve this tool call.", ephemeral=True)
            return

        self.approved = False
        self.approver_name = interaction.user.name
        self.stop()
        await interaction.response.defer()

active_adapter: Any = None

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


class DiscordApprovalProvider(BaseApprovalProvider):
    """Discord-specific approval provider using Embeds and Button Views."""
    
    def __init__(self, adapter: Any):
        self.adapter = adapter

    async def request_approval(self, context: ContextKey, data: ToolCall, original_desc: str) -> bool:
        channel = await self.adapter._resolve_channel(context)
        if not channel:
            logger.error("Could not resolve channel for tool call approval", context_key=context)
            return False

        embed = discord.Embed(
            title="🔒 Tool Call Approval Request",
            description=original_desc,
            color=discord.Color.orange()
        )
        
        view = ApprovalView()
        
        try:
            approval_msg = await channel.send(embed=embed, view=view)
        except Exception as e:
            logger.error("Failed to send approval message to channel", error=str(e))
            return False

        # Wait for user input or timeout
        await view.wait()

        # Update outcome
        if view.approved is True:
            outcome_desc = f"✅ Approved by {view.approver_name}"
            embed.color = discord.Color.green()
        elif view.approved is False:
            outcome_desc = f"❌ Denied by {view.approver_name}"
            embed.color = discord.Color.red()
        else:
            outcome_desc = "⚠️ Timed out (no response within 60s)"
            embed.color = discord.Color.red()

        embed.description = f"{original_desc}\n\n**Outcome**: {outcome_desc}"

        # Disable all buttons
        for child in view.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        try:
            await approval_msg.edit(embed=embed, view=view)
        except Exception as e:
            logger.error("Failed to edit approval message with outcome", error=str(e))

        return view.approved is True

    async def update_status(self, context: ContextKey, status_text: str) -> None:
        try:
            await self.adapter.update_streaming_status(context, status_text)
        except Exception as e:
            logger.debug("Failed to update tool execution status", error=str(e))


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


class DiscordApprovalHook(ApprovalHook):
    """Backwards-compatible wrapper that automatically uses the DiscordApprovalProvider."""
    
    def __init__(self, context_key: ContextKey, config: AppConfig):
        global active_adapter
        provider = DiscordApprovalProvider(active_adapter) if active_adapter else None
        super().__init__(context_key, config, provider=provider)
