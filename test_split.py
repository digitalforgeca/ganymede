from ganymede.platforms.discord.formatter import DiscordFormatter

fmt = DiscordFormatter()

massive_code = "```python\n" + ("x = '" + "A"*4000 + "'") + "\n```"
chunks = fmt.split_message(massive_code)
print("Test 2 chunks:", len(chunks))
for i, c in enumerate(chunks):
    print(f"CHUNK {i} LENGTH: {len(c)}")
    print(repr(c[-10:]))
