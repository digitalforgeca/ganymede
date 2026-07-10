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
        self.app.router.add_post('/api/chats/{id}/merge', self.handle_chat_merge)
        self.app.router.add_post('/api/telemetry', self.handle_telemetry_post)
        self.app.router.add_post('/api/chat/invoke', self.handle_chat_invoke)
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
        return web.json_response({
            "status": "online",
            "platform": self.config.platform,
            "data_dir": self.config.data_dir,
            "log_level": self.config.log_level
        })

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
                async with conn.execute("""
                    SELECT context_platform, context_channel, context_thread, MAX(created_at) as last_active, COUNT(id) as msg_count
                    FROM conversations 
                    GROUP BY context_platform, context_channel, context_thread
                    ORDER BY last_active DESC
                """) as cursor:
                    rows = await cursor.fetchall()
                    for r in rows:
                        chats.append({
                            "platform": r["context_platform"],
                            "channel_id": r["context_channel"],
                            "thread_id": r["context_thread"],
                            "last_active": r["last_active"],
                            "msg_count": r["msg_count"],
                            "id": f"{r['context_platform']}_{r['context_channel']}_{r['context_thread'] or 'main'}"
                        })
        return web.json_response({"chats": chats})

    async def handle_chat_history(self, request):
        context_id = request.match_info.get('id', '')
        parts = context_id.split('_')
        if len(parts) < 3:
            return web.json_response({"error": "Invalid context ID format"}, status=400)
            
        platform = parts[0]
        channel_id = parts[1]
        thread_id = parts[2] if parts[2] != 'main' else None
        
        db_path = os.path.join(self.config.data_dir, "ganymede.db")
        history = []
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
