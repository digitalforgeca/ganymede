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

# Setup robust structured logging
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("ganymede.cli")

def setup_logging(level_name: str):
    numeric_level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
    )
    # Bridge standard logging to structlog
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.setFormatter(logging.Formatter("%(message)s"))
    # Suppress overly verbose discord.py debug logs if we aren't in debug
    if numeric_level > logging.DEBUG:
        logging.getLogger("discord").setLevel(logging.WARNING)
        logging.getLogger("apscheduler").setLevel(logging.WARNING)

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
        
        # Write our JSON metadata to lock file
        import json
        from datetime import datetime, timezone
        lock_data = {
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "_comment": "Ganymede Lock. If this file exists without the process, the gateway crashed."
        }
        _lock_file.seek(0)
        _lock_file.truncate()
        _lock_file.write(json.dumps(lock_data) + "\n")
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
    setup_logging(config.log_level)
    logger.info("Initializing ganymede bridge", log_level=config.log_level)
    
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
        
        # Safe exit lock cleanup
        global _lock_file
        if _lock_file:
            try:
                path = _lock_file.name
                _lock_file.close()
                if os.path.exists(path):
                    os.remove(path)
                logger.info("Removed lock file on clean shutdown")
            except Exception as e:
                logger.warning("Failed to remove lock file", error=str(e))
                
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

def stop_daemon(config):
    lock_path = os.path.join(config.data_dir, "ganymede.lock")
    if not os.path.exists(lock_path):
        print(f"No lock file found at {lock_path}. Ganymede does not appear to be running.")
        return False
        
    import json
    import time
    try:
        with open(lock_path, "r") as f:
            data = json.load(f)
            pid = data.get("pid")
        if not pid:
            print("Invalid lock file format: Missing PID.")
            return False
            
        pid = int(pid)
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to Ganymede daemon (PID: {pid}). Initiating graceful shutdown...")
        
        # Wait for process to exit
        for _ in range(30):
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except OSError:
                print("Daemon shut down successfully.")
                return True
                
        print("Daemon did not shut down within 15 seconds. Escalating to SIGKILL...")
        try:
            os.kill(pid, signal.SIGKILL)
            time.sleep(1)
            # Verify the kill
            os.kill(pid, 0)
            print("Failed to SIGKILL the process.")
            return False
        except OSError:
            print("Daemon forcefully terminated.")
            if os.path.exists(lock_path):
                os.remove(lock_path)
            return True
    except ProcessLookupError:
        print(f"Ganymede daemon (PID: {pid}) is not running. Removing stale lock file.")
        os.remove(lock_path)
        return True
    except Exception as e:
        print(f"Failed to stop Ganymede: {e}")
        return False

def main():
    # Load .env file if present
    load_dotenv()
    
    parser = argparse.ArgumentParser(prog="ganymede")
    parser.add_argument("command", nargs="?", choices=["run", "mcp", "stop", "restart"], default="run", help="Subcommand to run (run, mcp, stop, restart)")
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
    
    if args.command == "stop":
        if stop_daemon(config):
            sys.exit(0)
        sys.exit(1)
        
    if args.command == "restart":
        stop_daemon(config)
        # Continue to run the daemon below
    
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
