import discord
from typing import Callable, Awaitable

class InteractiveToolView(discord.ui.View):
    def __init__(self, interactive_tools: list, callback: Callable[[str, discord.Interaction], Awaitable[None]]):
        super().__init__(timeout=None)
        self.callback = callback
        
        for tool in interactive_tools:
            name = tool.get("name", "")
            args = tool.get("args", {})
            
            if "ask_question" in name:
                questions = args.get("questions", [])
                for q in questions:
                    options = q.get("options", [])
                    for i, opt in enumerate(options):
                        # Use a closure to capture 'opt' properly
                        self.add_item(self._create_button(opt, str(i)))
                        
            elif "ask_permission" in name:
                self.add_item(self._create_button("Yes", "approve", discord.ButtonStyle.green))
                self.add_item(self._create_button("No", "deny", discord.ButtonStyle.red))

    def _create_button(self, label: str, custom_id_suffix: str, style: discord.ButtonStyle = discord.ButtonStyle.primary):
        button = discord.ui.Button(label=label[:80], style=style, custom_id=f"tool_btn_{custom_id_suffix}_{hash(label)}")
        
        async def callback(interaction: discord.Interaction):
            await interaction.response.send_message(f"Selected: {label}", ephemeral=True)
            # Disable buttons after click
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)
            
            if self.callback:
                await self.callback(label, interaction)
                
        button.callback = callback
        return button
