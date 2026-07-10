import os
import asyncio
from typing import Any
import discord
import structlog
from aiohttp import web
from ganymede.config import AppConfig

logger = structlog.get_logger()

class DiscordIPCServer:
    """Hosts local HTTP server in sidecar to handle tool execution requests from the stdio MCP server."""

    def __init__(self, config: AppConfig, client: discord.Client, schedule_callback: Any = None, db: Any = None):
        self.config = config
        self.client = client
        self.schedule_callback = schedule_callback
        self.db = db
        self.app = web.Application()
        self.runner = None
        self.port_file_path = os.path.join(config.data_dir, "rpc_port.txt")
        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_get("/api/ping", self.handle_ping)
        self.app.router.add_post("/api/channel/history", self.handle_channel_history)
        self.app.router.add_post("/api/channel/info", self.handle_channel_info)
        self.app.router.add_post("/api/message/post", self.handle_message_post)
        self.app.router.add_post("/api/message/reply", self.handle_message_reply)
        self.app.router.add_post("/api/message/edit", self.handle_message_edit)
        self.app.router.add_post("/api/message/react", self.handle_message_react)
        self.app.router.add_post("/api/message/get", self.handle_message_get)
        self.app.router.add_post("/api/thread/create", self.handle_thread_create)
        self.app.router.add_post("/api/schedule/cron", self.handle_schedule_cron)
        self.app.router.add_post("/api/status/update", self.handle_status_update)

    async def start(self) -> None:
        """Launch the local web server on a dynamic port and write port to file."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        
        # Start on port 0 to bind to a random free local port
        site = web.TCPSite(self.runner, "localhost", 0)
        await site.start()
        
        # Retrieve the assigned port
        port = self.runner.addresses[0][1]
        self.port = port
        logger.info("Local HTTP IPC Server started", host="localhost", port=port)

        # Write port to data directory so the stdio MCP server can read it
        try:
            with open(self.port_file_path, "w") as f:
                f.write(str(port))
            logger.debug("Wrote active port to config path", path=self.port_file_path)
        except Exception as e:
            logger.error("Failed to write active port to file", path=self.port_file_path, error=str(e))

    async def stop(self) -> None:
        """Stop the server and clean up port file."""
        if self.runner:
            await self.runner.cleanup()
            logger.info("Local HTTP IPC Server stopped.")
        
        if os.path.exists(self.port_file_path):
            try:
                os.remove(self.port_file_path)
                logger.debug("Cleaned up active port file")
            except Exception as e:
                logger.error("Failed to delete port file", path=self.port_file_path, error=str(e))

    # --- HTTP Handler Endpoints ---

    async def handle_ping(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "bot_user": str(self.client.user)})

    async def handle_channel_history(self, request: web.Request) -> web.Response:
        data = await request.json()
        channel_id = await self._resolve_channel_id(data)
        limit = min(int(data.get("limit", 50)), 100)

        if not channel_id:
            return web.json_response({"error": "Missing channel_id or conversation_id"}, status=400)

        try:
            channel = await self._resolve_messageable(channel_id)
            if not channel:
                return web.json_response({"error": "Channel not found"}, status=404)

            history = []
            async for msg in channel.history(limit=limit):
                history.append({
                    "id": str(msg.id),
                    "author": msg.author.name,
                    "author_id": str(msg.author.id),
                    "content": msg.content,
                    "created_at": msg.created_at.isoformat()
                })
            
            return web.json_response({"messages": history})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_channel_info(self, request: web.Request) -> web.Response:
        data = await request.json()
        channel_id = await self._resolve_channel_id(data)

        if not channel_id:
            return web.json_response({"error": "Missing channel_id or conversation_id"}, status=400)

        try:
            channel = self.client.get_channel(int(channel_id))
            if not channel:
                channel = await self.client.fetch_channel(int(channel_id))
            
            info = {
                "id": str(channel.id),
                "name": getattr(channel, "name", "DM"),
                "type": str(channel.type),
                "guild_id": str(channel.guild.id) if getattr(channel, "guild", None) else None
            }
            if hasattr(channel, "topic"):
                info["topic"] = channel.topic

            return web.json_response(info)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_message_post(self, request: web.Request) -> web.Response:
        data = await request.json()
        channel_id = await self._resolve_channel_id(data)
        content = data.get("content")

        if not channel_id or not content:
            return web.json_response({"error": "Missing channel_id/conversation_id or content"}, status=400)

        try:
            channel = await self._resolve_messageable(channel_id)
            if not channel:
                return web.json_response({"error": "Channel not found"}, status=404)

            msg = await channel.send(content)
            return web.json_response({"id": str(msg.id), "status": "sent"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_thread_create(self, request: web.Request) -> web.Response:
        data = await request.json()
        channel_id = await self._resolve_channel_id(data)
        name = data.get("name")
        content = data.get("content")

        if not channel_id or not name:
            return web.json_response({"error": "Missing channel_id/conversation_id or name"}, status=400)

        try:
            channel = self.client.get_channel(int(channel_id))
            if not channel:
                channel = await self.client.fetch_channel(int(channel_id))
            
            if not isinstance(channel, discord.TextChannel):
                return web.json_response({"error": "Threads can only be created in Text Channels"}, status=400)

            # Create thread
            thread = await channel.create_thread(name=name, auto_archive_duration=60)
            if content:
                await thread.send(content)

            return web.json_response({"id": str(thread.id), "status": "created"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_message_reply(self, request: web.Request) -> web.Response:
        data = await request.json()
        channel_id = await self._resolve_channel_id(data)
        message_id = data.get("message_id")
        content = data.get("content")

        if not channel_id or not message_id or not content:
            return web.json_response({"error": "Missing channel_id/conversation_id, message_id, or content"}, status=400)

        try:
            channel = await self._resolve_messageable(channel_id)
            if not channel:
                return web.json_response({"error": "Channel not found"}, status=404)

            message = await channel.fetch_message(int(message_id))
            msg = await message.reply(content)
            return web.json_response({"id": str(msg.id), "status": "replied"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_message_edit(self, request: web.Request) -> web.Response:
        data = await request.json()
        channel_id = await self._resolve_channel_id(data)
        message_id = data.get("message_id")
        content = data.get("content")

        if not channel_id or not message_id or not content:
            return web.json_response({"error": "Missing channel_id/conversation_id, message_id, or content"}, status=400)

        try:
            channel = await self._resolve_messageable(channel_id)
            if not channel:
                return web.json_response({"error": "Channel not found"}, status=404)

            message = await channel.fetch_message(int(message_id))
            if message.author.id != self.client.user.id:
                return web.json_response({"error": "Cannot edit messages sent by other users"}, status=403)

            msg = await message.edit(content=content)
            return web.json_response({"id": str(msg.id), "status": "edited"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_message_react(self, request: web.Request) -> web.Response:
        data = await request.json()
        channel_id = await self._resolve_channel_id(data)
        message_id = data.get("message_id")
        emoji = data.get("emoji")

        if not channel_id or not message_id or not emoji:
            return web.json_response({"error": "Missing channel_id/conversation_id, message_id, or emoji"}, status=400)

        try:
            channel = await self._resolve_messageable(channel_id)
            if not channel:
                return web.json_response({"error": "Channel not found"}, status=404)

            message = await channel.fetch_message(int(message_id))
            await message.add_reaction(emoji)
            return web.json_response({"status": "reacted"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_message_get(self, request: web.Request) -> web.Response:
        data = await request.json()
        channel_id = await self._resolve_channel_id(data)
        message_id = data.get("message_id")

        if not channel_id or not message_id:
            return web.json_response({"error": "Missing channel_id/conversation_id or message_id"}, status=400)

        try:
            channel = await self._resolve_messageable(channel_id)
            if not channel:
                return web.json_response({"error": "Channel not found"}, status=404)

            msg = await channel.fetch_message(int(message_id))
            return web.json_response({
                "id": str(msg.id),
                "author": msg.author.name,
                "author_id": str(msg.author.id),
                "content": msg.content,
                "created_at": msg.created_at.isoformat()
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_schedule_cron(self, request: web.Request) -> web.Response:
        data = await request.json()
        cron_expr = data.get("cron_expr")
        prompt = data.get("prompt")
        channel_id = await self._resolve_channel_id(data)

        if not cron_expr or not prompt or not channel_id:
            return web.json_response({"error": "Missing cron_expr, prompt, or channel_id/conversation_id"}, status=400)

        try:
            if self.schedule_callback:
                job_id = await self.schedule_callback(cron_expr, prompt, channel_id)
                return web.json_response({"job_id": job_id, "status": "scheduled"})
            else:
                return web.json_response({"error": "Scheduler callback not registered on sidecar"}, status=501)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _resolve_channel_id(self, data: dict) -> str | None:
        channel_id = data.get("channel_id")
        if channel_id:
            return str(channel_id)
        
        conversation_id = data.get("conversation_id")
        # Map conversation ID back to network context
        contexts = await self.db.get_conversation_contexts(conversation_id)
        if not contexts:
            logger.warning("Received event for unknown conversation", conversation_id=conversation_id)
            return None
            
        for context in contexts:
            return context.channel_id
        return None

    async def _resolve_messageable(self, cid: str) -> discord.abc.Messageable | None:
        try:
            channel = self.client.get_channel(int(cid))
            if not channel:
                channel = await self.client.fetch_channel(int(cid))
            return channel
        except Exception as e:
            logger.error("Failed resolving messageable channel", id=cid, error=str(e))
            return None

    async def handle_status_update(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            conversation_id = data.get("conversation_id")
            tool_name = data.get("tool_name")
            tool_args = data.get("tool_args", {})
            
            if not conversation_id or not tool_name:
                return web.json_response({"error": "Missing conversation_id or tool_name"}, status=400)
                
            context = None
            if self.db:
                contexts = await self.db.get_conversation_contexts(conversation_id)
                if contexts:
                    context = contexts[0]
                
            if not context:
                # Fallback pattern matching for channel ID in friendly name
                import re
                match = re.search(r"_(\d{17,20})$", conversation_id)
                if match:
                    channel_id = match.group(1)
                    context = ContextKey("discord", channel_id, None)
                    
            if context and self.client:
                from ganymede.core.status import format_tool_status
                status_text = format_tool_status(tool_name, tool_args)
                
                if hasattr(self.client, "update_streaming_status"):
                    await self.client.update_streaming_status(context, status_text)
                    
            return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error("Failed to process status update request", error=str(e))
            return web.json_response({"error": str(e)}, status=500)
