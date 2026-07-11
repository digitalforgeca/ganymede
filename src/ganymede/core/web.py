import os
import structlog
import json
from aiohttp import web
from ganymede.config import AppConfig

logger = structlog.get_logger()

dashboard_instance = None

class DashboardServer:
    def __init__(self, config: AppConfig):
        global dashboard_instance
        dashboard_instance = self
        self.config = config
        self.app = web.Application()
        
        # API Routes
        self.app.router.add_get('/api/status', self.handle_status)
        self.app.router.add_get('/api/files', self.handle_files)
        self.app.router.add_get('/api/chats', self.handle_chats)
        self.app.router.add_get('/api/chats/{id}/history', self.handle_chat_history)
        self.app.router.add_get('/api/chats/{id}/files', self.handle_chat_files)
        self.app.router.add_get('/api/chats/{id}/settings', self.handle_chat_settings_get)
        self.app.router.add_post('/api/chats/{id}/settings', self.handle_chat_settings_post)
        self.app.router.add_post('/api/chats/{id}/merge', self.handle_chat_merge)
        self.app.router.add_post('/api/chats/{id}/fork', self.handle_chat_fork)
        self.app.router.add_post('/api/telemetry', self.handle_telemetry_post)
        self.app.router.add_post('/api/chat/invoke', self.handle_chat_invoke)
        self.app.router.add_get('/api/config', self.handle_config_get)
        self.app.router.add_post('/api/config', self.handle_config_post)
        self.app.router.add_get('/api/rules', self.handle_rules_get)
        self.app.router.add_post('/api/rules', self.handle_rules_post)
        self.app.router.add_delete('/api/rules/{filename}', self.handle_rule_delete)
        self.app.router.add_get('/api/user', self.handle_user_info)
        self.app.router.add_get('/ws/telemetry', self.handle_telemetry_ws)
        self.app.router.add_get('/ws/dashboard', self.handle_dashboard_ws)
        
        # Track connected frontend clients
        self.dashboard_clients = set()
        
        # Static Dashboard Routes
        self.web_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'web')
        if not os.path.exists(self.web_dir):
            os.makedirs(self.web_dir, exist_ok=True)
            
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_static('/', self.web_dir, name='static')
            
        self.runner = None
        self.site = None
        self.web_invoke_callback = None
        self.platform_states = {}

    def set_platform_status(self, platform: str, is_connected: bool) -> None:
        self.platform_states[platform] = is_connected

    async def handle_index(self, request):
        index_path = os.path.join(self.web_dir, 'index.html')
        if os.path.exists(index_path):
            return web.FileResponse(index_path)
        return web.Response(text="Dashboard initializing...", status=404)

    async def handle_chat_invoke(self, request):
        if self.web_invoke_callback:
            return await self.web_invoke_callback(request)
        return web.json_response({"error": "WebProvider not initialized"}, status=503)

    async def handle_status(self, request):
        status_str = "online" if any(self.platform_states.values()) else "offline"
        
        active_instances = 0
        tokens_hour = 0
        quota_used = 0
        quota_limit = getattr(self.config.quota, "max_requests_per_day", 18)
        token_limit = getattr(self.config.quota, "max_tokens_global_per_hour", 200000)
        bot_info = None
        
        try:
            import subprocess
            out = subprocess.check_output(["ps", "-A", "-o", "command"], text=True)
            active_instances = sum(1 for line in out.splitlines() if line.startswith("agy ") or line.endswith("/agy") or "/agy " in line)
        except Exception:
            pass

        if getattr(self, "providers", None):
            for p in self.providers:
                if hasattr(p, "router") and p.router and p.router.agent_manager:
                    # Query ganymede.db for persistent tokens and requests
                    import sqlite3
                    import os
                    db_path = os.path.expanduser("~/.ganymede/data/ganymede.db")
                    if os.path.exists(db_path):
                        try:
                            with sqlite3.connect(db_path) as conn:
                                c = conn.cursor()
                                c.execute("SELECT sum(tokens) FROM conversations WHERE created_at >= datetime('now', '-1 hour')")
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
                "name": getattr(self.config.agent, "name", "Agent"),
                "discriminator": "",
                "id": "web-console",
                "avatar_url": None
            }
                    
        return web.json_response({
            "status": status_str,
            "platform": self.config.platform,
            "log_level": self.config.log_level,
            "data_dir": os.path.expanduser("~/.ganymede/data"),
            "model": getattr(self.config.agent, "model", "default"),
            "metrics": {
                "active_instances": active_instances,
                "tokens_hour": tokens_hour,
                "token_limit": token_limit,
                "quota_used": quota_used,
                "quota_limit": quota_limit
            },
            "bot_info": bot_info
        })

    async def handle_config_get(self, request):
        import yaml
        config_path = os.path.expanduser("~/.ganymede/config.yaml")
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                data = yaml.safe_load(f) or {}
                return web.json_response(data)
        return web.json_response({})
        
    async def handle_config_post(self, request):
        import yaml
        data = await request.json()
            
        # Update in-memory config for immediate application
        if "log_level" in data:
            self.config.log_level = data["log_level"]
        if "platform" in data:
            self.config.platform = data["platform"]
        if "agent" in data:
            if not hasattr(self.config, "agent"):
                class AgentConfig: pass
                self.config.agent = AgentConfig()
            if "model" in data["agent"]:
                self.config.agent.model = data["agent"]["model"]
            if "name" in data["agent"]:
                self.config.agent.name = data["agent"]["name"]
            if "system_instructions" in data["agent"]:
                self.config.agent.system_instructions = data["agent"]["system_instructions"]
            if "mission_statement" in data["agent"]:
                self.config.agent.mission_statement = data["agent"]["mission_statement"]
                
        config_path = os.path.expanduser("~/.ganymede/config.yaml")
        try:
            with open(config_path, "w") as f:
                yaml.dump(data, f, default_flow_style=False)
            return web.json_response({"status": "saved"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
    async def handle_rules_get(self, request):
        rules_dir = os.path.expanduser("~/.gemini/rules")
        if not os.path.exists(rules_dir):
            os.makedirs(rules_dir, exist_ok=True)
            
        filename = request.query.get("filename")
        if filename:
            file_path = os.path.join(rules_dir, filename)
            if not os.path.exists(file_path):
                return web.json_response({"error": "Rule not found"}, status=404)
            with open(file_path, "r") as f:
                return web.json_response({"content": f.read()})
                
        files = []
        for f in os.listdir(rules_dir):
            if f.endswith(".md"):
                files.append(f)
        return web.json_response({"rules": sorted(files)})
        
    async def handle_rules_post(self, request):
        rules_dir = os.path.expanduser("~/.gemini/rules")
        if not os.path.exists(rules_dir):
            os.makedirs(rules_dir, exist_ok=True)
            
        data = await request.json()
        filename = data.get("filename")
        content = data.get("content", "")
        
        if not filename or not filename.endswith(".md"):
            return web.json_response({"error": "Invalid filename. Must end with .md"}, status=400)
            
        file_path = os.path.join(rules_dir, filename)
        with open(file_path, "w") as f:
            f.write(content)
            
        return web.json_response({"status": "saved", "filename": filename})
        
    async def handle_rule_delete(self, request):
        filename = request.match_info['filename']
        if not filename or not filename.endswith(".md"):
            return web.json_response({"error": "Invalid filename"}, status=400)
            
        file_path = os.path.join(os.path.expanduser("~/.gemini/rules"), filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            return web.json_response({"status": "deleted"})
        return web.json_response({"error": "Rule not found"}, status=404)

    async def handle_user_info(self, request):
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
        return web.json_response(user_info)

    async def handle_telemetry_ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        logger.info("Chalice plugin connected via WebSocket")
        
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        logger.debug("Chalice Telemetry", payload=data)
                        
                        # Broadcast to all connected dashboard clients
                        for client in self.dashboard_clients:
                            if not client.closed:
                                await client.send_json(data)
                                
                        # Echo acknowledgement for 2-way sync
                        await ws.send_json({"status": "received", "event": data.get("event", "unknown")})
                    except json.JSONDecodeError:
                        logger.warning("Received invalid JSON from Chalice")
                elif msg.type == web.WSMsgType.ERROR:
                    logger.error("WebSocket connection closed with exception", error=ws.exception())
        finally:
            logger.info("Chalice plugin disconnected")
            
        return ws

    async def handle_telemetry_post(self, request):
        try:
            data = await request.json()
            logger.debug("Chalice Telemetry via POST", payload=data)
            
            # Log telemetry to disk
            try:
                log_dir = os.path.join(self.config.data_dir, "telemetry")
                os.makedirs(log_dir, exist_ok=True)
                log_file = os.path.join(log_dir, "telemetry.jsonl")
                with open(log_file, "a") as f:
                    f.write(json.dumps(data) + "\n")
            except Exception as e:
                logger.error("Failed to write telemetry to disk", error=str(e))
            
            # Broadcast to all connected dashboard clients
            for client in self.dashboard_clients:
                if not client.closed:
                    await client.send_json(data)
                    
            return web.json_response({"status": "received", "event": data.get("event", "unknown")})
        except json.JSONDecodeError:
            logger.warning("Received invalid JSON from Chalice POST")
            return web.json_response({"error": "Invalid JSON"}, status=400)

    async def broadcast_telemetry(self, data: dict):
        # Broadcast to all connected dashboard clients
        for client in list(self.dashboard_clients):
            if not client.closed:
                try:
                    await client.send_json(data)
                except Exception as e:
                    logger.warning("Failed to send telemetry to dashboard client", error=str(e))

    async def handle_dashboard_ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.dashboard_clients.add(ws)
        
        try:
            async for msg in ws:
                pass # Dashboard only listens
        finally:
            self.dashboard_clients.remove(ws)
            
        return ws

    async def handle_chats(self, request):
        # Return all unique contexts from the conversations table by doing a group by
        db = self.config.db if hasattr(self.config, 'db') else None
        
        # We need a reference to DB. Let's see if we can get it from the globally injected db or router
        from ganymede.core.agent_manager import AgentManager
        
        # We will just fetch directly from DB if available, else return empty
        # Wait, the DashboardServer doesn't have db injected in __init__ currently.
        # Let's import it or just query the sqlite directly since we have data_dir
        import aiosqlite
        db_path = os.path.join(self.config.data_dir, "ganymede.db")
        
        chats = []
        if os.path.exists(db_path):
            async with aiosqlite.connect(db_path) as conn:
                conn.row_factory = aiosqlite.Row
                
                # Fetch Ganymede-native conversations
                async with conn.execute("""
                    SELECT context_platform, context_channel, context_thread, MAX(created_at) as last_active, COUNT(id) as msg_count
                    FROM conversations 
                    GROUP BY context_platform, context_channel, context_thread
                    ORDER BY last_active DESC
                """) as cursor:
                    rows = await cursor.fetchall()
                    for r in rows:
                        conversation_id = f"{r['context_platform']}_{r['context_channel']}"
                        if r['context_thread']:
                            conversation_id += f"_{r['context_thread']}"
                            
                        actual_conv_id = conversation_id
                        try:
                            async with conn.execute(
                                "SELECT conversation_id FROM conversation_mappings WHERE platform = ? AND channel_id = ? AND (thread_id = ? OR (thread_id IS NULL AND ? IS NULL))",
                                (r["context_platform"], r["context_channel"], r["context_thread"], r["context_thread"])
                            ) as map_cursor:
                                map_row = await map_cursor.fetchone()
                                if map_row:
                                    actual_conv_id = map_row["conversation_id"]
                        except Exception:
                            pass
                            
                        project_name = f"{r['context_platform']}-{r['context_channel']}"
                        if r['context_thread']:
                            project_name += f"-{r['context_thread']}"
                            
                        brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{actual_conv_id}")
                        project_name_path = os.path.join(brain_dir, "project_name.txt")
                        if os.path.exists(project_name_path):
                            try:
                                with open(project_name_path, "r") as f:
                                    pname = f.read().strip()
                                if pname:
                                    project_name = pname
                            except Exception:
                                pass
                                
                        chats.append({
                            "platform": r["context_platform"],
                            "channel_id": r["context_channel"],
                            "thread_id": r["context_thread"],
                            "last_active": r["last_active"],
                            "msg_count": r["msg_count"],
                            "id": f"{r['context_platform']}_{r['context_channel']}_{r['context_thread'] or 'main'}",
                            "actual_conv_id": actual_conv_id,
                            "project_name": project_name
                        })
                        
        # Merge Antigravity CLI native conversations from brain directory
        brain_dir = os.path.expanduser("~/.gemini/antigravity-cli/brain")
        if os.path.exists(brain_dir):
            ganymede_conv_ids = {c.get("actual_conv_id") for c in chats if c.get("actual_conv_id")}
            try:
                cli_chats = []
                for entry in os.listdir(brain_dir):
                    if entry in ganymede_conv_ids or entry == "telemetry.db" or not os.path.isdir(os.path.join(brain_dir, entry)):
                        continue
                        
                    # Get modification time of transcript.jsonl if it exists
                    transcript_path = os.path.join(brain_dir, entry, ".system_generated", "logs", "transcript.jsonl")
                    last_mod = 0
                    msg_count = 0
                    if os.path.exists(transcript_path):
                        last_mod = os.stat(transcript_path).st_mtime
                        try:
                            with open(transcript_path, 'rb') as f:
                                msg_count = sum(1 for _ in f)
                        except Exception:
                            pass
                    else:
                        continue
                        
                    pname = f"cli-{entry[:8]}"
                    pname_path = os.path.join(brain_dir, entry, "project_name.txt")
                    if os.path.exists(pname_path):
                        try:
                            with open(pname_path, "r") as f:
                                pname = f.read().strip() or pname
                        except Exception:
                            pass
                            
                    import datetime
                    cli_chats.append({
                        "platform": "cli",
                        "channel_id": entry[:8],
                        "thread_id": None,
                        "last_active": datetime.datetime.fromtimestamp(last_mod).strftime('%Y-%m-%d %H:%M:%S'),
                        "msg_count": msg_count,
                        "id": f"cli_{entry}_main",
                        "actual_conv_id": entry,
                        "project_name": pname
                    })
                
                cli_chats.sort(key=lambda x: x["last_active"], reverse=True)
                chats.extend(cli_chats[:20])
            except Exception as e:
                print(f"Error fetching brain chats: {e}")
                
        # Re-sort combined list
        chats.sort(key=lambda x: x["last_active"], reverse=True)
        return web.json_response({"chats": chats})

    async def handle_chat_history(self, request):
        context_id = request.match_info.get('id', '')
        parts = context_id.split('_')
        if len(parts) < 3:
            return web.json_response({"error": "Invalid context ID format"}, status=400)
            
        platform = parts[0]
        channel_id = parts[1]
        thread_id = parts[2] if parts[2] != 'main' else None
        
        actual_conv_id = channel_id if platform == "cli" else None
        
        if platform != "cli":
            db_path = os.path.join(self.config.data_dir, "ganymede.db")
            if os.path.exists(db_path):
                import aiosqlite
                async with aiosqlite.connect(db_path) as conn:
                    conn.row_factory = aiosqlite.Row
                    async with conn.execute(
                        "SELECT conversation_id FROM conversation_mappings WHERE platform = ? AND channel_id = ? AND (thread_id = ? OR (thread_id IS NULL AND ? IS NULL))",
                        (platform, channel_id, thread_id, thread_id)
                    ) as cursor:
                        row = await cursor.fetchone()
                        if row:
                            actual_conv_id = row["conversation_id"]

        history = []
        if actual_conv_id:
            transcript_path = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{actual_conv_id}/.system_generated/logs/transcript_full.jsonl")
            if not os.path.exists(transcript_path):
                transcript_path = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{actual_conv_id}/.system_generated/logs/transcript.jsonl")
            
            if os.path.exists(transcript_path):
                import json
                try:
                    with open(transcript_path, 'r') as f:
                        for line in f:
                            if not line.strip(): continue
                            try:
                                data = json.loads(line)
                            except Exception:
                                continue
                            if data.get("type") == "USER_INPUT":
                                history.append({
                                    "author_id": "User",
                                    "role": "user",
                                    "content": data.get("content", ""),
                                    "created_at": data.get("created_at", "")
                                })
                            elif data.get("type") == "PLANNER_RESPONSE" or data.get("type") == "TEXT_RESPONSE":
                                content = data.get("content", "")
                                tool_calls = data.get("tool_calls", [])
                                if tool_calls:
                                    tool_text = "\n\n*⚒️ Tools Used:*\n" + "\n".join([f"- `{t.get('name') or t.get('function', {}).get('name') or 'tool'}`" for t in tool_calls])
                                    content = (content + tool_text) if content else tool_text.strip()
                                
                                if content:
                                    history.append({
                                        "author_id": "Antigravity",
                                        "role": "assistant",
                                        "content": content,
                                        "created_at": data.get("created_at", "")
                                    })
                except Exception as e:
                    print(f"Error reading transcript: {e}")

        # Fallback to database if no transcript history found
        if not history and platform != "cli":
            db_path = os.path.join(self.config.data_dir, "ganymede.db")
            if os.path.exists(db_path):
                import aiosqlite
                async with aiosqlite.connect(db_path) as conn:
                    conn.row_factory = aiosqlite.Row
                    query = """
                        SELECT author_id, role, content, tokens, created_at
                        FROM conversations
                        WHERE context_platform = ? AND context_channel = ? AND (context_thread = ? OR (context_thread IS NULL AND ? IS NULL))
                        ORDER BY created_at ASC
                    """
                    async with conn.execute(query, (platform, channel_id, thread_id, thread_id)) as cursor:
                        rows = await cursor.fetchall()
                        for r in rows:
                            history.append({
                                "author_id": r["author_id"],
                                "role": r["role"],
                                "content": r["content"],
                                "created_at": r["created_at"]
                            })
                            
        return web.json_response({"messages": history})

    async def handle_chat_files(self, request):
        context_id = request.match_info.get('id', '')
        parts = context_id.split('_')
        if len(parts) < 3:
            return web.json_response({"error": "Invalid context ID format"}, status=400)
            
        platform = parts[0]
        channel_id = parts[1]
        thread_id = parts[2] if parts[2] != 'main' else None
        
        db_path = os.path.join(self.config.data_dir, "ganymede.db")
        conversation_id = f"ganymede_{platform}_{channel_id}"
        if thread_id:
            conversation_id += f"_{thread_id}"
            
        # Check mapping table to resolve merged context
        if os.path.exists(db_path):
            import aiosqlite
            async with aiosqlite.connect(db_path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(
                    "SELECT conversation_id FROM conversation_mappings WHERE platform = ? AND channel_id = ? AND (thread_id = ? OR (thread_id IS NULL AND ? IS NULL))",
                    (platform, channel_id, thread_id, thread_id)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row and row["conversation_id"]:
                        conversation_id = row["conversation_id"]
                        
        # The default AGY workspace path for artifacts
        # We can also check if there's a local .gemini folder or use the default global
        # Let's check ~/.gemini/antigravity-cli/brain/{conversation_id}
        agy_brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{conversation_id}")
        files_data = []
        
        if os.path.exists(agy_brain_dir):
            for root, dirs, files in os.walk(agy_brain_dir):
                # Optionally exclude logs
                if ".system_generated" in root: continue
                for file in files:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, agy_brain_dir)
                    size = os.path.getsize(full_path)
                    files_data.append({"name": file, "path": rel_path, "size": size})
                    
        return web.json_response({"files": files_data, "workspace": agy_brain_dir})

    async def handle_chat_merge(self, request):
        context_id = request.match_info.get('id', '')
        data = await request.json()
        target_conversation_id = data.get('target_conversation_id')
        
        if not target_conversation_id:
            return web.json_response({"error": "Missing target_conversation_id"}, status=400)
            
        parts = context_id.split('_')
        if len(parts) < 3:
            return web.json_response({"error": "Invalid context ID format"}, status=400)
            
        platform = parts[0]
        channel_id = parts[1]
        thread_id = parts[2] if parts[2] != 'main' else None
        
        db_path = os.path.join(self.config.data_dir, "ganymede.db")
        if os.path.exists(db_path):
            import aiosqlite
            async with aiosqlite.connect(db_path) as conn:
                # Merge logic: We explicitly map this (platform, channel, thread) to the target_conversation_id
                await conn.execute(
                    """
                    INSERT INTO conversation_mappings (platform, channel_id, thread_id, conversation_id)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(platform, channel_id, thread_id) DO UPDATE SET
                        conversation_id = excluded.conversation_id
                    """,
                    (platform, channel_id, thread_id, target_conversation_id)
                )
                await conn.commit()
        
        return web.json_response({"status": "merged", "target_conversation_id": target_conversation_id})

    async def handle_chat_fork(self, request):
        import uuid
        import shutil
        
        context_id = request.match_info.get('id', '')
        conversation_id = await self._resolve_conversation_id(context_id)
        if not conversation_id:
            return web.json_response({"error": "Invalid context ID format"}, status=400)
            
        parts = context_id.split('_')
        platform = parts[0]
        channel_id = parts[1]
        thread_id = parts[2] if parts[2] != 'main' else None
        
        new_thread_id = f"fork-{uuid.uuid4().hex[:8]}"
        new_conversation_id = f"ganymede_{platform}_{channel_id}_{new_thread_id}"
        
        # 1. Copy agy brain dir
        old_brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{conversation_id}")
        new_brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{new_conversation_id}")
        if os.path.exists(old_brain_dir):
            shutil.copytree(old_brain_dir, new_brain_dir)
            
        # 2. Copy DB History
        db_path = os.path.join(self.config.data_dir, "ganymede.db")
        if os.path.exists(db_path):
            import aiosqlite
            async with aiosqlite.connect(db_path) as conn:
                await conn.execute(
                    """
                    INSERT INTO conversations (context_platform, context_channel, context_thread, author_id, role, content, tokens, created_at)
                    SELECT context_platform, context_channel, ?, author_id, role, content, tokens, created_at
                    FROM conversations
                    WHERE context_platform = ? AND context_channel = ? AND (context_thread = ? OR (context_thread IS NULL AND ? IS NULL))
                    """,
                    (new_thread_id, platform, channel_id, thread_id, thread_id)
                )
                await conn.commit()
                
        new_context_id = f"{platform}_{channel_id}_{new_thread_id}"
        return web.json_response({"status": "forked", "new_context_id": new_context_id})

    async def _resolve_conversation_id(self, context_id: str) -> str:
        parts = context_id.split('_')
        if len(parts) < 3:
            return None
        platform = parts[0]
        channel_id = parts[1]
        thread_id = parts[2] if parts[2] != 'main' else None
        
        conversation_id = f"ganymede_{platform}_{channel_id}"
        if thread_id:
            conversation_id += f"_{thread_id}"
            
        db_path = os.path.join(self.config.data_dir, "ganymede.db")
        if os.path.exists(db_path):
            import aiosqlite
            async with aiosqlite.connect(db_path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(
                    "SELECT conversation_id FROM conversation_mappings WHERE platform = ? AND channel_id = ? AND (thread_id = ? OR (thread_id IS NULL AND ? IS NULL))",
                    (platform, channel_id, thread_id, thread_id)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row and row["conversation_id"]:
                        conversation_id = row["conversation_id"]
        return conversation_id

    async def handle_chat_settings_get(self, request):
        context_id = request.match_info.get('id', '')
        conversation_id = await self._resolve_conversation_id(context_id)
        if not conversation_id:
            return web.json_response({"error": "Invalid context ID format"}, status=400)
            
        brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{conversation_id}")
        
        # Read Model
        model_path = os.path.join(brain_dir, "model.txt")
        model_override = ""
        if os.path.exists(model_path):
            with open(model_path, "r") as f:
                model_override = f.read().strip()
                
        # Read Project Name
        project_name_path = os.path.join(brain_dir, "project_name.txt")
        project_name = ""
        if os.path.exists(project_name_path):
            with open(project_name_path, "r") as f:
                project_name = f.read().strip()
        else:
            # Generate default
            parts = context_id.split('_')
            platform = parts[0]
            channel_id = parts[1]
            thread_id = parts[2] if len(parts) > 2 and parts[2] != 'main' else None
            project_name = f"{platform}-{channel_id}"
            if thread_id:
                project_name += f"-{thread_id}"
                
        # Read Mode
        mode_path = os.path.join(brain_dir, "mode.txt")
        mode = "accept-edits"
        if os.path.exists(mode_path):
            with open(mode_path, "r") as f:
                mode = f.read().strip()
                
        # Read Rules
        rules_path = os.path.join(brain_dir, "sys_instructions.txt")
        rules = ""
        if os.path.exists(rules_path):
            with open(rules_path, "r") as f:
                rules = f.read().strip()

        # Read Skip Permissions
        skip_permissions = False
        skip_permissions_path = os.path.join(brain_dir, "skip_permissions.txt")
        if os.path.exists(skip_permissions_path):
            with open(skip_permissions_path, "r") as f:
                skip_permissions = f.read().strip() == "true"
                
        return web.json_response({
            "model": model_override, 
            "project_name": project_name,
            "mode": mode,
            "skip_permissions": skip_permissions,
            "rules": rules
        })
        
    async def handle_chat_settings_post(self, request):
        context_id = request.match_info.get('id', '')
        conversation_id = await self._resolve_conversation_id(context_id)
        if not conversation_id:
            return web.json_response({"error": "Invalid context ID format"}, status=400)
            
        data = await request.json()
        model_override = data.get("model", "").strip()
        project_name = data.get("project_name", "").strip()
        
        brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{conversation_id}")
        os.makedirs(brain_dir, exist_ok=True)
        
        model_path = os.path.join(brain_dir, "model.txt")
        if model_override:
            with open(model_path, "w") as f:
                f.write(model_override)
        elif os.path.exists(model_path):
            os.remove(model_path)
            
        project_name_path = os.path.join(brain_dir, "project_name.txt")
        if project_name:
            with open(project_name_path, "w") as f:
                f.write(project_name)
        elif os.path.exists(project_name_path):
            os.remove(project_name_path)
            
        mode = data.get("mode", "")
        mode_path = os.path.join(brain_dir, "mode.txt")
        if mode:
            with open(mode_path, "w") as f:
                f.write(mode)
        elif os.path.exists(mode_path):
            os.remove(mode_path)
            
        skip_permissions = data.get("skip_permissions")
        skip_permissions_path = os.path.join(brain_dir, "skip_permissions.txt")
        if skip_permissions is not None:
            with open(skip_permissions_path, "w") as f:
                f.write("true" if skip_permissions else "false")
        elif os.path.exists(skip_permissions_path):
            os.remove(skip_permissions_path)
            
        rules = data.get("rules")
        rules_path = os.path.join(brain_dir, "sys_instructions.txt")
        if rules is not None:
            if rules.strip() == "":
                if os.path.exists(rules_path):
                    os.remove(rules_path)
            else:
                with open(rules_path, "w") as f:
                    f.write(rules)
            
        # Log this change directly into the chat history for visibility
        try:
            db_path = os.path.join(self.config.data_dir, "ganymede.db")
            if os.path.exists(db_path):
                import aiosqlite
                parts = context_id.split('_')
                platform = parts[0]
                channel_id = parts[1]
                thread_id = parts[2] if parts[2] != 'main' else None
                async with aiosqlite.connect(db_path) as conn:
                    content = f"⚙️ *Administrator updated project settings:*"
                    if model_override:
                        content += f"\n- **Model**: `{model_override}`"
                    if project_name:
                        content += f"\n- **Project Name**: `{project_name}`"
                    if not model_override and not project_name:
                        content += f"\n- Restored to defaults."
                        
                    await conn.execute(
                        """
                        INSERT INTO conversations (context_platform, context_channel, context_thread, author_id, role, content, tokens)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (platform, channel_id, thread_id, "system", "system", content, 0)
                    )
                    await conn.commit()
        except Exception as e:
            logger.error("Failed to log settings change to db", error=str(e))
            
        return web.json_response({"status": "saved", "model": model_override, "project_name": project_name})

    async def handle_files(self, request):
        workspace = self.config.workspace if hasattr(self.config, 'workspace') else os.path.expanduser("~/.ganymede/workspace")
        files_data = []
        
        if os.path.exists(workspace):
            for root, dirs, files in os.walk(workspace):
                for file in files:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, workspace)
                    size = os.path.getsize(full_path)
                    files_data.append({"name": file, "path": rel_path, "size": size})
                    
        return web.json_response({"files": files_data, "workspace": workspace})

    async def start(self):
        logger.info("Starting Ganymede dashboard on http://0.0.0.0:8080")
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '0.0.0.0', 8080)
        await self.site.start()

    async def stop(self):
        if self.runner:
            logger.info("Stopping Ganymede dashboard")
            await self.runner.cleanup()
