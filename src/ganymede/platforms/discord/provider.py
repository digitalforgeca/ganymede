import uuid
from typing import Any
from ganymede.platforms.base import BasePlatformProvider
from ganymede.platforms.discord.adapter import DiscordAdapter
from ganymede.platforms.discord.ipc_server import DiscordIPCServer
from ganymede.core.scheduler import DiscordScheduler
from ganymede.core import ContextKey

from ganymede.platforms.discord.config import DiscordConfig

class DiscordPlatformProvider(BasePlatformProvider):
    """Platform provider for Discord. Manages the Discord client adapter, scheduler, and local IPC server."""
    
    def __init__(self, config: Any, router: Any, db: Any):
        super().__init__(config, router, db)
        
        raw_discord = config.platforms.get("discord", {})
        if isinstance(raw_discord, dict):
            self.discord_config = DiscordConfig(
                token=raw_discord.get("token", ""),
                allowed_guilds=raw_discord.get("allowed_guilds", []),
                name=raw_discord.get("name", "ganymede"),
                namespace=raw_discord.get("namespace")
            )
        else:
            self.discord_config = raw_discord

        self.adapter = DiscordAdapter(config, self.discord_config, router)
        self.scheduler = DiscordScheduler(config, db, router)

        async def schedule_callback(cron, prompt, channel_id):
            job_id = str(uuid.uuid4())
            context = ContextKey("discord", channel_id, None)
            await self.scheduler.add_cron_job(job_id, context, "system", cron, prompt)
            return job_id

        self.ipc_server = DiscordIPCServer(config, self.adapter, schedule_callback, db=db)
        self.adapter.ipc_server = self.ipc_server
        self.adapter.schedule_callback = schedule_callback

    async def start(self) -> None:
        """Start all services for Discord integration."""
        self.router.register_on_message = self.adapter.register_on_message
        self.adapter.register_on_message(self.router.handle_message)
        
        await self.scheduler.start()
        await self.ipc_server.start()
        await self.adapter.start()

    async def stop(self) -> None:
        """Gracefully stop all Discord services."""
        if self.scheduler:
            await self.scheduler.stop()
        if self.ipc_server:
            await self.ipc_server.stop()
        await self.adapter.stop()
