import os
import structlog
import yaml
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = structlog.get_logger()

router = APIRouter()

@router.get('/api/config')
async def handle_config_get(request: Request):
    server = request.app.state.server
    config_path = os.path.expanduser("~/.ganymede/config.yaml")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            data = yaml.safe_load(f) or {}
            return data
    return {}

_cached_models = None

@router.get('/api/models')
async def handle_models_get(request: Request):
    from ganymede.core.model_registry import ModelRegistry
    try:
        available = ModelRegistry.get_available_models()
        models = [disp for slug, disp in available]
        return {"models": models}
    except Exception as e:
        logger.error("Failed to list models", error=str(e))
        return {"models": ["Gemini 3.7 Flash (High)", "Gemini 3.1 Pro (High)"]}
    

@router.post('/api/config')
async def handle_config_post(request: Request):
    server = request.app.state.server
    data = await request.json()
        
    # Clean up empty strings sent by UI to prevent overriding defaults with blanks
    if "bot" in data and isinstance(data["bot"], dict):
        if "identity" in data["bot"] and data["bot"]["identity"] == "":
            del data["bot"]["identity"]
            server.config.bot.identity = type(server.config.bot).identity
        elif "identity" in data["bot"]:
            server.config.bot.identity = data["bot"]["identity"]
            
    if "agent" in data and isinstance(data["agent"], dict):
        if not hasattr(server.config, "agent"):
            class AgentConfig:
                pass
            server.config.agent = AgentConfig()
            
        for key in ["model", "name", "mission_statement"]:
            if key in data["agent"]:
                if data["agent"][key] == "":
                    del data["agent"][key]
                    setattr(server.config.agent, key, getattr(type(server.config.agent), key, ""))
                else:
                    setattr(server.config.agent, key, data["agent"][key])
                    
    # Clean up empty parent dicts if they are now empty
    if "bot" in data and not data["bot"]:
        del data["bot"]
    if "agent" in data and not data["agent"]:
        del data["agent"]
        
    # Update other in-memory config
    if "log_level" in data:
        server.config.log_level = data["log_level"]
    if "platform" in data:
        server.config.platform = data["platform"]
    if "theme" in data:
        server.config.theme = data["theme"]
            
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
        
    filename = request.query_params.get("filename")
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



@router.get('/api/agents')
async def handle_agents_get(request: Request):
    server = request.app.state.server
    return {
        "agents": getattr(server.config, "agents", {}),
        "channel_mappings": getattr(server.config, "channel_mappings", {})
    }

@router.post('/api/agents/{agent_id}')
async def handle_agent_post(request: Request):
    server = request.app.state.server
    agent_id = request.path_params.get('agent_id', 'default').strip()
    agent_data = await request.json()
    
    config_path = os.path.expanduser("~/.ganymede/config.yaml")
    data = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            data = yaml.safe_load(f) or {}
            
    if "agents" not in data:
        data["agents"] = {}
        
    data["agents"][agent_id] = agent_data
    server.config.agents[agent_id] = agent_data
    
    # If this is the default agent, also update top-level agent/bot defaults
    if agent_id == "default":
        if "name" in agent_data:
            server.config.agent.name = agent_data["name"]
        if "model" in agent_data:
            server.config.agent.model = agent_data["model"]
        if "workspace" in agent_data:
            server.config.agent.workspace = agent_data["workspace"]
        if "identity" in agent_data:
            server.config.bot.identity = agent_data["identity"]
        if "mission_statement" in agent_data:
            server.config.agent.mission_statement = agent_data["mission_statement"]
        if "mode" in agent_data:
            server.config.agent.mode = agent_data["mode"]
            
    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
        
    return {"status": "saved", "agent_id": agent_id}

@router.delete('/api/agents/{agent_id}')
async def handle_agent_delete(request: Request):
    server = request.app.state.server
    agent_id = request.path_params.get('agent_id')
    if agent_id == "default":
        return JSONResponse({"error": "Cannot delete the default agent"}, status_code=400)
        
    config_path = os.path.expanduser("~/.ganymede/config.yaml")
    data = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            data = yaml.safe_load(f) or {}
            
    if "agents" in data and agent_id in data["agents"]:
        del data["agents"][agent_id]
        if agent_id in server.config.agents:
            del server.config.agents[agent_id]
            
        # Clean up any channel mappings referencing this agent
        if "channel_mappings" in data:
            data["channel_mappings"] = {k: v for k, v in data["channel_mappings"].items() if v != agent_id}
            server.config.channel_mappings = data["channel_mappings"]
            
        with open(config_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)
            
        return {"status": "deleted", "agent_id": agent_id}
    return JSONResponse({"error": "Agent not found"}, status_code=404)

@router.get('/api/channels')
async def handle_channels_get(request: Request):
    server = request.app.state.server
    channels = []
    
    # Query all active platform providers
    if getattr(server, "providers", None):
        for p in server.providers:
            if hasattr(p, "get_channels"):
                try:
                    p_channels = p.get_channels()
                    for ch in p_channels:
                        platform = ch.get("platform", "discord")
                        ch_id = ch.get("id")
                        
                        from ganymede.core import ContextKey
                        ctx = ContextKey(platform, ch_id, None)
                        assigned_agent = server.config.get_agent_for_context(ctx)
                        
                        channels.append({
                            **ch,
                            "assigned_agent_id": assigned_agent.get("id", "default"),
                            "assigned_agent_name": assigned_agent.get("name", "Icarus"),
                            "assigned_agent_model": assigned_agent.get("model", "Default")
                        })
                except Exception as e:
                    logger.warning("Error fetching channels from provider", provider=getattr(p, "bot_id", "unknown"), error=str(e))

    # Also list any historical channels from conversation database if not already discovered
    if server.db:
        try:
            async with server.db._conn.execute(
                """
                SELECT DISTINCT context_platform, context_channel, MAX(created_at) as last_active
                FROM conversations
                GROUP BY context_platform, context_channel
                ORDER BY last_active DESC
                """
            ) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    p_form = row["context_platform"]
                    c_id = row["context_channel"]
                    if not any(c.get("id") == c_id and c.get("platform") == p_form for c in channels):
                        from ganymede.core import ContextKey
                        ctx = ContextKey(p_form, c_id, None)
                        assigned_agent = server.config.get_agent_for_context(ctx)
                        channels.append({
                            "platform": p_form,
                            "id": c_id,
                            "name": f"Channel {c_id}",
                            "guild_id": "",
                            "guild_name": p_form.capitalize(),
                            "topic": "",
                            "type": "text",
                            "assigned_agent_id": assigned_agent.get("id", "default"),
                            "assigned_agent_name": assigned_agent.get("name", "Icarus"),
                            "assigned_agent_model": assigned_agent.get("model", "Default")
                        })
        except Exception as e:
            logger.warning("Error querying conversation channels", error=str(e))
            
    return {"channels": channels}

@router.post('/api/channels/assign')
async def handle_channel_assign_post(request: Request):
    server = request.app.state.server
    payload = await request.json()
    platform = payload.get("platform", "discord").lower()
    channel_id = str(payload.get("channel_id", "")).strip()
    agent_id = payload.get("agent_id", "default").strip()
    
    if not channel_id:
        return JSONResponse({"error": "channel_id is required"}, status_code=400)
        
    config_path = os.path.expanduser("~/.ganymede/config.yaml")
    data = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            data = yaml.safe_load(f) or {}
            
    if "channel_mappings" not in data:
        data["channel_mappings"] = {}
        
    key = f"{platform}:{channel_id}"
    data["channel_mappings"][key] = agent_id
    server.config.channel_mappings[key] = agent_id
    
    # Keep agent bindings in sync
    if "agents" not in data:
        data["agents"] = server.config.agents
    if agent_id in data["agents"]:
        agent = data["agents"][agent_id]
        bindings = agent.get("bindings", [])
        # Add channel to this agent's bindings if not already present
        found = False
        for b in bindings:
            if b.get("provider") == platform:
                if channel_id not in b.get("channels", []):
                    b.setdefault("channels", []).append(channel_id)
                found = True
                break
        if not found:
            bindings.append({"provider": platform, "channels": [channel_id]})
        agent["bindings"] = bindings
        server.config.agents[agent_id] = agent

    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
        
    return {"status": "assigned", "key": key, "agent_id": agent_id}

@router.get('/api/providers')
async def handle_providers_get(request: Request):
    server = request.app.state.server
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
                    is_connected = server.platform_states.get(name, False)
                    providers.append({
                        "id": name,
                        "name": name.capitalize(),
                        "schema": obj.get_config_schema(),
                        "connected": is_connected
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
                            is_connected = server.platform_states.get(name, False)
                            providers.append({
                                "id": name,
                                "name": name.capitalize() + " (External)",
                                "schema": obj.get_config_schema(),
                                "connected": is_connected
                            })
                            break
                except Exception:
                    pass
                    
    return {"providers": providers}

@router.get('/api/bots')
async def handle_bots_get(request: Request):
    server = request.app.state.server
    return await handle_agents_get(request)

@router.post('/api/bots/{bot_id}')
async def handle_bot_post(request: Request):
    return await handle_agent_post(request)

@router.delete('/api/bots/{bot_id}')
async def handle_bot_delete(request: Request):
    return await handle_agent_delete(request)
