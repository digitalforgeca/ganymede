with open('/Users/mcdoolz/dev/ganymede/src/ganymede/core/routes/config.py', 'r') as f:
    content = f.read()

new_routes = """
async def handle_providers_get(server, request):
    # Dynamically list all providers and their schemas
    import pkgutil
    import importlib
    import ganymede.platforms
    from ganymede.platforms.base import BasePlatformProvider
    
    providers = []
    
    for _, name, _ in pkgutil.iter_modules(ganymede.platforms.__path__):
        if name == "base":
            continue
        try:
            module = importlib.import_module(f"ganymede.platforms.{name}.provider")
            for obj_name in dir(module):
                obj = getattr(module, obj_name)
                if isinstance(obj, type) and issubclass(obj, BasePlatformProvider) and obj is not BasePlatformProvider:
                    providers.append({
                        "id": name,
                        "name": name.capitalize(),
                        "schema": obj.get_config_schema()
                    })
                    break
        except Exception:
            pass
            
    return web.json_response({"providers": providers})

async def handle_bots_get(server, request):
    import yaml
    config_path = os.path.expanduser("~/.ganymede/config.yaml")
    bots = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            data = yaml.safe_load(f) or {}
            bots = data.get("bots", {})
    return web.json_response({"bots": bots})

async def handle_bot_post(server, request):
    import yaml
    bot_id = request.match_info['bot_id']
    bot_data = await request.json()
    
    config_path = os.path.expanduser("~/.ganymede/config.yaml")
    data = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            data = yaml.safe_load(f) or {}
            
    if "bots" not in data:
        data["bots"] = {}
        
    data["bots"][bot_id] = bot_data
    
    # Also update in-memory config
    server.config.bots[bot_id] = bot_data
    
    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
        
    return web.json_response({"status": "saved", "bot_id": bot_id})

async def handle_bot_delete(server, request):
    import yaml
    bot_id = request.match_info['bot_id']
    
    config_path = os.path.expanduser("~/.ganymede/config.yaml")
    data = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            data = yaml.safe_load(f) or {}
            
    if "bots" in data and bot_id in data["bots"]:
        del data["bots"][bot_id]
        
        # Also update in-memory config
        if bot_id in server.config.bots:
            del server.config.bots[bot_id]
            
        with open(config_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)
            
        return web.json_response({"status": "deleted", "bot_id": bot_id})
    return web.json_response({"error": "Bot not found"}, status=404)
"""

if "handle_providers_get" not in content:
    content += new_routes
    with open('/Users/mcdoolz/dev/ganymede/src/ganymede/core/routes/config.py', 'w') as f:
        f.write(content)
    print("Added new routes")
else:
    print("Routes already exist")
