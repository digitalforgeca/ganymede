import sys
import logging
from mcp.server.fastmcp import FastMCP

# Configure logger to output only to stderr to avoid stdout JSON-RPC corruption
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("ganymede-mcp")

# Instantiate FastMCP Server
app = FastMCP("ganymede-tools")

# Import tools so they register on the FastMCP app instance
from ganymede.mcp_server import tools
