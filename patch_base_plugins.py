with open('/Users/mcdoolz/dev/ganymede/src/ganymede/platforms/base.py', 'r') as f:
    content = f.read()

target = """def get_platform_provider_class(platform_name: str) -> type[BasePlatformProvider]:
    \"\"\"Dynamically import and retrieve the BasePlatformProvider subclass for a given platform name.\"\"\"
    platform_name = platform_name.lower()
    try:
        module_path = f"ganymede.platforms.{platform_name}.provider"
        module = importlib.import_module(module_path)
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, type) and issubclass(obj, BasePlatformProvider) and obj is not BasePlatformProvider:
                return obj
        raise ValueError(f"No BasePlatformProvider subclass found in {module_path}")
    except ModuleNotFoundError as e:
        raise ValueError(f"Platform provider module for '{platform_name}' not found: {str(e)}")"""

replacement = """def get_platform_provider_class(platform_name: str) -> type[BasePlatformProvider]:
    \"\"\"Dynamically import and retrieve the BasePlatformProvider subclass for a given platform name.\"\"\"
    platform_name = platform_name.lower()
    
    # Allow loading from ~/.ganymede/plugins
    import sys
    import os
    plugin_dir = os.path.expanduser("~/.ganymede/plugins")
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)
        
    modules_to_try = [
        f"ganymede.platforms.{platform_name}.provider",
        f"{platform_name}.provider",  # For external plugins in ~/.ganymede/plugins/{platform_name}/provider.py
        platform_name  # If the plugin is just a single file ~/.ganymede/plugins/{platform_name}.py
    ]
    
    for module_path in modules_to_try:
        try:
            module = importlib.import_module(module_path)
            for name in dir(module):
                obj = getattr(module, name)
                if isinstance(obj, type) and issubclass(obj, BasePlatformProvider) and obj is not BasePlatformProvider:
                    return obj
        except ModuleNotFoundError:
            continue
            
    raise ValueError(f"Platform provider module for '{platform_name}' not found in any standard or plugin paths.")"""

if target in content:
    content = content.replace(target, replacement)
    with open('/Users/mcdoolz/dev/ganymede/src/ganymede/platforms/base.py', 'w') as f:
        f.write(content)
    print("Patched base.py for plugins")
else:
    print("Target not found")
