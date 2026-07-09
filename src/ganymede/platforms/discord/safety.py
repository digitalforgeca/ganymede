import structlog
import discord
import json
from typing import Any
from google.antigravity.types import ToolCall
from ganymede.core import ContextKey
from ganymede.config import AppConfig
from ganymede.core.safety import ApprovalHook, BaseApprovalProvider

logger = structlog.get_logger()
active_adapter = None


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


class DiscordApprovalHook(ApprovalHook):
    """Backwards-compatible wrapper that automatically uses the DiscordApprovalProvider."""
    
    def __init__(self, context_key: ContextKey, config: AppConfig):
        # Dynamically resolve active_adapter to keep backward compatibility with test suites
        from ganymede.core.safety import active_adapter as core_adapter
        import ganymede.platforms.discord.safety as ds
        adapter = core_adapter or ds.active_adapter
        provider = DiscordApprovalProvider(adapter) if adapter else None
        super().__init__(context_key, config, provider=provider)
