import os
import asyncio
import structlog
import json
import yaml
from aiohttp import web
from ganymede.config import AppConfig
from ganymede.core import ContextKey

logger = structlog.get_logger()

async def handle_telemetry_ws(server, request):
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
                    for client in server.dashboard_clients:
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


async def handle_telemetry_post(server, request):
    try:
        data = await request.json()
        logger.debug("Chalice Telemetry via POST", payload=data)
        
        # Log telemetry to disk
        try:
            log_dir = os.path.join(server.config.data_dir, "telemetry")
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, "telemetry.jsonl")
            with open(log_file, "a") as f:
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error("Failed to write telemetry to disk", error=str(e))
        
        # Broadcast to all connected dashboard clients
        for client in server.dashboard_clients:
            if not client.closed:
                await client.send_json(data)
                
        # Broadcast to internal python listeners
        for listener in getattr(server, "telemetry_listeners", []):
            asyncio.create_task(listener(data))
                
        return web.json_response({"status": "received", "event": data.get("event", "unknown")})
    except json.JSONDecodeError:
        logger.warning("Received invalid JSON from Chalice POST")
        return web.json_response({"error": "Invalid JSON"}, status=400)


