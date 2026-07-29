
with open('/Users/mcdoolz/dev/ganymede/src/ganymede/core/routes/config.py', 'r') as f:
    content = f.read()

target = """async def handle_providers_get(server, request):
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
            
    return web.json_response({"providers": providers})"""

replacement = """async def handle_providers_get(server, request):
    # Dynamically list all providers and their schemas
    import pkgutil
    import importlib
    import os
    import sys
    import ganymede.platforms
    from ganymede.platforms.base import BasePlatformProvider
    
    providers = []
    
    # 1. Load built-in providers
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

    # 2. Load external plugins from ~/.ganymede/plugins
    plugin_dir = os.path.expanduser("~/.ganymede/plugins")
    if os.path.exists(plugin_dir):
        if plugin_dir not in sys.path:
            sys.path.insert(0, plugin_dir)
            
        for name in os.listdir(plugin_dir):
            path = os.path.join(plugin_dir, name)
            if os.path.isdir(path) and not name.startswith('.') and not name.startswith('__'):
                try:
                    module = importlib.import_module(f"{name}.provider")
                    for obj_name in dir(module):
                        obj = getattr(module, obj_name)
                        if isinstance(obj, type) and issubclass(obj, BasePlatformProvider) and obj is not BasePlatformProvider:
                            providers.append({
                                "id": name,
                                "name": name.capitalize() + " (External)",
                                "schema": obj.get_config_schema()
                            })
                            break
                except Exception:
                    pass
                    
    return web.json_response({"providers": providers})"""

if target in content:
    content = content.replace(target, replacement)
    with open('/Users/mcdoolz/dev/ganymede/src/ganymede/core/routes/config.py', 'w') as f:
        f.write(content)
    print("Patched config routes for plugins")
else:
    print("Target not found")
