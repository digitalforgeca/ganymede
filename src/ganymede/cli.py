import argparse
import asyncio
import logging
import os
import signal
import sys
import structlog
from dotenv import load_dotenv
from ganymede.config import load_config, AppConfig
from ganymede.core.quota import QuotaTracker
from ganymede.core.agent_manager import AgentManager
from ganymede.core.router import Router
from ganymede.core.activation import ActivationManager
from ganymede.core.db import Database
from ganymede.core import ContextKey

try:
    import fcntl
except ImportError:
    fcntl = None

_lock_file = None

# Setup structured logging
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

logger = structlog.get_logger()

def acquire_instance_lock(data_dir: str):
    global _lock_file
    lock_path = os.path.join(data_dir, "ganymede.lock")
    if fcntl is None:
        logger.warning("fcntl module not available; single-instance execution cannot be strictly guaranteed.")
        return

    try:
        _lock_file = open(lock_path, "a+")
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        
        # Read old PID if any to log stale locks gracefully
        _lock_file.seek(0)
        old_pid = _lock_file.read().strip()
        
        # Write our PID to lock file
        _lock_file.seek(0)
        _lock_file.truncate()
        _lock_file.write(f"{os.getpid()}\n")
        _lock_file.flush()
        
        if old_pid:
            logger.debug("Acquired single-instance lock, replacing stale PID", old_pid=old_pid, new_pid=os.getpid())
        else:
            logger.debug("Acquired single-instance lock", pid=os.getpid())
            
    except (OSError, IOError) as e:
        other_pid = "unknown"
        try:
            _lock_file.seek(0)
            pid_str = _lock_file.read().strip()
            if pid_str.isdigit():
                other_pid = pid_str
        except Exception:
            pass
            
        logger.error(
            "Another instance of ganymede is already running",
            pid=other_pid,
            lock_path=lock_path,
            error=str(e)
        )
        print(f"Error: Another instance of ganymede is already running (PID {other_pid}). Exiting.", file=sys.stderr)
        sys.exit(1)


async def dummy_schedule_callback(cron, prompt, channel_id):
    logger.info("Dummy scheduler callback triggered", cron=cron, prompt=prompt, channel_id=channel_id)
    return "dummy_job_id_123"

async def run(config: AppConfig):
    logger.info("Initializing ganymede bridge")
    
    # Initialize Database
    db = Database(config)
    await db.init()
    
    # Dynamically resolve and load active platform provider class
    platform_name = getattr(config, "platform", "discord").lower()
    from ganymede.platforms.base import get_platform_provider_class
    provider_class = get_platform_provider_class(platform_name)
    
    # Factory function to create a Router and its subsystems for a config copy
    def router_factory(inst_config: AppConfig) -> Router:
        quota_tracker = QuotaTracker(inst_config)
        agent_manager = AgentManager(inst_config, quota_tracker, db=db)
        activation = ActivationManager(inst_config)
        router = Router(inst_config, agent_manager, activation, db)
        return router

    # The platform provider class provides the runner instances
    providers = provider_class.create_providers(config, router_factory, db)
    
    # Force-attach the native Web Provider alongside any other configured platform
    from ganymede.platforms.web.provider import WebProvider
    web_provider = WebProvider(config, router_factory(config), db)
    providers.append(web_provider)
    
    # Hook signal handling for clean exit
    loop = asyncio.get_running_loop()
    
    async def shutdown():
        logger.info("Received shutdown request, cleaning up...")
        if 'dashboard' in locals():
            await dashboard.stop()
        for provider in providers:
            if provider.router and provider.router.agent_manager:
                await provider.router.agent_manager.destroy_all()
            await provider.stop()
        await db.close()
        logger.info("Shutdown completed.")
        
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
        except ValueError:
            # Signal handlers only work in main thread, ignore if tested/spawned elsewhere
            pass
            
    # Start dashboard web server
    from ganymede.core.web import DashboardServer
    dashboard = DashboardServer(config)
    dashboard.providers = providers
    await dashboard.start()
    
    # Start platform provider services concurrently
    tasks = []
    for provider in providers:
        if hasattr(provider, "adapter") and provider.adapter:
            if hasattr(provider.adapter, "register_status_callback"):
                provider.adapter.register_status_callback(dashboard.set_platform_status)
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
    
    validate_environment()
    
    # Ensure only one instance of the daemon runs at a time
    acquire_instance_lock(config.data_dir)
    
    asyncio.run(run(config))

def validate_environment():
    """Strictly validates the Antigravity ecosystem chain before booting."""
    import shutil
    
    print("[VALIDATION] Commencing Ganymede environment validation...", file=sys.stdout)
    
    # 1. Validate agy CLI
    print("[VALIDATION] Checking for Antigravity (agy) CLI...", file=sys.stdout)
    agy_path = shutil.which("agy")
    if not agy_path:
        print("[ERROR] Fatal: The 'agy' CLI tool was not found in your PATH.", file=sys.stderr)
        print("[ERROR] Please ensure Antigravity 2.0 is installed before running Ganymede.", file=sys.stderr)
        sys.exit(1)
    print(f"[VALIDATION]  ✓ Found agy binary at: {agy_path}", file=sys.stdout)
        
    # 2. Validate Chalice Plugin
    print("[VALIDATION] Checking for Chalice telemetry plugin...", file=sys.stdout)
    plugin_path_target = os.path.expanduser("~/.gemini/config/plugins/chalice")
    plugin_path_json = os.path.join(plugin_path_target, "plugin.json")
    
    if not os.path.exists(plugin_path_json):
        # Auto-install it!
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        source_chalice_path = os.path.join(repo_root, "plugins", "chalice")
        
        if os.path.exists(os.path.join(source_chalice_path, "plugin.json")):
            print("[VALIDATION]  - Chalice plugin not found in ~/.gemini. Auto-installing...", file=sys.stdout)
            os.makedirs(os.path.dirname(plugin_path_target), exist_ok=True)
            try:
                os.symlink(source_chalice_path, plugin_path_target)
                print(f"[VALIDATION]  ✓ Successfully symlinked Chalice plugin to {plugin_path_target}", file=sys.stdout)
            except Exception as e:
                print(f"[ERROR] Fatal: Could not create symlink for Chalice plugin: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"[ERROR] Fatal: Chalice plugin not found at {plugin_path_json}", file=sys.stderr)
            print("[ERROR] Your installer failed to symlink the telemetry plugin. Ganymede cannot operate without accurate records.", file=sys.stderr)
            sys.exit(1)
    else:
        print("[VALIDATION]  ✓ Chalice plugin is installed and ready.", file=sys.stdout)
        
    print("[VALIDATION] Chain validation complete. Proceeding to boot gateway...", file=sys.stdout)

if __name__ == "__main__":
    main()
