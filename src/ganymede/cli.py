import argparse
import asyncio
import copy
import logging
import os
import signal
import structlog
from dotenv import load_dotenv
from ganymede.config import load_config, AppConfig
from ganymede.core.quota import QuotaTracker
from ganymede.core.agent_manager import AgentManager
from ganymede.core.router import Router
from ganymede.core.activation import ActivationManager
from ganymede.core.db import Database
from ganymede.core import ContextKey

# Setup structured logging
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

logger = structlog.get_logger()

async def dummy_schedule_callback(cron, prompt, channel_id):
    logger.info("Dummy scheduler callback triggered", cron=cron, prompt=prompt, channel_id=channel_id)
    return "dummy_job_id_123"

async def run(config: AppConfig):
    logger.info("Initializing ganymede bridge")
    
    # Initialize Database
    db = Database(config)
    await db.init()
    
    # Dynamically resolve and load active platform provider
    platform_name = getattr(config, "platform", "discord").lower()
    
    # Check if there are multiple bots configured under discord
    instances = []
    if platform_name == "discord":
        discord_raw = config.platforms.get("discord", {})
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
                instances.append(bot_config)
        else:
            instances.append(config)
    else:
        instances.append(config)
        
    runners = []
    for inst_config in instances:
        # Initialize Core subsystems
        quota_tracker = QuotaTracker(inst_config)
        agent_manager = AgentManager(inst_config, quota_tracker, db=db)
        activation = ActivationManager(inst_config)
        
        # Initialize Router
        router = Router(inst_config, agent_manager, activation, db)
        
        if platform_name == "discord":
            from ganymede.platforms.discord.provider import DiscordPlatformProvider
            provider = DiscordPlatformProvider(inst_config, router, db)
        elif platform_name == "console":
            from ganymede.platforms.console.provider import ConsolePlatformProvider
            provider = ConsolePlatformProvider(inst_config, router, db)
        else:
            raise ValueError(f"Unsupported communication platform: {config.platform}")

        agent_manager.set_adapter(provider.adapter)
        runners.append((agent_manager, provider))
    
    # Hook signal handling for clean exit
    loop = asyncio.get_running_loop()
    
    async def shutdown():
        logger.info("Received shutdown request, cleaning up...")
        for agent_manager, provider in runners:
            await agent_manager.destroy_all()
            await provider.stop()
        await db.close()
        logger.info("Shutdown completed.")
        
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
        except ValueError:
            # Signal handlers only work in main thread, ignore if tested/spawned elsewhere
            pass
            
    # Start platform provider services concurrently
    tasks = []
    for agent_manager, provider in runners:
        tasks.append(provider.start())
        
    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        logger.error("Error during platform execution", error=str(e))
        await shutdown()

def main():
    # Load .env file if present
    load_dotenv()
    
    parser = argparse.ArgumentParser(prog="ganymede")
    parser.add_argument("command", nargs="?", choices=["run", "mcp"], default="run", help="Subcommand to run (run, mcp)")
    parser.add_argument("--config", default=None, help="Path to YAML configuration file")
    parser.add_argument("--workspace", default=None, help="Target workspace path for the agent")
    parser.add_argument("--log-level", default=None, help="Logging level")
    parser.add_argument("--platform", default=None, help="Target platform (discord, console)")
    
    args = parser.parse_args()
    
    if args.command == "mcp":
        from ganymede.mcp_server.__main__ import main as mcp_main
        mcp_main()
        return
        
    config = load_config(args)
    
    # Override log level from config
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, config.log_level.upper(), logging.INFO) if hasattr(logging, config.log_level.upper()) else logging.INFO
        )
    )
    
    asyncio.run(run(config))

if __name__ == "__main__":
    main()
