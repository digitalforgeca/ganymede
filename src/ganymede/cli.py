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
        
    class UglyErrorFilter(logging.Filter):
        def filter(self, record):
            if record.exc_info:
                exc_type, exc_value, _ = record.exc_info
                import asyncio
                if issubclass(exc_type, asyncio.CancelledError):
                    return False
                if record.name == "discord.client" and "Cannot connect to host" in str(exc_value):
                    record.exc_info = None
                    record.args = ()
                    record.msg = f"Network disconnected. Waiting to reconnect... ({exc_value})"
                    record.levelname = "WARNING"
                    record.levelno = logging.WARNING
            return True

    for handler in root_logger.handlers:
        handler.addFilter(UglyErrorFilter())
        
    # Also attach to specific framework loggers that might have their own handlers
    for logger_name in ["discord", "discord.client", "discord.gateway", "uvicorn", "uvicorn.error"]:
        framework_logger = logging.getLogger(logger_name)
        for handler in framework_logger.handlers:
            handler.addFilter(UglyErrorFilter())
        # If they propagate to root, root's handler will filter them too.
        
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
    from ganymede import __version__, __git_hash__
    logger.info(f"Initializing ganymede bridge v{__version__} (build: {__git_hash__})", log_level=config.log_level)
    
    # Initialize Database
    db = Database(config)
    await db.init()
    
    from ganymede.core.platform_manager import PlatformManager
    import copy
    
    platform_manager = PlatformManager()

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
            provider_class = platform_manager.get_provider_class(platform_name)
            
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
            web_provider_class = platform_manager.get_provider_class("web")
            web_provider = web_provider_class(config, router_factory(config), db, bot_id="web-default")
            providers.append(web_provider)
        except ValueError:
            logger.warning("Web provider platform not found, dashboard bots will be unavailable.")
    
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
                        },
                        "eagerTools": ["post_to_channel", "add_folder_to_project", "download_attachment"]
                    }
                }
            }, f, indent=2)
        logger.info("Registered Ganymede SSE MCP server globally", url=sse_url)
    except Exception as e:
        logger.warning("Failed to auto-register SSE MCP server", error=str(e))
        
    # Hook signal handling for clean exit
    loop = asyncio.get_running_loop()
    
    dashboard = None
    
    async def shutdown():
        logger.info("Received shutdown request, cleaning up...")
        
        async def _do_cleanup():
            if dashboard is not None:
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
    dashboard.web_invoke_callback = getattr(providers[-1].adapter, "handle_invoke", None)
    
    # Register global router telemetry listeners to ensure autonomous and subagent persistence
    for provider in providers:
        if hasattr(provider, "router") and hasattr(provider.router, "global_telemetry_listener"):
            dashboard.telemetry_listeners.append(provider.router.global_telemetry_listener)
            
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

def print_status(config):
    import json, subprocess, sqlite3, sys
    from ganymede import __version__, __git_hash__
    
    print("Ganymede Gateway Status")
    print("=======================\n")
    
    print("System Information:")
    print("-------------------")
    print(f"Ganymede Version : {__version__} (Build: {__git_hash__})")
    print(f"Python Version   : {sys.version.split(' ')[0]}")
    try:
        agy_ver = subprocess.check_output(["agy", "--version"], text=True, stderr=subprocess.DEVNULL).strip()
        print(f"Antigravity CLI  : {agy_ver}")
    except Exception:
        print("Antigravity CLI  : Not found or error")
    print("")
    
    # 1. Daemon Status
    lock_path = os.path.join(config.data_dir, "ganymede.lock")
    is_running = False
    pid = None
    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r") as f:
                data = json.load(f)
                pid = data.get("pid")
            if pid:
                os.kill(int(pid), 0)
                is_running = True
        except OSError:
            pass
        except Exception:
            pass
            
    print(f"Daemon State : {'🟢 ONLINE' if is_running else '🔴 OFFLINE'}")
    if is_running:
        print(f"Daemon PID   : {pid}")
    
    db_path = os.path.join(config.data_dir, "ganymede.db")
    if os.path.exists(db_path):
        try:
            with sqlite3.connect(db_path) as conn:
                c = conn.cursor()
                c.execute("SELECT sum(tokens_total) FROM telemetry WHERE created_at >= datetime('now', '-1 hour')")
                row = c.fetchone()
                tokens_hr = int(row[0]) if row and row[0] else 0
                print(f"Tokens (1hr) : {tokens_hr:,}")
                
                c.execute("SELECT count(*) FROM conversations WHERE role = 'assistant' AND created_at >= datetime('now', 'start of day')")
                row = c.fetchone()
                quota = int(row[0]) if row and row[0] else 0
                max_quota = getattr(config.quota, "max_requests_per_day", 18)
                print(f"Quota (Day)  : {quota} / {max_quota}")
        except Exception:
            pass
            
    print("\nActive Channels:")
    print("----------------")
    
    # Check tmux sessions
    try:
        out = subprocess.check_output(["tmux", "ls"], text=True, stderr=subprocess.DEVNULL)
        sessions = [line.split(":")[0] for line in out.splitlines() if line.startswith("ganymede-")]
        if not sessions:
            print("  No active channels.")
        else:
            for s in sessions:
                uuid_part = s.replace("ganymede-", "")
                
                brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{uuid_part}")
                tasks_dir = os.path.join(brain_dir, ".system_generated", "tasks")
                
                active_tasks = 0
                if os.path.exists(tasks_dir):
                    for f in os.listdir(tasks_dir):
                        if f.endswith(".pid"):
                            try:
                                with open(os.path.join(tasks_dir, f), "r") as pid_f:
                                    task_pid = int(pid_f.read().strip())
                                os.kill(task_pid, 0)
                                active_tasks += 1
                            except Exception:
                                pass
                                
                model = "unknown"
                model_txt = os.path.join(brain_dir, "model.txt")
                if os.path.exists(model_txt):
                    with open(model_txt, "r") as f:
                        model = f.read().strip()
                elif hasattr(config.agent, "model"):
                    model = config.agent.model
                    
                status_line = f"  • {s} | Model: {model}"
                if active_tasks > 0:
                    status_line += f" | ⚙️ {active_tasks} active tasks"
                print(status_line)
                
    except subprocess.CalledProcessError:
        print("  No active channels (tmux not running).")
    except Exception as e:
        print(f"  Error reading channels: {e}")
        
    print("")
    return True

def manage_sessions(config, action: str, targets: list[str] = None):
    """List, kill, or kill-all ganymede-managed tmux sessions."""
    import subprocess
    
    pid_map_dir = os.path.expanduser("~/.ganymede/data/pid_map")
    
    def _get_ganymede_sessions() -> list[dict]:
        try:
            out = subprocess.check_output(["tmux", "ls", "-F", "#{session_name}"], text=True, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            return []
        except FileNotFoundError:
            return []
        
        sessions = []
        for name in out.strip().splitlines():
            if not name.startswith("ganymede-"):
                continue
            info = {"name": name, "uuid": name.replace("ganymede-", "")}
            
            # Get pane PID and current command
            try:
                pane_info = subprocess.check_output(
                    ["tmux", "display-message", "-p", "-t", name, "#{pane_pid} #{pane_current_command}"],
                    text=True, stderr=subprocess.DEVNULL
                ).strip()
                parts = pane_info.split(" ", 1)
                info["pane_pid"] = parts[0]
                info["command"] = parts[1] if len(parts) > 1 else "unknown"
            except Exception:
                info["pane_pid"] = "?"
                info["command"] = "?"
            
            # Resolve conversation ID from PID map
            map_file = os.path.join(pid_map_dir, info["pane_pid"])
            if os.path.exists(map_file):
                try:
                    with open(map_file) as f:
                        info["conv_id"] = f.read().strip()
                except Exception:
                    info["conv_id"] = None
            else:
                info["conv_id"] = None
            
            sessions.append(info)
        return sessions
    
    def _kill_session(session: dict):
        name = session["name"]
        try:
            subprocess.run(["tmux", "kill-session", "-t", name], check=True, capture_output=True)
            print(f"  ✅ Killed session: {name}")
        except Exception as e:
            print(f"  ❌ Failed to kill {name}: {e}")
        
        # Clean up PID map
        if session.get("pane_pid") and session["pane_pid"] != "?":
            map_file = os.path.join(pid_map_dir, session["pane_pid"])
            try:
                os.remove(map_file)
            except FileNotFoundError:
                pass
    
    sessions = _get_ganymede_sessions()
    
    if action == "list":
        if not sessions:
            print("No active Ganymede sessions.")
            return
        print(f"Active Ganymede Sessions ({len(sessions)})")
        print("=" * 60)
        for s in sessions:
            conv_label = s['conv_id'] or '(no PID map)'
            print(f"  {s['name']}")
            print(f"    PID: {s['pane_pid']}  Command: {s['command']}")
            print(f"    Conv: {conv_label}")
        print()
        
    elif action == "kill":
        if not sessions:
            print("No active Ganymede sessions to kill.")
            return
        
        # "all" is the only accepted kill-all keyword.
        # Do NOT accept "*" — the shell expands it to every file in the CWD
        # before we ever see it, so we'd get dozens of bogus targets.
        kill_all = not targets or (len(targets) == 1 and targets[0].lower() == "all")
        
        if kill_all:
            if not targets:
                # No args — confirm with user
                print(f"This will kill all {len(sessions)} Ganymede session(s).")
                confirm = input("Are you sure? [y/N] ").strip().lower()
                if confirm not in ("y", "yes"):
                    print("Aborted.")
                    return
            
            print(f"Killing all {len(sessions)} Ganymede session(s)...")
            for s in sessions:
                _kill_session(s)
            print(f"\nDone. All sessions terminated.")
        else:
            matched = []
            unmatched = []
            for target in targets:
                for s in sessions:
                    if target in (s["name"], s["uuid"], s.get("conv_id", "")):
                        matched.append(s)
                        break
                else:
                    unmatched.append(target)
            
            # Detect shell glob expansion: many unmatched targets that look like filenames
            if len(unmatched) > 3 and not matched:
                print(f"  ⚠️  None of the {len(unmatched)} provided targets matched any Ganymede session.")
                print(f"  💡 It looks like your shell expanded a glob (e.g. '*').")
                print(f"     Use: ganymede sessions kill all")
                return
            
            for t in unmatched:
                print(f"  ⚠️  No session found matching: {t}")
            
            if matched:
                for s in matched:
                    _kill_session(s)
                print(f"\nKilled {len(matched)} session(s).")
    else:
        print(f"Error: Unknown sessions action '{action}'.")
        print("  Available actions: list, kill")
        sys.exit(1)

def main():
    # Load .env file if present
    load_dotenv()
    
    parser = argparse.ArgumentParser(prog="ganymede")
    parser.add_argument("command", nargs="?", default="start", help="Action to perform: start (default), stop, restart, status, sessions, mcp")
    parser.add_argument("subargs", nargs="*", help="Sub-arguments for commands like 'sessions kill <name>'")
    parser.add_argument("--config", default=None, help="Path to YAML configuration file")
    parser.add_argument("--workspace", default=None, help="Target workspace path for the agent")
    parser.add_argument("--model", default=None, help="Force a specific model string, bypassing any config mappings")
    parser.add_argument("--log-level", default=None, help="Logging level")
    parser.add_argument("--platform", default=None, help="Target platform (discord, console)")
    
    args = parser.parse_args()
    
    if args.command == "mcp":
        from ganymede.mcp_server.__main__ import main as mcp_main
        mcp_main()
        return
        
    config = load_config(args)
    
    if args.command == "sessions":
        action = args.subargs[0] if args.subargs else "list"
        targets = args.subargs[1:] if len(args.subargs) > 1 else []
        manage_sessions(config, action, targets)
        sys.exit(0)
    
    if args.command == "stop":
        if stop_daemon(config):
            sys.exit(0)
        sys.exit(1)
        
    if args.command == "status":
        print_status(config)
        sys.exit(0)
        
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
    
    broadcast_script = os.path.join(plugin_path_target, "scripts", "broadcast.py")
    if not os.path.exists(plugin_path_json) or os.path.getsize(plugin_path_json) == 0:
        needs_install = True
    else:
        needs_install = False
    
    # Also force reinstall if broadcast.py is missing or empty (corrupted install)
    if not needs_install:
        if not os.path.exists(broadcast_script) or os.path.getsize(broadcast_script) == 0:
            log_print("[VALIDATION]  ⚠ Chalice plugin exists but broadcast.py is missing or empty. Re-installing...")
            needs_install = True
    
    if needs_install:
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
                import shutil, json
                if os.path.exists(plugin_path_target):
                    shutil.rmtree(plugin_path_target)
                shutil.copytree(source_chalice_path, plugin_path_target)
                
                # Rewrite hooks.json to use absolute paths since agy does not expand ~
                target_hooks = os.path.join(plugin_path_target, "hooks.json")
                if os.path.exists(target_hooks):
                    with open(target_hooks, "r") as f:
                        hooks_data = f.read()
                    home_dir = os.path.expanduser("~")
                    hooks_data = hooks_data.replace("~/.gemini", f"{home_dir}/.gemini")
                    with open(target_hooks, "w") as f:
                        f.write(hooks_data)
                        
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
        
    # Ensure import_manifest.json knows about the hooks
    manifest_path = os.path.expanduser("~/.gemini/config/import_manifest.json")
    if os.path.exists(manifest_path):
        try:
            import json
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
            
            updated = False
            for plugin in manifest.get("imports", []):
                if plugin.get("name") == "chalice":
                    if not plugin.get("components") or "hooks" not in plugin["components"]:
                        plugin["components"] = ["hooks"]
                        updated = True
            
            if updated:
                with open(manifest_path, "w") as f:
                    json.dump(manifest, f, indent=2)
                log_print("[VALIDATION]  - Patched Antigravity manifest for Chalice hooks")
        except Exception as e:
            log_print(f"[VALIDATION]  - Failed to patch manifest: {e}", is_err=True)
            
    log_print("[VALIDATION] Chain validation complete. Proceeding to boot gateway...")

if __name__ == "__main__":
    main()
