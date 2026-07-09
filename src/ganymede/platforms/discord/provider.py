import uuid
from typing import Any, Callable
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

    @classmethod
    def create_providers(cls, config: Any, router_factory: Callable[[Any], Any], db: Any) -> list[BasePlatformProvider]:
        import copy
        discord_raw = config.platforms.get("discord", {})
        instances = []
        
        if isinstance(discord_raw, dict) and "bots" in discord_raw:
            for bot_raw in discord_raw["bots"]:
                bot_config = copy.deepcopy(config)
                bot_config.platforms["discord"] = {
                    "token": bot_raw.get("token", ""),
                    "allowed_guilds": bot_raw.get("allowed_guilds", []),
                    "name": bot_raw.get("name", "ganymede"),
                    "namespace": bot_raw.get("namespace"),
                }
                if "agent" in bot_raw:
                    agent_overrides = bot_raw["agent"]
                    bot_config.agent.system_instructions = agent_overrides.get("system_instructions", bot_config.agent.system_instructions)
                    bot_config.agent.workspace = agent_overrides.get("workspace", bot_config.agent.workspace)
                    if "capabilities" in agent_overrides:
                        bot_config.agent.capabilities.update(agent_overrides["capabilities"])
                    bot_config.agent.idle_timeout_minutes = agent_overrides.get("idle_timeout_minutes", bot_config.agent.idle_timeout_minutes)
                    bot_config.agent.max_contexts = agent_overrides.get("max_contexts", bot_config.agent.max_contexts)
                    bot_config.agent.status_verbosity = agent_overrides.get("status_verbosity", bot_config.agent.status_verbosity)
                    bot_config.agent.require_approval = agent_overrides.get("require_approval", bot_config.agent.require_approval)
                    bot_config.agent.elevated_users = agent_overrides.get("elevated_users", bot_config.agent.elevated_users)
                    bot_config.agent.auto_approve_tools = agent_overrides.get("auto_approve_tools", bot_config.agent.auto_approve_tools)
                    bot_config.agent.mission_statement = agent_overrides.get("mission_statement", bot_config.agent.mission_statement)
                
                router = router_factory(bot_config)
                provider = cls(bot_config, router, db)
                instances.append(provider)
        else:
            router = router_factory(config)
            provider = cls(config, router, db)
            instances.append(provider)
            
        return instances
