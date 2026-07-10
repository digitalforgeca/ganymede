import os
import structlog
import json
from aiohttp import web
from ganymede.config import AppConfig

logger = structlog.get_logger()

class DashboardServer:
    def __init__(self, config: AppConfig):
        self.config = config
        self.app = web.Application()
        
        # API Routes
        self.app.router.add_get('/api/status', self.handle_status)
        self.app.router.add_get('/ws/telemetry', self.handle_telemetry_ws)
        
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
                        # Here we can broadcast data to dashboard clients or process it
                        logger.debug("Chalice Telemetry", payload=data)
                        
                        # Echo acknowledgement for 2-way sync
                        await ws.send_json({"status": "received", "event": data.get("event", "unknown")})
                    except json.JSONDecodeError:
                        logger.warning("Received invalid JSON from Chalice")
                elif msg.type == web.WSMsgType.ERROR:
                    logger.error("WebSocket connection closed with exception", error=ws.exception())
        finally:
            logger.info("Chalice plugin disconnected")
            
        return ws

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
