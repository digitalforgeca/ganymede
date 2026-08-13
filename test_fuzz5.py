from ganymede.platforms.discord.formatter import DiscordFormatter

with open("fail_content.txt", "r") as f:
    content = f.read()

f = DiscordFormatter()
chunks = f.split_message(content)
for i, c in enumerate(chunks):
    if len(c) > 2000:
        print(f"Chunk {i} is {len(c)}")
        print("Starts with:", repr(c[:50]))
        print("Ends with:", repr(c[-50:]))
