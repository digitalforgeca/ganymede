from ganymede.platforms.discord.formatter import DiscordFormatter
f = DiscordFormatter()

# We need a chunk that is 1998 characters long.
content = "a" * 1998 + "\n```json\n" + "b" * 10 + "\n```\n"

chunks = f.split_message(content)
for i, c in enumerate(chunks):
    print(f"Chunk {i+1} len:", len(c))
