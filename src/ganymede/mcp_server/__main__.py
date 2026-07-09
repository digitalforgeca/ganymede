import sys
from ganymede.mcp_server import app, logger

def main():
    logger.info("Starting ganymede FastMCP stdio server...")
    try:
        app.run(transport="stdio")
    except Exception as e:
        logger.error(f"Fatal error running FastMCP server: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
