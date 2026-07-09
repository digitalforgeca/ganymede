import argparse
import asyncio
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
    
    # Initialize Core subsystems
    quota_tracker = QuotaTracker(config)
    agent_manager = AgentManager(config, quota_tracker, db=db)
    activation = ActivationManager(config)
    
    # Initialize Router
    router = Router(config, agent_manager, activation, db)
    
    # Dynamically resolve and load active platform provider
    platform_name = getattr(config, "platform", "discord").lower()
    
    if platform_name == "discord":
        from ganymede.platforms.discord.provider import DiscordPlatformProvider
        provider = DiscordPlatformProvider(config, router, db)
    elif platform_name == "console":
        from ganymede.platforms.console.provider import ConsolePlatformProvider
        provider = ConsolePlatformProvider(config, router, db)
    else:
        raise ValueError(f"Unsupported communication platform: {config.platform}")

    agent_manager.set_adapter(provider.adapter)
    
    # Hook signal handling for clean exit
    loop = asyncio.get_running_loop()
    
    async def shutdown():
        logger.info("Received shutdown request, cleaning up...")
        await agent_manager.destroy_all()
        await db.close()
        await provider.stop()
        logger.info("Shutdown completed.")
        
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
        except ValueError:
            # Signal handlers only work in main thread, ignore if tested/spawned elsewhere
            pass
            
    # Start platform provider services
    try:
        await provider.start()
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
