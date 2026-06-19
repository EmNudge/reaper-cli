"""FastMCP server — registers every tool module on a single MCP instance.

The list of modules lives in :data:`reaper_mcp.tools.TOOL_MODULES`. To add a
new tool module, edit that list — both this server and the CLI will pick it up.
"""

import logging

from mcp.server.fastmcp import FastMCP

from reaper_mcp.tools import register_all

logger = logging.getLogger("reaper_mcp.server")

mcp = FastMCP("reaper-mcp-unified")
register_all(mcp)
