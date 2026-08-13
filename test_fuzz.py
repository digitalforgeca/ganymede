from ganymede.platforms.discord.formatter import DiscordFormatter
import random

def test():
    f = DiscordFormatter()
    for _ in range(100):
        # Generate random length string with newlines and code fences
        content = ""
        for _ in range(100):
            content += "a" * random.randint(1, 100)
            if random.random() < 0.1:
                content += "\n```json\n"
            elif random.random() < 0.1:
                content += "\n```\n"
            else:
                content += "\n"
        chunks = f.split_message(content)
        for c in chunks:
            if len(c) > 2000:
                print("FAIL!", len(c))
                return
    print("SUCCESS")
test()
