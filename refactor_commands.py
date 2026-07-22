import re

with open("/Users/mcdoolz/dev/ganymede/src/ganymede/platforms/discord/commands.py", "r") as f:
    content = f.read()

# Add the helper function right after setup_commands signature
helper = """def setup_commands(adapter: discord.Client):
    tree = adapter.tree

    def _get_context(interaction: discord.Interaction) -> ContextKey:
        thread_id = str(interaction.channel.id) if isinstance(interaction.channel, discord.Thread) else None
        channel_id = str(interaction.channel.parent_id) if thread_id else str(interaction.channel.id)
        return ContextKey(platform="discord", channel_id=channel_id, thread_id=thread_id)
"""

content = content.replace("def setup_commands(adapter: discord.Client):\n    tree = adapter.tree", helper, 1)

# Now find all instances of the boilerplate and replace it
boilerplate = r"""        thread_id = str\(interaction.channel.id\) if isinstance\(interaction.channel, discord.Thread\) else None
        channel_id = str\(interaction.channel.parent_id\) if thread_id else str\(interaction.channel.id\)
        
        context = ContextKey\(
            platform="discord",
            channel_id=channel_id,
            thread_id=thread_id
        \)"""

content = re.sub(boilerplate, "        context = _get_context(interaction)", content)

with open("/Users/mcdoolz/dev/ganymede/src/ganymede/platforms/discord/commands.py", "w") as f:
    f.write(content)

print("Done")
