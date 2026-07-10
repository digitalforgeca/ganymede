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

    async def handle_index(self, request):
        index_path = os.path.join(self.web_dir, 'index.html')
        if os.path.exists(index_path):
            return web.FileResponse(index_path)
        return web.Response(text="Dashboard initializing...", status=404)

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
