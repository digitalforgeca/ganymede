import os
import asyncio
import structlog
import json
import yaml
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from ganymede.config import AppConfig
from ganymede.core import ContextKey

logger = structlog.get_logger()

router = APIRouter()

@router.get('/api/config')
async def handle_config_get(request: Request):
    server = request.app.state.server
    import yaml
    config_path = os.path.expanduser("~/.ganymede/config.yaml")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            data = yaml.safe_load(f) or {}
            return data
    return {}

_cached_models = None

@router.get('/api/models')
async def handle_models_get(request: Request):
    global _cached_models
    if _cached_models is not None:
        return _cached_models
        
    try:
        import subprocess
        out = subprocess.check_output(["agy", "models"], text=True, timeout=15)
        
        # Map raw slugs to pretty formatted strings
        format_map = {
            "gemini-3.1-pro-high": "Gemini 3.1 Pro (High)",
            "gemini-3.1-pro-low": "Gemini 3.1 Pro (Low)",
            "gemini-3.5-flash-high": "Gemini 3.5 Flash (High)",
            "gemini-3.5-flash-medium": "Gemini 3.5 Flash (Medium)",
            "gemini-3.5-flash-low": "Gemini 3.5 Flash (Low)",
            "gemini-3.6-flash-high": "Gemini 3.6 Flash (High)",
            "gemini-3.6-flash-medium": "Gemini 3.6 Flash (Medium)",
            "gemini-3.6-flash-low": "Gemini 3.6 Flash (Low)",
            "claude-sonnet-4-6": "Claude 3.5 Sonnet (4-6)",
            "claude-opus-4-6-thinking": "Claude Opus (Thinking)",
        }
        
        models = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("-"):
                line = line[1:].strip()
            if line and not line.startswith("Available") and not line.startswith("=="):
                # Use mapped name if available, otherwise raw slug
                models.append(format_map.get(line, line))
                
        if not models:
            models = ["Gemini 3.1 Pro (High)", "Gemini Flash", "gemini-1.5-pro-002", "gemini-1.5-flash-002"]
            
        _cached_models = {"models": models}
        return _cached_models
    except Exception as e:
        logger.error("Failed to list models", error=str(e))
        return {"models": ["Gemini 3.1 Pro (High)", "Gemini Flash", "gemini-1.5-pro-002", "gemini-1.5-flash-002"]}
    

@router.post('/api/config')
async def handle_config_post(request: Request):
    server = request.app.state.server
    import yaml
    data = await request.json()
        
    # Update in-memory config for immediate application
    if "log_level" in data:
        server.config.log_level = data["log_level"]
    if "platform" in data:
        server.config.platform = data["platform"]
    if "theme" in data:
        server.config.theme = data["theme"]
    if "agent" in data:
        if not hasattr(server.config, "agent"):
            class AgentConfig:
                pass
            server.config.agent = AgentConfig()
        if "model" in data["agent"]:
            server.config.agent.model = data["agent"]["model"]
        if "name" in data["agent"]:
            server.config.agent.name = data["agent"]["name"]
        if "mission_statement" in data["agent"]:
            server.config.agent.mission_statement = data["agent"]["mission_statement"]
    if "bot" in data:
        if "identity" in data["bot"]:
            server.config.bot.identity = data["bot"]["identity"]
            
    config_path = os.path.expanduser("~/.ganymede/config.yaml")
    try:
        with open(config_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)
        return {"status": "saved"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get('/api/rules')
async def handle_rules_get(request: Request):
    server = request.app.state.server
    rules_dir = os.path.expanduser("~/.gemini/rules")
    if not os.path.exists(rules_dir):
        os.makedirs(rules_dir, exist_ok=True)
        
    filename = request.query.get("filename")
    if filename:
        file_path = os.path.join(rules_dir, filename)
        if not os.path.exists(file_path):
            return JSONResponse({"error": "Rule not found"}, status_code=404)
        with open(file_path, "r") as f:
            return {"content": f.read()}
            
    files = []
    for f in os.listdir(rules_dir):
        if f.endswith(".md"):
            files.append(f)
    return {"rules": sorted(files)}


@router.post('/api/rules')
async def handle_rules_post(request: Request):
    server = request.app.state.server
    rules_dir = os.path.expanduser("~/.gemini/rules")
    if not os.path.exists(rules_dir):
        os.makedirs(rules_dir, exist_ok=True)
        
    data = await request.json()
    filename = data.get("filename")
    content = data.get("content", "")
    
    if not filename or not filename.endswith(".md"):
        return JSONResponse({"error": "Invalid filename. Must end with .md"}, status_code=400)
        
    file_path = os.path.join(rules_dir, filename)
    with open(file_path, "w") as f:
        f.write(content)
        
    return {"status": "saved", "filename": filename}
    

@router.delete('/api/rules/{filename}')
async def handle_rule_delete(request: Request):
    server = request.app.state.server
    filename = request.path_params.get('filename')
    if not filename or not filename.endswith(".md"):
        return JSONResponse({"error": "Invalid filename"}, status_code=400)
        
    file_path = os.path.join(os.path.expanduser("~/.gemini/rules"), filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        return {"status": "deleted"}
    return JSONResponse({"error": "Rule not found"}, status_code=404)


@router.get('/api/bots/detail/conversations')
async def handle_bot_conversations(request: Request):
    server = request.app.state.server
    if not server.db:
        return JSONResponse({"error": "Database not available"}, status_code=500)
        
    async with server.db._conn.execute(
        """
        SELECT context_platform, context_channel, context_thread, MAX(created_at) as last_active, COUNT(id) as message_count
        FROM conversations
        GROUP BY context_platform, context_channel, context_thread
        ORDER BY last_active DESC
        """
    ) as cursor:
        rows = await cursor.fetchall()
        return {"conversations": [dict(row) for row in rows]}



@router.get('/api/providers')
async def handle_providers_get(request: Request):
    server = request.app.state.server
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
                    
    return {"providers": providers}

@router.get('/api/bots')
async def handle_bots_get(request: Request):
    server = request.app.state.server
    import yaml
    config_path = os.path.expanduser("~/.ganymede/config.yaml")
    bots = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            data = yaml.safe_load(f) or {}
            bots = data.get("bots", {})
            if not bots and "bot" in data:
                # Fallback mapping for single bot gateway configurations
                bots = {"primary": data["bot"]}
    return {"bots": bots}

@router.post('/api/bots/{bot_id}')
async def handle_bot_post(request: Request):
    server = request.app.state.server
    import yaml
    bot_id = request.path_params.get('bot_id')
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
        
    return {"status": "saved", "bot_id": bot_id}

@router.delete('/api/bots/{bot_id}')
async def handle_bot_delete(request: Request):
    server = request.app.state.server
    import yaml
    bot_id = request.path_params.get('bot_id')
    
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
            
        return {"status": "deleted", "bot_id": bot_id}
    return JSONResponse({"error": "Bot not found"}, status_code=404)
