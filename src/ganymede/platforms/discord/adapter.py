import asyncio
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
        """Generate a unique, stable conversation identifier for the given context key.
        
        NOTE: This is OUR internal naming scheme. Do not change it to satisfy SDK constraints.
        The SDK boundary layer in agent_manager.py derives a UUID from this ID.
        """
        cid = f"ganymede_discord_{context.channel_id}"
        if context.thread_id:
            cid += f"_{context.thread_id}"
        return cid

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
            content=message.content,
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

def time_ns() -> int:
    import time
    return int(time.time() * 1000000000)
