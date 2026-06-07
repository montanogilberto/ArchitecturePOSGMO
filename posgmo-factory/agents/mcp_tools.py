"""
Shared MCP toolset factory.

All agents import get_mcp_toolset() to connect to the knowledge server.
Using StdioServerParameters so the MCP server runs as a subprocess —
no separate network service needed for local development.
"""

from __future__ import annotations

import sys
from pathlib import Path

from google.adk.tools.mcp_tool.mcp_toolset import McpToolset as MCPToolset, StdioServerParameters

# Absolute path to mcp_server/server.py
_SERVER_PATH = str(Path(__file__).parent.parent / "mcp_server" / "server.py")
_PYTHON = sys.executable


def get_mcp_toolset() -> MCPToolset:
    """Returns an MCPToolset that spawns the knowledge server via stdio."""
    return MCPToolset(
        connection_params=StdioServerParameters(
            command=_PYTHON,
            args=[_SERVER_PATH],
        )
    )
