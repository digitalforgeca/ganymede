import os
import asyncio
import structlog
import json
import yaml
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from ganymede.config import AppConfig
from ganymede.core import ContextKey

logger = structlog.get_logger()

router = APIRouter()

def handle_ipc_request(server, method_name: str, required_args: list[str]):
    async def handler(request: Request):
        try:
            data = await request.json()
            platform = data.get("platform", "discord")
            
            adapter = server._get_provider_adapter(platform)
            if not adapter:
                return JSONResponse({"error": f"Provider adapter for platform '{platform}' not found or not running."}, status_code=404)
                
            method = getattr(adapter, method_name, None)
            if not method:
                return JSONResponse({"error": f"Method {method_name} not implemented for platform '{platform}'."}, status_code=501)
                
            kwargs = {k: data[k] for k in required_args if k in data}
            
            # Special cases for optional arguments
            if method_name == 'create_thread' and 'content' in data:
                kwargs['content'] = data['content']
            elif method_name == 'create_thread' and 'content' not in data:
                kwargs['content'] = ""

            result = await method(**kwargs)
            
            if isinstance(result, list):
                return {"messages": result}
            elif isinstance(result, dict):
                return result
            else:
                return {"status": "ok", "data": result}
                
        except Exception as e:
            logger.error(f"IPC Server error on {method_name}", error=str(e))
            return JSONResponse({"error": str(e)}, status_code=500)
    return handler


@router.post('/api/schedule/cron')
async def handle_schedule_cron(request: Request):
    server = request.app.state.server
    data = await request.json()
    platform = data.get("platform", "discord")
    cron_expr = data.get("cron_expr")
    prompt = data.get("prompt")
    channel_id = data.get("channel_id")
    
    if not all([cron_expr, prompt, channel_id]):
        return JSONResponse({"error": "Missing cron_expr, prompt, or channel_id"}, status_code=400)
        
    for provider in getattr(server, "providers", []):
        provider_platform = getattr(provider.config, "platform", "discord").lower()
        if provider_platform == platform.lower() and hasattr(provider, "scheduler"):
            import uuid
            from ganymede.core import ContextKey
            job_id = str(uuid.uuid4())
            context = ContextKey(platform, str(channel_id), None)
            try:
                await provider.scheduler.add_cron_job(job_id, context, "system", cron_expr, prompt)
                return {"job_id": job_id, "status": "scheduled"}
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)
                
    return JSONResponse({"error": f"Scheduler not found for platform '{platform}'."}, status_code=501)


@router.post('/api/status/update')
async def handle_status_update(request: Request):
    server = request.app.state.server
    try:
        data = await request.json()
        conversation_id = data.get("conversation_id")
        tool_name = data.get("tool_name")
        tool_args = data.get("tool_args", {})
        platform = data.get("platform", "discord")
        
        if not conversation_id or not tool_name:
            return JSONResponse({"error": "Missing conversation_id or tool_name"}, status_code=400)
            
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
                
        return {"status": "ok"}
    except Exception as e:
        logger.error("Failed to process status update request", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post('/api/test/invoke')
async def handle_test_invoke(request: Request):
    server = request.app.state.server
    """Simulate an incoming message for testing purposes."""
    try:
        data = await request.json()
        platform = data.get("platform", "discord")
        channel_id = data.get("channel_id")
        content = data.get("content")
        author_id = data.get("author_id", "test_user_id")
        author_name = data.get("author_name", "TestUser")
        
        if not channel_id or not content:
            return JSONResponse({"error": "Missing channel_id or content"}, status_code=400)
            
        adapter = server._get_provider_adapter(platform)
        if not adapter or not hasattr(adapter, "_on_message_callback") or not adapter._on_message_callback:
            return JSONResponse({"error": "Adapter missing _on_message_callback"}, status_code=500)
            
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
        return {"status": "invoked", "channel_id": channel_id}
    except Exception as e:
        logger.error("Failed to process test invoke", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)

