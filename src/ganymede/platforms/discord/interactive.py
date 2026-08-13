import discord
import hashlib
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

class InteractiveToolView(discord.ui.View):
    def __init__(self, interactive_tools: list, callback: Callable[[str, discord.Interaction], Awaitable[None]]):
        super().__init__(timeout=None)
        self.callback = callback
        
        for tool in interactive_tools:
            name = tool.get("name", "")
            args = tool.get("args", {})
            
            if name in ("ask_question", "default_api:ask_question"):
                questions = args.get("questions", [])
                for q_idx, q in enumerate(questions):
                    options = q.get("options", [])
                    # If more than 5 options, or adding buttons would exceed 25 components, use Select
                    if len(options) > 5 or len(self.children) + len(options) > 25:
                        self.add_item(self._create_select(q.get("question", "Select an option"), options, str(q_idx)))
                    else:
                        for i, opt in enumerate(options):
                            self.add_item(self._create_button(opt, f"q{q_idx}_{i}"))
                        
            elif name in ("ask_permission", "default_api:ask_permission"):
                if len(self.children) <= 23:
                    self.add_item(self._create_button("Yes", "approve", discord.ButtonStyle.green))
                    self.add_item(self._create_button("No", "deny", discord.ButtonStyle.red))

    def _get_stable_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:8]

    def _create_select(self, placeholder: str, options: list, custom_id_suffix: str):
        # Truncate placeholder to 100 max
        placeholder = placeholder[:100]
        # Max 25 options per select
        choices = [discord.SelectOption(label=opt[:100], value=opt[:100]) for opt in options[:25]]
        
        # custom_id must be unique but stable
        stable_hash = self._get_stable_hash(placeholder)
        select = discord.ui.Select(
            placeholder=placeholder,
            options=choices,
            custom_id=f"tool_sel_{custom_id_suffix}_{stable_hash}"
        )
        
        async def callback(interaction: discord.Interaction):
            selected = select.values[0] if select.values else None
            if not selected:
                return
                
            await interaction.response.send_message(f"Selected: {selected}", ephemeral=True)
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)
            
            if self.callback:
                try:
                    await self.callback(selected, interaction)
                except Exception as e:
                    logger.error(f"Error in interactive select callback: {e}", exc_info=True)
                    
        select.callback = callback
        return select

    def _create_button(self, label: str, custom_id_suffix: str, style: discord.ButtonStyle = discord.ButtonStyle.primary):
        stable_hash = self._get_stable_hash(label)
        button = discord.ui.Button(
            label=label[:80], 
            style=style, 
            custom_id=f"tool_btn_{custom_id_suffix}_{stable_hash}"
        )
        
        async def callback(interaction: discord.Interaction):
            await interaction.response.send_message(f"Selected: {label}", ephemeral=True)
            # Disable buttons after click
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)
            
            if self.callback:
                try:
                    await self.callback(label, interaction)
                except Exception as e:
                    logger.error(f"Error in interactive button callback: {e}", exc_info=True)
                
        button.callback = callback
        return button
