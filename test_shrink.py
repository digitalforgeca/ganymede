from ganymede.platforms.discord.formatter import DiscordFormatter
f = DiscordFormatter()

# We want to find a string S and a string A such that len(split(S + A)) < len(split(S))
# Is this possible?
# Let's think:
# limit = 2000.
# If S has length 1999. It's 1 chunk.
# S + A has length 2005. It's 2 chunks.
