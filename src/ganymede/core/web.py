import os
import asyncio
import structlog
import json
from aiohttp import web
from ganymede.config import AppConfig
from ganymede.core import ContextKey

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
        self.app.router.add_get('/api/providers', self.handle_providers_get)
        self.app.router.add_get('/api/bots', self.handle_bots_get)
        self.app.router.add_post('/api/bots/{bot_id}', self.handle_bot_post)
        self.app.router.add_delete('/api/bots/{bot_id}', self.handle_bot_delete)
        self.app.router.add_post('/api/config', self.handle_config_post)
        self.app.router.add_get('/api/rules', self.handle_rules_get)
        self.app.router.add_post('/api/rules', self.handle_rules_post)
        self.app.router.add_delete('/api/rules/{filename}', self.handle_rule_delete)
        self.app.router.add_get('/api/bots/detail/conversations', self.handle_bot_conversations)
        self.app.router.add_get('/api/user', self.handle_user_info)
        self.app.router.add_get('/ws/telemetry', self.handle_telemetry_ws)
        self.app.router.add_get('/ws/dashboard', self.handle_dashboard_ws)
        
        # Internal IPC API for SSE Tools
        self.app.router.add_post('/api/channel/history', self.handle_ipc_request('get_channel_history', ["channel_id", "limit"]))
        self.app.router.add_post('/api/channel/info', self.handle_ipc_request('get_channel_info', ["channel_id"]))
        self.app.router.add_post('/api/message/post', self.handle_ipc_request('post_message', ["channel_id", "content"]))
        self.app.router.add_post('/api/message/reply', self.handle_ipc_request('reply_message', ["channel_id", "message_id", "content"]))
        self.app.router.add_post('/api/message/edit', self.handle_ipc_request('edit_message', ["channel_id", "message_id", "content"]))
        self.app.router.add_post('/api/message/react', self.handle_ipc_request('react_message', ["channel_id", "message_id", "emoji"]))
        self.app.router.add_post('/api/message/get', self.handle_ipc_request('get_message', ["channel_id", "message_id"]))
        self.app.router.add_post('/api/thread/create', self.handle_ipc_request('create_thread', ["channel_id", "name", "content"]))
        
        # Schedule cron is a special case since it interacts with the scheduler
        self.app.router.add_post('/api/schedule/cron', self.handle_schedule_cron)
        
        # Additional IPC routes migrated from discord/ipc_server
        self.app.router.add_post('/api/status/update', self.handle_status_update)
        self.app.router.add_post('/api/test/invoke', self.handle_test_invoke)
        
        # Track connected frontend clients
        self.dashboard_clients = set()
        self.telemetry_listeners = []
        
        # Static Dashboard Routes
        import shutil
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
                
        self.web_dir = theme_dir
            
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_static('/', self.web_dir, name='static')
            
        self.runner = None
        self.site = None
        self.web_invoke_callback = None
        self.platform_states = {}
        self.mcp_task = None

    def set_platform_status(self, platform: str, is_connected: bool) -> None:
        self.platform_states[platform] = is_connected

    async def start_mcp_server(self):
        try:
            import uvicorn
            from ganymede.mcp_server import app as mcp_app
            starlette_app = mcp_app.sse_app("/mcp")
            
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
            
            cfg = uvicorn.Config(wrapped_app, host="0.0.0.0", port=8081, log_level="warning")
            self.uvicorn_server = uvicorn.Server(cfg)
            await self.uvicorn_server.serve()
        except Exception as e:
            logger.error("FastMCP SSE server crashed", error=str(e))


from ganymede.core.routes.dashboard import handle_index, handle_status, handle_user_info, handle_dashboard_ws, handle_files
from ganymede.core.routes.chats import handle_chats, handle_chat_history, handle_chat_files, handle_chat_merge, handle_chat_fork, handle_chat_settings_get, handle_chat_settings_post, handle_chat_invoke
from ganymede.core.routes.config import handle_config_get, handle_config_post, handle_rules_get, handle_rules_post, handle_rule_delete, handle_bot_conversations, handle_providers_get, handle_bots_get, handle_bot_post, handle_bot_delete
from ganymede.core.routes.telemetry import handle_telemetry_ws, handle_telemetry_post
from ganymede.core.routes.ipc import handle_ipc_request, handle_schedule_cron, handle_status_update, handle_test_invoke

DashboardServer.handle_index = handle_index
DashboardServer.handle_status = handle_status
DashboardServer.handle_user_info = handle_user_info
DashboardServer.handle_dashboard_ws = handle_dashboard_ws
DashboardServer.handle_files = handle_files

DashboardServer.handle_chats = handle_chats
DashboardServer.handle_chat_history = handle_chat_history
DashboardServer.handle_chat_files = handle_chat_files
DashboardServer.handle_chat_merge = handle_chat_merge
DashboardServer.handle_chat_fork = handle_chat_fork
DashboardServer.handle_chat_settings_get = handle_chat_settings_get
DashboardServer.handle_chat_settings_post = handle_chat_settings_post
DashboardServer.handle_chat_invoke = handle_chat_invoke

DashboardServer.handle_config_get = handle_config_get
DashboardServer.handle_providers_get = handle_providers_get
DashboardServer.handle_bots_get = handle_bots_get
DashboardServer.handle_bot_post = handle_bot_post
DashboardServer.handle_bot_delete = handle_bot_delete
DashboardServer.handle_config_post = handle_config_post
DashboardServer.handle_rules_get = handle_rules_get
DashboardServer.handle_rules_post = handle_rules_post
DashboardServer.handle_rule_delete = handle_rule_delete
DashboardServer.handle_bot_conversations = handle_bot_conversations

DashboardServer.handle_telemetry_ws = handle_telemetry_ws
DashboardServer.handle_telemetry_post = handle_telemetry_post

DashboardServer.handle_ipc_request = handle_ipc_request
DashboardServer.handle_schedule_cron = handle_schedule_cron
DashboardServer.handle_status_update = handle_status_update
DashboardServer.handle_test_invoke = handle_test_invoke
