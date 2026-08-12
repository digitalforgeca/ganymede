import os
import asyncio
import structlog
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from ganymede.config import AppConfig
import uvicorn
import shutil

logger = structlog.get_logger()

dashboard_instance = None

class DashboardServer:
    def __init__(self, config: AppConfig, db=None):
        global dashboard_instance
        dashboard_instance = self
        self.config = config
        self.db = db
        self.app = FastAPI(title="Ganymede API")
        self.app.state.server = self
        
        from fastapi import Depends
        from ganymede.core.routes import dashboard, chats, config as config_routes, telemetry, ipc, auth

        # Mount routers
        self.app.include_router(auth.router)
        self.app.include_router(dashboard.router, dependencies=[Depends(auth.require_auth)])
        self.app.include_router(chats.router, dependencies=[Depends(auth.require_auth)])
        self.app.include_router(config_routes.router, dependencies=[Depends(auth.require_auth)])
        self.app.include_router(telemetry.router)
        self.app.include_router(ipc.router)
        
        # Internal IPC API for SSE Tools
        self.app.add_api_route('/api/channel/history', ipc.handle_ipc_request(self, 'get_channel_history', ["channel_id", "limit"]), methods=["POST"])
        self.app.add_api_route('/api/channel/info', ipc.handle_ipc_request(self, 'get_channel_info', ["channel_id"]), methods=["POST"])
        self.app.add_api_route('/api/message/post', ipc.handle_ipc_request(self, 'post_message', ["channel_id", "content"]), methods=["POST"])
        self.app.add_api_route('/api/message/reply', ipc.handle_ipc_request(self, 'reply_message', ["channel_id", "message_id", "content"]), methods=["POST"])
        self.app.add_api_route('/api/message/edit', ipc.handle_ipc_request(self, 'edit_message', ["channel_id", "message_id", "content"]), methods=["POST"])
        self.app.add_api_route('/api/message/react', ipc.handle_ipc_request(self, 'react_message', ["channel_id", "message_id", "emoji"]), methods=["POST"])
        self.app.add_api_route('/api/message/get', ipc.handle_ipc_request(self, 'get_message', ["channel_id", "message_id"]), methods=["POST"])
        self.app.add_api_route('/api/thread/create', ipc.handle_ipc_request(self, 'create_thread', ["channel_id", "name", "content"]), methods=["POST"])
        self.app.add_api_route('/api/attachment/download', ipc.handle_ipc_request(self, 'download_attachment', ["url", "absolute_path"]), methods=["POST"])
        
        # Track connected frontend clients
        self.dashboard_clients = set()
        self.telemetry_listeners = []
        
        # Static Dashboard Routes
        embedded_web_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'web')
        user_web_dir = os.path.expanduser('~/.ganymede/web')
        
        active_theme = getattr(self.config, "theme", "default")
        
        # If the user directory doesn't exist, we copy the embedded one over to populate themes/default.
        if not os.path.exists(user_web_dir) or not os.path.exists(os.path.join(user_web_dir, 'themes', 'default')):
            logger.info("Initializing user web directory with default assets", dest=user_web_dir)
            os.makedirs(user_web_dir, exist_ok=True)
            if os.path.exists(embedded_web_dir):
                shutil.copytree(embedded_web_dir, user_web_dir, dirs_exist_ok=True)
                
        # Resolve the active theme directory
        theme_dir = os.path.join(user_web_dir, 'themes', active_theme)
        if not os.path.exists(theme_dir):
            logger.warning(f"Theme '{active_theme}' not found, falling back to 'default'")
            theme_dir = os.path.join(user_web_dir, 'themes', 'default')
                
        # Check if dist exists in the theme dir
        dist_dir = os.path.join(theme_dir, "dist")
        if os.path.exists(dist_dir):
            self.web_dir = dist_dir
        else:
            self.web_dir = theme_dir
            
        # Mount static files. We want to serve index.html at /, so we mount at /
        self.app.mount('/', StaticFiles(directory=self.web_dir, html=True), name='static')
        
        @self.app.exception_handler(StarletteHTTPException)
        async def catch_all_handler(request: Request, exc: StarletteHTTPException):
            if exc.status_code == 404:
                if request.url.path.startswith("/api/") or request.url.path.startswith("/ws/") or request.url.path.startswith("/mcp/"):
                    return JSONResponse({"error": "Not found"}, status_code=404)
                
                index_path = os.path.join(self.web_dir, "index.html")
                if os.path.exists(index_path):
                    return FileResponse(index_path)
            
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
            
        self.runner = None
        self.site = None
        self.web_invoke_callback = None
        self.platform_states = {}
        self.mcp_task = None

    def set_platform_status(self, platform: str, is_connected: bool) -> None:
        self.platform_states[platform] = is_connected

    async def start_mcp_server(self):
        try:
            from ganymede.mcp_server import app as mcp_app
            if hasattr(mcp_app, "sse_app"):
                starlette_app = mcp_app.sse_app("/mcp")
            else:
                starlette_app = mcp_app.http_app(path="/mcp", transport="sse")
            
            # Simple ASGI middleware for Auth
            token = getattr(self.config.agent, "mcp_auth_token", "default_secure_token_123")
            class MCPAuthMiddleware:
                def __init__(self, app):
                    self.app = app
                async def __call__(self, scope, receive, send):
                    if scope["type"] != "http":
                        return await self.app(scope, receive, send)
                    headers = dict(scope.get("headers", []))
                    auth = headers.get(b"authorization", b"").decode("utf-8")
                    if not auth or auth != f"Bearer {token}":
                        await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"application/json")]})
                        await send({"type": "http.response.body", "body": b'{"error": "Unauthorized"}'})
                        return
                    return await self.app(scope, receive, send)
                    
            wrapped_app = MCPAuthMiddleware(starlette_app)
            
            cfg = uvicorn.Config(wrapped_app, host="0.0.0.0", port=8081, log_level="warning", log_config=None)
            self.mcp_uvicorn_server = uvicorn.Server(cfg)
            await self.mcp_uvicorn_server.serve()
        except Exception as e:
            logger.error("FastMCP SSE server crashed", error=str(e))

    async def start(self):
        port = getattr(self.config.agent, "dashboard_port", 8180)
        
        cfg = uvicorn.Config(self.app, host="0.0.0.0", port=port, log_level="warning", log_config=None)
        self.uvicorn_server = uvicorn.Server(cfg)
        
        # Start dashboard server
        self.server_task = asyncio.create_task(self.uvicorn_server.serve())
        
        logger.info(f"Dashboard started on port {port}", url=f"http://localhost:{port}")
        
        # Start SSE MCP server on 8081 natively
        self.mcp_task = asyncio.create_task(self.start_mcp_server())

    async def stop(self):
        if getattr(self, 'mcp_task', None):
            self.mcp_task.cancel()
        if getattr(self, 'mcp_uvicorn_server', None):
            self.mcp_uvicorn_server.should_exit = True
        if getattr(self, 'uvicorn_server', None):
            self.uvicorn_server.should_exit = True
            if hasattr(self, 'server_task'):
                await self.server_task
        logger.info("Dashboard stopped")
