import os
import asyncio
import structlog
import json
import yaml
from aiohttp import web
from ganymede.config import AppConfig
from ganymede.core import ContextKey

logger = structlog.get_logger()

def handle_ipc_request(server, method_name: str, required_args: list[str]):
    async def handler(request: web.Request) -> web.Response:
        try:
            data = await request.json()
            platform = data.get("platform", "discord")
            
            adapter = server._get_provider_adapter(platform)
            if not adapter:
                return web.json_response({"error": f"Provider adapter for platform '{platform}' not found or not running."}, status=404)
                
            method = getattr(adapter, method_name, None)
            if not method:
                return web.json_response({"error": f"Method {method_name} not implemented for platform '{platform}'."}, status=501)
                
            kwargs = {k: data[k] for k in required_args if k in data}
            
            # Special cases for optional arguments
            if method_name == 'create_thread' and 'content' in data:
                kwargs['content'] = data['content']
            elif method_name == 'create_thread' and 'content' not in data:
                kwargs['content'] = ""

            result = await method(**kwargs)
            
            if isinstance(result, list):
                return web.json_response({"messages": result})
            elif isinstance(result, dict):
                return web.json_response(result)
            else:
                return web.json_response({"status": "ok", "data": result})
                
        except Exception as e:
            logger.error(f"IPC Server error on {method_name}", error=str(e))
            return web.json_response({"error": str(e)}, status=500)
    return handler


async def handle_schedule_cron(server, request: web.Request) -> web.Response:
    data = await request.json()
    platform = data.get("platform", "discord")
    cron_expr = data.get("cron_expr")
    prompt = data.get("prompt")
    channel_id = data.get("channel_id")
    
    if not all([cron_expr, prompt, channel_id]):
        return web.json_response({"error": "Missing cron_expr, prompt, or channel_id"}, status=400)
        
    for provider in getattr(server, "providers", []):
        provider_platform = getattr(provider.config, "platform", "discord").lower()
        if provider_platform == platform.lower() and hasattr(provider, "scheduler"):
            import uuid
            from ganymede.core import ContextKey
            job_id = str(uuid.uuid4())
            context = ContextKey(platform, str(channel_id), None)
            try:
                await provider.scheduler.add_cron_job(job_id, context, "system", cron_expr, prompt)
                return web.json_response({"job_id": job_id, "status": "scheduled"})
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)
                
    return web.json_response({"error": f"Scheduler not found for platform '{platform}'."}, status=501)


async def handle_status_update(server, request: web.Request) -> web.Response:
    try:
        data = await request.json()
        conversation_id = data.get("conversation_id")
        tool_name = data.get("tool_name")
        tool_args = data.get("tool_args", {})
        platform = data.get("platform", "discord")
        
        if not conversation_id or not tool_name:
            return web.json_response({"error": "Missing conversation_id or tool_name"}, status=400)
            
        adapter = server._get_provider_adapter(platform)
        if adapter and hasattr(adapter, "update_streaming_status"):
            # We need context key to update streaming status
            from ganymede.core import ContextKey
            import re
            
            # Best effort context recovery
            channel_id = None
            match = re.search(r"_(\d{17,20})$", conversation_id)
            if match:
                channel_id = match.group(1)
            
            if channel_id:
                context = ContextKey(platform, channel_id, None)
                from ganymede.core.status import format_tool_status
                status_text = format_tool_status(tool_name, tool_args)
                await adapter.update_streaming_status(context, status_text)
                
        return web.json_response({"status": "ok"})
    except Exception as e:
        logger.error("Failed to process status update request", error=str(e))
        return web.json_response({"error": str(e)}, status=500)


async def handle_test_invoke(server, request: web.Request) -> web.Response:
    """Simulate an incoming message for testing purposes."""
    try:
        data = await request.json()
        platform = data.get("platform", "discord")
        channel_id = data.get("channel_id")
        content = data.get("content")
        author_id = data.get("author_id", "test_user_id")
        author_name = data.get("author_name", "TestUser")
        
        if not channel_id or not content:
            return web.json_response({"error": "Missing channel_id or content"}, status=400)
            
        adapter = server._get_provider_adapter(platform)
        if not adapter or not hasattr(adapter, "_on_message_callback") or not adapter._on_message_callback:
            return web.json_response({"error": "Adapter missing _on_message_callback"}, status=500)
            
        from ganymede.core import ContextKey
        from ganymede.core.models import PlatformMessage
        
        context = ContextKey(platform=platform, channel_id=str(channel_id), thread_id=None)
        normalized = PlatformMessage(
            context=context,
            author_id=str(author_id),
            author_name=author_name,
            content=content,
            is_bot=False,
            mentions_us=True,
            attachments=[],
            reply_to=None,
            raw=None
        )
        
        asyncio.create_task(adapter._on_message_callback(normalized))
        return web.json_response({"status": "invoked", "channel_id": channel_id})
    except Exception as e:
        logger.error("Failed to process test invoke", error=str(e))
        return web.json_response({"error": str(e)}, status=500)

