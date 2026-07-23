import os
import asyncio
import structlog
import json
import yaml
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse
from ganymede.config import AppConfig
from ganymede.core import ContextKey

logger = structlog.get_logger()
router = APIRouter()


@router.get('/api/status')
async def handle_status(request: Request):
    server = request.app.state.server
    status_str = "online" if any(server.platform_states.values()) else "offline"
    
    active_instances = 0
    tokens_hour = 0
    quota_used = 0
    quota_limit = getattr(server.config.quota, "max_requests_per_day", 18)
    token_limit = getattr(server.config.quota, "max_tokens_global_per_hour", 200000)
    bot_info = None
    
    try:
        import subprocess
        out = subprocess.check_output(["ps", "-A", "-o", "command"], text=True)
        active_instances = sum(1 for line in out.splitlines() if line.startswith("agy ") or line.endswith("/agy") or "/agy " in line)
    except Exception:
        pass

    if getattr(server, "providers", None):
        for p in server.providers:
            if hasattr(p, "router") and p.router and p.router.agent_manager:
                import sqlite3
                db_path = os.path.expanduser("~/.ganymede/data/ganymede.db")
                if os.path.exists(db_path):
                    try:
                        with sqlite3.connect(db_path) as conn:
                            c = conn.cursor()
                            c.execute("SELECT sum(tokens_total) FROM telemetry WHERE created_at >= datetime('now', '-1 hour')")
                            row = c.fetchone()
                            if row and row[0]:
                                tokens_hour += int(row[0])
                            c.execute("SELECT count(*) FROM conversations WHERE role = 'assistant' AND created_at >= datetime('now', 'start of day')")
                            row = c.fetchone()
                            if row and row[0]:
                                quota_used += int(row[0])
                    except Exception as e:
                        print(f"Error querying DB for metrics: {e}")
            adapter = getattr(p, "adapter", None)
            if adapter and hasattr(adapter, "user") and adapter.user:
                try:
                    bot_info = {
                        "name": adapter.user.name,
                        "discriminator": getattr(adapter.user, "discriminator", ""),
                        "id": str(adapter.user.id),
                        "avatar_url": adapter.user.display_avatar.url if getattr(adapter.user, "display_avatar", None) else None
                    }
                except Exception:
                    pass
                    
    if not bot_info:
        bot_info = {
            "name": getattr(server.config.agent, "name", "Agent"),
            "discriminator": "",
            "id": "web-console",
            "avatar_url": None
        }
                
    return {
        "status": status_str,
        "platform": server.config.platform,
        "log_level": server.config.log_level,
        "data_dir": os.path.expanduser("~/.ganymede/data"),
        "model": getattr(server.config.agent, "model", "default"),
        "metrics": {
            "active_instances": active_instances,
            "tokens_hour": tokens_hour,
            "token_limit": token_limit,
            "quota_used": quota_used,
            "quota_limit": quota_limit
        },
        "bot_info": bot_info
    }


@router.get('/api/user')
async def handle_user_info(request: Request):
    import base64
    import json
    creds_path = os.path.expanduser("~/.gemini/oauth_creds.json")
    user_info = {"name": "Operator", "avatar_url": None}
    if os.path.exists(creds_path):
        try:
            with open(creds_path, "r") as f:
                creds = json.load(f)
            if "id_token" in creds:
                token = creds["id_token"]
                payload_b64 = token.split(".")[1]
                payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
                payload = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
                if "name" in payload:
                    user_info["name"] = payload["name"]
                if "picture" in payload:
                    user_info["avatar_url"] = payload["picture"]
        except Exception as e:
            logger.error("Failed to parse oauth_creds.json", error=str(e))
    return user_info


@router.websocket('/ws/dashboard')
async def handle_dashboard_ws(websocket: WebSocket):
    server = websocket.app.state.server
    await websocket.accept()
    server.dashboard_clients.add(websocket)
    
    try:
        while True:
            await websocket.receive_text() # Dashboard only listens
    except WebSocketDisconnect:
        pass
    finally:
        server.dashboard_clients.remove(websocket)


@router.get('/api/files')
async def handle_files(request: Request):
    server = request.app.state.server
    workspace = server.config.workspace if hasattr(server.config, 'workspace') else os.path.expanduser("~/.ganymede/workspace")
    files_data = []
    
    if os.path.exists(workspace):
        for root, dirs, files in os.walk(workspace):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, workspace)
                size = os.path.getsize(full_path)
                files_data.append({"name": file, "path": rel_path, "size": size})
                
    return {"files": files_data, "workspace": workspace}
