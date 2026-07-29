import discord
from discord import app_commands
import structlog
from typing import Callable, Awaitable, Any
from ganymede.core import ContextKey
from ganymede.core.models import PlatformMessage
from ganymede.platforms.base import PlatformAdapter
from ganymede.platforms.discord.streamer import DiscordStreamer
from ganymede.config import AppConfig
from ganymede.platforms.discord.config import DiscordConfig

logger = structlog.get_logger()

class DiscordAdapter(discord.Client, PlatformAdapter):
    """Adapter wrapping discord.py Client to satisfy PlatformAdapter protocol."""

    def __init__(self, config: AppConfig, discord_config: DiscordConfig, router: Any):
        # Enable necessary intents for message monitoring and command registration
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True

        discord.Client.__init__(self, intents=intents)
        
        self.config = config
        self.discord_config = discord_config
        self.router = router
        self.router.set_adapter(self)
        self.tree = app_commands.CommandTree(self)
        
        self._on_message_callback: Callable[[PlatformMessage], Awaitable[None]] | None = None
        self._active_streamers: dict[str, DiscordStreamer] = {}
        self.ipc_server = None
        self.schedule_callback = None
        self._status_callback: Callable[[str, bool], None] | None = None

        from ganymede.platforms.discord.commands import setup_commands
        setup_commands(self)

    # --- PlatformAdapter Protocol Methods ---

    async def start(self) -> None:
        """Start the bot connection (non-blocking runs inside event loop)."""
        logger.info("Connecting to Discord...")
        # Since Client.start() is blocking inside the task, we run it
        await discord.Client.start(self, self.discord_config.token)

    async def stop(self) -> None:
        """Gracefully close the bot connection."""
        logger.info("Disconnecting from Discord...")
        await discord.Client.close(self)

    async def send_response(self, context: ContextKey, content: str, metadata: dict[str, Any]) -> None:
        channel = await self._resolve_channel(context)
        if not channel:
            return
        
        # Determine if we should format as an embed or text
        if metadata.get("error"):
            embed = discord.Embed(description=content, color=discord.Color.red())
            await channel.send(embed=embed)
        else:
            await channel.send(content)

    async def send_streaming_start(self, context: ContextKey, initial_text: str | None = None, persist_header: str | None = None) -> str:
        channel = await self._resolve_channel(context)
        if not channel:
            raise RuntimeError(f"Could not resolve channel {context.channel_id}")

        edit_interval = getattr(self.discord_config, "stream_edit_interval", 1.5)
        streamer = DiscordStreamer(channel, initial_text=initial_text, persist_header=persist_header, edit_interval=edit_interval)
        await streamer.start()
        
        # Generate temporary unique transaction key to identify this streamer
        stream_id = f"{context.channel_id}_{context.thread_id or ''}_{time_ns()}"
        self._active_streamers[stream_id] = streamer
        return stream_id

    async def edit_streaming(self, context: ContextKey, message_id: str, content: str) -> None:
        if streamer := self._active_streamers.get(message_id):
            await streamer.set_content(content)

    async def send_streaming_end(self, context: ContextKey, message_id: str, metadata: dict[str, Any]) -> None:
        if streamer := self._active_streamers.pop(message_id, None):
            await streamer.finish(metadata)

    async def update_streaming_status(self, context: ContextKey, status_text: str) -> None:
        prefix = f"{context.channel_id}_{context.thread_id or ''}_"
        for stream_id, streamer in list(self._active_streamers.items()):
            if stream_id.startswith(prefix):
                await streamer.set_status(status_text)
                break

    def register_on_message(self, callback: Callable[[PlatformMessage], Awaitable[None]]) -> None:
        self._on_message_callback = callback

    def register_status_callback(self, callback: Callable[[str, bool], None]) -> None:
        self._status_callback = callback

    def get_bot_namespace(self) -> str:
        # Check if namespace is explicitly configured
        if getattr(self.discord_config, "namespace", None):
            return self.discord_config.namespace
        
        # Derive from self.user.name if available, else use config.name
        bot_name = self.user.name if self.user else getattr(self.discord_config, "name", "ganymede")
        # Sanitize and lowercase
        import re
        s = bot_name.lower().strip()
        s = re.sub(r"[^a-z0-9_.-]", "", s.replace(" ", "_").replace("-", "_"))
        return s

    def get_conversation_id(self, context: ContextKey) -> str:
        return context.ganymede_conv_id

    # --- discord.py Event Handlers ---

    async def on_ready(self) -> None:
        logger.info("Bot is ready and connected", user=str(self.user), id=self.user.id)
        if self._status_callback:
            self._status_callback("discord", True)
            
        # Register and sync slash commands with Discord API
        try:
            await self.tree.sync()
            logger.info("Slash command tree synced successfully.")
        except Exception as e:
            logger.error("Failed to sync slash command tree", error=str(e))

    async def on_connect(self) -> None:
        if self._status_callback:
            self._status_callback("discord", True)
            
    async def on_resumed(self) -> None:
        if self._status_callback:
            self._status_callback("discord", True)

    async def on_disconnect(self) -> None:
        if self._status_callback:
            self._status_callback("discord", False)

        # Open DM with default developer to initialize the "home DM channel"
        try:
            elevated_users = getattr(self.config.agent, "elevated_users", [])
            if elevated_users:
                owner_id = int(elevated_users[0])
                owner_user = await self.fetch_user(owner_id)
                dm_channel = await owner_user.create_dm()
                logger.info("Initialized home DM channel with bot owner", user=owner_user.name, channel_id=dm_channel.id)
        except Exception as e:
            logger.warning("Failed to initialize home DM channel with owner", error=str(e))

    async def on_message(self, message: discord.Message) -> None:
        # Ignore own messages to prevent loop cycles
        if message.author == self.user:
            return

        # Normalize context key
        thread_id = str(message.channel.id) if isinstance(message.channel, discord.Thread) else None
        channel_id = str(message.channel.parent_id) if thread_id else str(message.channel.id)
        
        # Prevent accidental native CLI invocations typed as plain text chat (even mid-string)
        # We escape the commands with backticks so agy treats them as plain text
        import re
        pattern = r"(?<!`)(/goal|/plan|/schedule|/grill-me|/teamwork-preview|/learn|/clear)(?!`)"
        content_to_send = re.sub(pattern, r"`\1`", message.content)
        
        context = ContextKey(
            platform="discord",
            channel_id=channel_id,
            thread_id=thread_id
        )

        is_dm = message.guild is None
        mentions_us = (self.user in message.mentions) or is_dm

        normalized = PlatformMessage(
            context=context,
            author_id=str(message.author.id),
            author_name=message.author.name,
            content=content_to_send,
            is_bot=message.author.bot,
            mentions_us=mentions_us,
            attachments=[att.url for att in message.attachments],
            reply_to=str(message.reference.message_id) if message.reference else None,
            raw=message
        )

        # Route the normalized message
        if self._on_message_callback:
            await self._on_message_callback(normalized)

    # --- Helper Resolution Methods ---

    async def _resolve_channel(self, context: ContextKey) -> discord.abc.Messageable | None:
        try:
            # Check if it's a thread first
            if context.thread_id:
                channel = self.get_channel(int(context.thread_id))
                if not channel:
                    channel = await self.fetch_channel(int(context.thread_id))
                return channel

            # Fall back to parent channel
            channel = self.get_channel(int(context.channel_id))
            if not channel:
                channel = await self.fetch_channel(int(context.channel_id))
            return channel
        except Exception as e:
            logger.error("Error resolving channel from context", context=context, error=str(e))
            return None

    # --- Standard Capability Methods for SSE Tools ---

    async def get_channel_history(self, channel_id: str, limit: int) -> list[dict[str, Any]]:
        channel = await self._resolve_channel(ContextKey("discord", channel_id))
        if not channel:
            raise ValueError("Channel not found")
        history = []
        async for msg in channel.history(limit=limit):
            history.append({
                "id": str(msg.id),
                "author": msg.author.name,
                "author_id": str(msg.author.id),
                "content": msg.content,
                "created_at": msg.created_at.isoformat()
            })
        return history

    async def get_channel_info(self, channel_id: str) -> dict[str, Any]:
        channel = await self._resolve_channel(ContextKey("discord", channel_id))
        if not channel:
            raise ValueError("Channel not found")
        info = {
            "id": str(channel.id),
            "name": getattr(channel, "name", "DM"),
            "type": str(channel.type),
            "guild_id": str(channel.guild.id) if getattr(channel, "guild", None) else None
        }
        if hasattr(channel, "topic"):
            info["topic"] = channel.topic
        return info

    async def post_message(self, channel_id: str, content: str) -> dict[str, Any]:
        channel = await self._resolve_channel(ContextKey("discord", channel_id))
        if not channel:
            raise ValueError("Channel not found")
        msg = await channel.send(content)
        return {"id": str(msg.id), "status": "sent"}

    async def reply_message(self, channel_id: str, message_id: str, content: str) -> dict[str, Any]:
        channel = await self._resolve_channel(ContextKey("discord", channel_id))
        if not channel:
            raise ValueError("Channel not found")
        message = await channel.fetch_message(int(message_id))
        msg = await message.reply(content)
        return {"id": str(msg.id), "status": "replied"}

    async def edit_message(self, channel_id: str, message_id: str, content: str) -> dict[str, Any]:
        channel = await self._resolve_channel(ContextKey("discord", channel_id))
        if not channel:
            raise ValueError("Channel not found")
        message = await channel.fetch_message(int(message_id))
        if message.author.id != self.user.id:
            raise ValueError("Cannot edit messages sent by other users")
        msg = await message.edit(content=content)
        return {"id": str(msg.id), "status": "edited"}

    async def react_message(self, channel_id: str, message_id: str, emoji: str) -> dict[str, Any]:
        channel = await self._resolve_channel(ContextKey("discord", channel_id))
        if not channel:
            raise ValueError("Channel not found")
        message = await channel.fetch_message(int(message_id))
        await message.add_reaction(emoji)
        return {"status": "reacted"}

    async def get_message(self, channel_id: str, message_id: str) -> dict[str, Any]:
        channel = await self._resolve_channel(ContextKey("discord", channel_id))
        if not channel:
            raise ValueError("Channel not found")
        msg = await channel.fetch_message(int(message_id))
        return {
            "id": str(msg.id),
            "author": msg.author.name,
            "author_id": str(msg.author.id),
            "content": msg.content,
            "created_at": msg.created_at.isoformat()
        }

    async def create_thread(self, channel_id: str, name: str, content: str | None = None) -> dict[str, Any]:
        channel = await self._resolve_channel(ContextKey("discord", channel_id))
        if not channel:
            raise ValueError("Channel not found")
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Threads can only be created in Text Channels")
        thread = await channel.create_thread(name=name, auto_archive_duration=60)
        if content:
            await thread.send(content)
        return {"id": str(thread.id), "status": "created"}

    async def inject_system_instructions(self, current_prompt: str, context: ContextKey = None) -> str:
        if context is None or context.platform != "discord":
            return current_prompt

        # Multi-bot guard: only the adapter that owns this channel should respond
        try:
            channel = await self._resolve_channel(context)
            if channel and hasattr(channel, 'guild') and self.discord_config.allowed_guilds:
                if str(channel.guild.id) not in self.discord_config.allowed_guilds:
                    return current_prompt
        except Exception:
            pass

        additions = """
You can communicate using Discord tools:
- `read_channel_history`: Reads recent messages from a channel.
- `post_to_channel`: Sends a new text message.
- `create_thread`: Creates a new thread under a message.
- `get_channel_info`: Retrieves channel metadata.
For the full set of capabilities, refer to the extended tools list.
"""
        # Inject dynamic channel context
        try:
            channel = await self._resolve_channel(context)
            if channel:
                channel_name = getattr(channel, 'name', 'unknown')
                channel_id = context.channel_id
                additions += f"\nInvocation context: Discord channel #{channel_name} (ID: {channel_id})\n"

                # Get topic — for threads, fall back to the parent channel's topic
                topic = getattr(channel, 'topic', None)
                if not topic and hasattr(channel, 'parent') and channel.parent:
                    topic = getattr(channel.parent, 'topic', None)
                if topic:
                    additions += f"Channel Description: {topic}\n"
        except Exception as e:
            logger.warning("Failed to inject channel info into system prompt", error=str(e))

        return f"{current_prompt}\n\n{additions.strip()}"

def time_ns() -> int:
    import time
    return int(time.time() * 1000000000)
