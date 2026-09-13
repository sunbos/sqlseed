"""MCP server package for sqlseed."""

from __future__ import annotations

from mcp_server_sqlseed.server import mcp


def main() -> None:
    """Run the MCP server."""
    mcp.run()
