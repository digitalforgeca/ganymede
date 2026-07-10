#!/usr/bin/env python3
import asyncio
import sys
import json
import logging
from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType

logging.basicConfig(level=logging.INFO, format='%(asctime)s [CHALICE] %(levelname)s: %(message)s')
logger = logging.getLogger("chalice")

GANYMEDE_WS_URL = "ws://127.0.0.1:8080/ws/telemetry"

async def read_stdin(queue: asyncio.Queue):
    """Read streaming telemetry from Antigravity via stdin and queue it."""
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    
    try:
        while not reader.at_eof():
            line = await reader.readline()
            if not line:
                break
            
            try:
                # Antigravity emits JSON events on sidecar stdin
                event = json.loads(line.decode('utf-8').strip())
                await queue.put(event)
            except json.JSONDecodeError:
                pass # Ignore malformed logs
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Error reading stdin: {e}")

async def chalice_conduit():
    queue = asyncio.Queue()
    asyncio.create_task(read_stdin(queue))
    
    async with ClientSession() as session:
        while True:
            try:
                logger.info(f"Attempting connection to Ganymede at {GANYMEDE_WS_URL}...")
                async with session.ws_connect(GANYMEDE_WS_URL) as ws:
                    logger.info("Chalice securely connected to Ganymede!")
                    
                    # Send initial handshake
                    await ws.send_json({"event": "chalice_connected", "version": "0.1.0"})
                    
                    async def send_telemetry():
                        while True:
                            event = await queue.get()
                            await ws.send_json(event)
                            queue.task_done()
                    
                    sender_task = asyncio.create_task(send_telemetry())
                    
                    # Receive feedback/commands from Ganymede
                    async for msg in ws:
                        if msg.type == WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                                if data.get("status") != "received":
                                    logger.info(f"Direct Feedback from Ganymede: {data}")
                                    # Output to stdout for Antigravity instance to process if needed
                                    print(json.dumps(data), flush=True)
                            except json.JSONDecodeError:
                                pass
                        elif msg.type == WSMsgType.CLOSED:
                            break
                        elif msg.type == WSMsgType.ERROR:
                            break
                            
                    sender_task.cancel()
                    
            except Exception as e:
                logger.warning(f"Connection to Ganymede failed: {e}. Retrying in 5s...")
                await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(chalice_conduit())
    except KeyboardInterrupt:
        logger.info("Chalice conduit shutting down.")
