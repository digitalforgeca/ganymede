import asyncio
import structlog
from typing import Callable, Awaitable, Any
from aiohttp import web
from ganymede.platforms.base import BasePlatformProvider, PlatformAdapter
from ganymede.core import ContextKey
from ganymede.core.models import PlatformMessage
import ganymede.core.web as gweb

logger = structlog.get_logger()

class WebAdapter(PlatformAdapter):
    def __init__(self, config):
        self.config = config
        self.on_message_callback = None
        
    async def start(self) -> None:
        logger.info("WebAdapter started")
        
        # Attach routes to the globally running dashboard instance
        if gweb.dashboard_instance:
            gweb.dashboard_instance.web_invoke_callback = self.handle_invoke
            logger.info("Registered web invoke callback with dashboard instance")
            
    async def stop(self) -> None:
        pass
        
    async def handle_invoke(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            prompt = data.get("prompt")
            channel_id = data.get("channel_id", "web-default")
            
            if not prompt:
                return web.json_response({"error": "Prompt required"}, status=400)
                
            context = ContextKey(platform="web", channel_id=channel_id)
            
            # Formulate the platform message
            msg = PlatformMessage(
                context=context,
                author_id="web_user",
                author_name="Web UI",
                content=prompt,
                is_bot=False,
                mentions_us=True
            )
            
            if self.on_message_callback:
                # Dispatch the message to the router asynchronously
                asyncio.create_task(self.on_message_callback(msg))
                
            return web.json_response({"status": "queued", "context": str(context)})
        except Exception as e:
            logger.error("Failed to handle web invocation", error=str(e))
            return web.json_response({"error": str(e)}, status=500)

    async def send_response(self, context: ContextKey, content: str, metadata: dict[str, Any]) -> None:
        if gweb.dashboard_instance:
            await gweb.dashboard_instance.broadcast_telemetry({
                "event": "Agent Response",
                "level": "info",
                "context": f"{context.platform}_{context.channel_id}_{context.thread_id or 'main'}",
                "payload": {"content": content, "metadata": metadata}
            })

    async def send_streaming_start(self, context: ContextKey, initial_text: str | None = None, persist_header: str | None = None) -> str:
        import uuid
        msg_id = f"web-msg-{uuid.uuid4().hex[:8]}"
        if gweb.dashboard_instance:
            await gweb.dashboard_instance.broadcast_telemetry({
                "event": "Agent Stream Start",
                "level": "info",
                "context": f"{context.platform}_{context.channel_id}_{context.thread_id or 'main'}",
                "payload": {"msg_id": msg_id, "content": initial_text or "⏳ *Thinking...*"}
            })
        return msg_id
        
    async def edit_streaming(self, context: ContextKey, message_id: str, content: str) -> None:
        if gweb.dashboard_instance:
            await gweb.dashboard_instance.broadcast_telemetry({
                "event": "Agent Stream Edit",
                "level": "info",
                "context": f"{context.platform}_{context.channel_id}_{context.thread_id or 'main'}",
                "payload": {"msg_id": message_id, "content": content}
            })
        
    async def send_streaming_end(self, context: ContextKey, message_id: str, metadata: dict[str, Any]) -> None:
        if gweb.dashboard_instance:
            await gweb.dashboard_instance.broadcast_telemetry({
                "event": "Agent Stream End",
                "level": "info",
                "context": f"{context.platform}_{context.channel_id}_{context.thread_id or 'main'}",
                "payload": {"msg_id": message_id, "metadata": metadata}
            })

    async def update_streaming_status(self, context: ContextKey, status_text: str) -> None:
        pass

    def register_on_message(self, callback: Callable[[PlatformMessage], Awaitable[None]]) -> None:
        self.on_message_callback = callback

    def get_conversation_id(self, context: ContextKey) -> str:
        return context.ganymede_conv_id


class WebProvider(BasePlatformProvider):
    def __init__(self, config: Any, router: Any, db: Any):
        super().__init__(config, router, db)
        self.adapter = WebAdapter(config)
        
    async def start(self) -> None:
        logger.info("Starting WebProvider", platform="web")
        self.adapter.register_on_message(self.router.handle_message)
        self.router.set_adapter(self.adapter)
        await self.adapter.start()
        
    async def stop(self) -> None:
        await self.adapter.stop()
