from ganymede.platforms.discord.formatter import DiscordFormatter

with open("fail_content.txt", "r") as f:
    content = f.read()

f = DiscordFormatter()
chunks = f.split_message(content)

for c in chunks:
    if len(c) > 2000:
        # print length of each element in current_chunk when it failed!
        pass
        
print("Let's copy the code of split_message and inject debug prints")
