from ganymede.platforms.base import PlatformAdapter

# Just check if we can add it to discord adapter
with open('/Users/mcdoolz/dev/ganymede/src/ganymede/platforms/discord/adapter.py', 'r') as f:
    print(f"Lines in discord adapter: {len(f.readlines())}")
