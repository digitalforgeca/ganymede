import asyncio
import structlog
import json
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

logger = structlog.get_logger()

router = APIRouter()

@router.websocket('/ws/telemetry')
async def handle_telemetry_ws(websocket: WebSocket):
    server = websocket.app.state.server
    await websocket.accept()
    
    logger.info("Chalice plugin connected via WebSocket")
    
    try:
        while True:
            msg = await websocket.receive_text()
            try:
                data = json.loads(msg)
                logger.debug("Chalice Telemetry", payload=data)
                
                # Broadcast to all connected dashboard clients
                for client in server.dashboard_clients:
                    if client.client_state.name == "CONNECTED":
                        await client.send_json(data)
                            
                # Echo acknowledgement for 2-way sync
                await websocket.send_json({"status": "received", "event": data.get("event", "unknown")})
            except json.JSONDecodeError:
                logger.warning("Received invalid JSON from Chalice")
    except WebSocketDisconnect:
        logger.warning("WebSocket connection closed")
    finally:
        logger.info("Chalice plugin disconnected")


@router.post('/api/telemetry')
async def handle_telemetry_post(request: Request):
    server = request.app.state.server
    try:
        data = await request.json()
        logger.debug("Chalice Telemetry via POST", payload=data)
        
        # Log telemetry to database
        try:
            if hasattr(server, 'db') and server.db and server.db._conn:
                event = data.get("event", "unknown")
                model = data.get("model")
                usage = data.get("usage", {})
                tokens_prompt = usage.get("prompt_tokens", 0)
                tokens_completion = usage.get("completion_tokens", 0)
                tokens_total = usage.get("total_tokens", 0)
                latency = data.get("latency_ms")
                
                await server.db._conn.execute(
                    """
                    INSERT INTO telemetry (event_type, model, tokens_prompt, tokens_completion, tokens_total, latency_ms, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (event, model, tokens_prompt, tokens_completion, tokens_total, latency, json.dumps(data))
                )
                await server.db._conn.commit()
        except Exception as e:
            logger.error("Failed to write telemetry to database", error=str(e))
        
        # Broadcast to all connected dashboard clients
        for client in server.dashboard_clients:
            if client.client_state.name == "CONNECTED":
                await client.send_json(data)
                
        # Broadcast to internal python listeners
        for listener in getattr(server, "telemetry_listeners", []):
            asyncio.create_task(listener(data))
                
        return {"status": "received", "event": data.get("event", "unknown")}
    except json.JSONDecodeError:
        logger.warning("Received invalid JSON from Chalice POST")
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)


