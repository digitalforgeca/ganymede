import argparse
import asyncio
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
    
    # Dynamically resolve and load active platform adapter
    platform_name = getattr(config, "platform", "discord").lower()
    
    scheduler = None
    ipc_server = None
    
    if platform_name == "discord":
        from ganymede.platforms.discord.adapter import DiscordAdapter
        from ganymede.platforms.discord.ipc_server import DiscordIPCServer
        from ganymede.core.scheduler import DiscordScheduler
        
        adapter = DiscordAdapter(config, router)
        agent_manager.set_adapter(adapter)
        adapter.register_on_message(router.handle_message)
        
        scheduler = DiscordScheduler(config, db, router)
        await scheduler.start()
        
        async def schedule_callback(cron, prompt, channel_id):
            import uuid
            job_id = str(uuid.uuid4())
            context = ContextKey("discord", channel_id, None)
            await scheduler.add_cron_job(job_id, context, "system", cron, prompt)
            return job_id

        ipc_server = DiscordIPCServer(config, adapter, schedule_callback, db=db)
        adapter.ipc_server = ipc_server
        adapter.schedule_callback = schedule_callback
    elif platform_name == "console":
        from ganymede.platforms.console.adapter import ConsoleAdapter
        
        adapter = ConsoleAdapter(config, router)
        agent_manager.set_adapter(adapter)
        adapter.register_on_message(router.handle_message)
    else:
        raise ValueError(f"Unsupported communication platform: {config.platform}")
    
    # Hook signal handling for clean exit
    loop = asyncio.get_running_loop()
    
    async def shutdown():
        logger.info("Received shutdown request, cleaning up...")
        await agent_manager.destroy_all()
        if scheduler:
            await scheduler.stop()
        await db.close()
        if ipc_server:
            await ipc_server.stop()
        await adapter.stop()
        logger.info("Shutdown completed.")
        
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
        except ValueError:
            # Signal handlers only work in main thread, ignore if tested/spawned elsewhere
            pass
            
    # Start IPC server and Bot transport
    try:
        if ipc_server:
            await ipc_server.start()
        await adapter.start()
    except Exception as e:
        logger.error("Error during bot runtime execution", error=str(e))
        await shutdown()

def main():
    # Load .env file if present
    load_dotenv()
    
    parser = argparse.ArgumentParser(prog="ganymede")
    parser.add_argument("--config", default=None, help="Path to YAML configuration file")
    parser.add_argument("--workspace", default=None, help="Target workspace path for the agent")
    parser.add_argument("--log-level", default=None, help="Logging level")
    parser.add_argument("--platform", default=None, help="Target platform (discord, console)")
    
    args = parser.parse_args()
    config = load_config(args)
    
    # Override log level from config
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, config.log_level.upper(), logging.INFO) if hasattr(logging, config.log_level.upper()) else logging.INFO
        )
    )
    
    asyncio.run(run(config))

import logging
