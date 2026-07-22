import re

with open("/Users/mcdoolz/dev/ganymede/src/ganymede/core/web.py", "r") as f:
    content = f.read()

# Let's count how many handler methods there are
methods = re.findall(r'async def handle_[a-z_]+\(self, request\):', content)
print(f"Found {len(methods)} handler methods in web.py")
