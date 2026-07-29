with open('/Users/mcdoolz/dev/ganymede/src/ganymede/core/routes/config.py', 'r') as f:
    content = f.read()

t = '    if "platform" in data:\n        server.config.platform = data["platform"]'
r = '    if "platform" in data:\n        server.config.platform = data["platform"]\n    if "theme" in data:\n        server.config.theme = data["theme"]'

if t in content:
    content = content.replace(t, r)
    with open('/Users/mcdoolz/dev/ganymede/src/ganymede/core/routes/config.py', 'w') as f:
        f.write(content)
    print("Routes config patched")
else:
    print("Not found")
