with open('/Users/mcdoolz/dev/ganymede/src/ganymede/config.py', 'r') as f:
    content = f.read()

# Add theme property to AppConfig
t = "    bots: dict[str, Any] = field(default_factory=dict)"
r = "    bots: dict[str, Any] = field(default_factory=dict)\n    theme: str = \"default\""

if t in content:
    content = content.replace(t, r)
    
# Update handle_config_post ? 
# We don't really need to unless they update it from UI, but let's just make it possible to load from yaml
t2 = "    if \"platform\" in data:\n        config.platform = data[\"platform\"]"
r2 = "    if \"platform\" in data:\n        config.platform = data[\"platform\"]\n\n    if \"theme\" in data:\n        config.theme = data[\"theme\"]"
if t2 in content:
    content = content.replace(t2, r2)
    
with open('/Users/mcdoolz/dev/ganymede/src/ganymede/config.py', 'w') as f:
    f.write(content)
print("config patched")
