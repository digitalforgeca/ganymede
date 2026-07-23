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
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("ganymede.cli")
def setup_logging(level_name: str, log_file: str = "ganymede_live.log"):
    import logging.handlers
    numeric_level = getattr(logging, level_name.upper(), logging.INFO)
    
    # Also log to file so we can debug daemon
    import sys
    file_handler = logging.FileHandler(log_file)
    stdout_handler = logging.StreamHandler(sys.stdout)
    
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[file_handler, stdout_handler],
        level=numeric_level,
    )
    # Bridge standard logging to structlog
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
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
    
    from ganymede.core.plugin_manager import PluginManager
    import copy
    
    plugin_manager = PluginManager()

    # Factory function to create a Router and its subsystems for a config copy
    def router_factory(inst_config: AppConfig) -> Router:
        quota_tracker = QuotaTracker(inst_config)
        agent_manager = AgentManager(inst_config, quota_tracker, db=db)
        activation = ActivationManager(inst_config)
        router = Router(inst_config, agent_manager, activation, db)
        return router

    providers = []
    
    # Iterate through all configured bots
    for bot_id, bot_cfg in config.bots.items():
        try:
            bot_config_copy = copy.copy(config)
            
            # Create a clone of the agent config to override model/identity
            bot_config_copy.agent = copy.copy(config.agent)
            bot_config_copy.bot = copy.copy(config.bot)
            
            if "model" in bot_cfg:
                bot_config_copy.agent.model = bot_cfg["model"]
            if "name" in bot_cfg:
                bot_config_copy.agent.name = bot_cfg["name"]
            if "identity" in bot_cfg:
                bot_config_copy.bot.identity = bot_cfg["identity"]
            if "provider" in bot_cfg:
                bot_config_copy.bot.provider = bot_cfg["provider"]
                
            platform_name = bot_cfg.get("provider", {}).get("type", "discord").lower()
            provider_class = plugin_manager.get_provider_class(platform_name)
            
            router = router_factory(bot_config_copy)
            
            # Check if the provider class accepts bot_config in its signature
            import inspect
            sig = inspect.signature(provider_class.__init__)
            if "bot_config" in sig.parameters:
                provider = provider_class(bot_config_copy, router, db, bot_id=bot_id, bot_config=bot_cfg)
            else:
                provider = provider_class(bot_config_copy, router, db)
                provider.bot_id = bot_id
                
            providers.append(provider)
        except Exception as e:
            logger.error("Failed to load provider for bot", bot_id=bot_id, error=str(e))
            
    # Force-attach the native Web Provider if not already present
    has_web = any(p.__class__.__name__ == "WebProvider" for p in providers)
    if not has_web:
        try:
            web_provider_class = plugin_manager.get_provider_class("web")
            web_provider = web_provider_class(config, router_factory(config), db, bot_id="web-default")
            providers.append(web_provider)
        except ValueError:
            logger.warning("Web provider plugin not found, dashboard bots will be unavailable.")
    
    # Auto-register Ganymede SSE MCP server globally for agy CLI clients
    import json
    mcp_dir = os.path.expanduser("~/.gemini/mcp")
    os.makedirs(mcp_dir, exist_ok=True)
    mcp_config_path = os.path.join(mcp_dir, "ganymede.json")
    try:
        # We grab the port dynamically from the dashboard configuration
        port = getattr(config.agent, "dashboard_port", 8180)
        token = getattr(config.agent, "mcp_auth_token", "default_secure_token_123")
        # FastMCP uses the /mcp endpoint by default for SSE connections
        sse_url = f"http://127.0.0.1:{port}/mcp"
        
        with open(mcp_config_path, "w") as f:
            json.dump({
                "mcpServers": {
                    "ganymede": {
                        "type": "sse",
                        "url": sse_url,
                        "headers": {
                            "Authorization": f"Bearer {token}"
                        }
                    }
                }
            }, f, indent=2)
        logger.info("Registered Ganymede SSE MCP server globally", url=sse_url)
    except Exception as e:
        logger.warning("Failed to auto-register SSE MCP server", error=str(e))
        
    # Hook signal handling for clean exit
    loop = asyncio.get_running_loop()
    
    async def shutdown():
        logger.info("Received shutdown request, cleaning up...")
        
        async def _do_cleanup():
            if 'dashboard' in locals():
                await dashboard.stop()
            for provider in providers:
                # Do NOT call destroy_all() anymore, so tmux sessions survive gateway restarts!
                await provider.stop()
            await db.close()
            
        try:
            await asyncio.wait_for(_do_cleanup(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("Shutdown timed out after 10s. Forcing cleanup.")
            
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
        import sys
        sys.exit(0)        
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
        except ValueError:
            # Signal handlers only work in main thread, ignore if tested/spawned elsewhere
            pass
            
    # Start dashboard web server
    from ganymede.core.web import DashboardServer
    dashboard = DashboardServer(config, db)
    dashboard.providers = providers
    dashboard.web_invoke_callback = providers[-1].adapter.handle_invoke
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
    parser.add_argument("command", nargs="?", default="start", help="Action to perform: start (default), stop, restart, mcp")
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
        
        # Daemonize without explicit command parameters
        import subprocess
        print("Starting Ganymede in the background...")
        log_file = open("ganymede.log", "a")
        subprocess.Popen([sys.argv[0]], start_new_session=True, stdout=log_file, stderr=log_file)
        sys.exit(0)

    if args.command not in ("run", "start"):
        print(f"Error: Unknown command '{args.command}'.")
        parser.print_help()
        sys.exit(1)

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
    from datetime import datetime
    
    def log_print(msg, is_err=False):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if is_err:
            print(f"{timestamp} [ERROR] {msg}", file=sys.stderr)
        else:
            print(f"{timestamp} {msg}", file=sys.stdout)

    log_print("[VALIDATION] Commencing Ganymede environment validation...")
    
    # 1. Validate agy CLI
    log_print("[VALIDATION] Checking for Antigravity (agy) CLI...")
    agy_path = shutil.which("agy")
    if not agy_path:
        log_print("Fatal: The 'agy' CLI tool was not found in your PATH.", is_err=True)
        log_print("Please ensure Antigravity 2.0 is installed before running Ganymede.", is_err=True)
        sys.exit(1)
    log_print(f"[VALIDATION]  ✓ Found agy binary at: {agy_path}")
        
    # 2. Validate Chalice Plugin
    log_print("[VALIDATION] Checking for Chalice telemetry plugin...")
    plugin_path_target = os.path.expanduser("~/.gemini/config/plugins/chalice")
    plugin_path_json = os.path.join(plugin_path_target, "plugin.json")
    
    # If a broken symlink exists, remove it
    if os.path.islink(plugin_path_target) and not os.path.exists(plugin_path_target):
        os.unlink(plugin_path_target)
    elif os.path.islink(plugin_path_target):
        # Let's upgrade them from symlink to an actual copy
        os.unlink(plugin_path_target)
    
    if not os.path.exists(plugin_path_json):
        # Auto-install it via copy!
        # Find the plugin source whether running from git tree or Homebrew libexec
        possible_paths = [
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "plugins", "chalice")),
            os.path.join(sys.prefix, "plugins", "chalice"),
            os.path.join(sys.prefix, "share", "ganymede", "plugins", "chalice")
        ]
        source_chalice_path = next((p for p in possible_paths if os.path.exists(os.path.join(p, "plugin.json"))), None)
        
        if source_chalice_path:
            log_print("[VALIDATION]  - Chalice plugin not found or needs upgrade in ~/.gemini. Auto-installing...")
            os.makedirs(os.path.dirname(plugin_path_target), exist_ok=True)
            try:
                import shutil
                if os.path.exists(plugin_path_target):
                    shutil.rmtree(plugin_path_target)
                shutil.copytree(source_chalice_path, plugin_path_target)
                log_print(f"[VALIDATION]  ✓ Successfully copied Chalice plugin to {plugin_path_target}")
            except Exception as e:
                log_print(f"Fatal: Could not copy Chalice plugin: {e}", is_err=True)
                sys.exit(1)
        else:
            log_print(f"Fatal: Chalice plugin not found at {plugin_path_json}", is_err=True)
            log_print("Your installer failed to install the telemetry plugin. Ganymede cannot operate without accurate records.", is_err=True)
            sys.exit(1)
    else:
        log_print("[VALIDATION]  ✓ Chalice plugin is installed and ready.")
        
    log_print("[VALIDATION] Chain validation complete. Proceeding to boot gateway...")

if __name__ == "__main__":
    main()
