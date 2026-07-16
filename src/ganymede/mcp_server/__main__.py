import sys
import os
try:
    import fcntl
except ImportError:
    fcntl = None
from ganymede.mcp_server import app, logger

def main():
    # Enforce single MCP server instance
    lock_path = os.path.expanduser("~/.ganymede/ganymede_mcp.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    
    if fcntl:
        try:
            lock_file = open(lock_path, "a+")
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            
            # Write our PID to the lock file
            lock_file.seek(0)
            lock_file.truncate()
            lock_file.write(str(os.getpid()))
            lock_file.flush()
        except (OSError, IOError):
            logger.error("Another ganymede MCP instance is already running. Exiting to prevent database contention.")
            sys.exit(1)

    logger.info("Starting ganymede FastMCP stdio server...")
    try:
        app.run(transport="stdio")
    except Exception as e:
        logger.error(f"Fatal error running FastMCP server: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
