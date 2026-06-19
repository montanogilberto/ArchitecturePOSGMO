"""
Shared MCP toolset factory.

All agents import get_mcp_toolset() to connect to the knowledge server.
Using StdioServerParameters so the MCP server runs as a subprocess —
no separate network service needed for local development.

A single MCPToolset instance is shared across all agents so only ONE
subprocess of the MCP server is spawned per factory run instead of one
per agent (which was causing 10+ duplicate server starts in the logs).
"""

from __future__ import annotations

import sys
from pathlib import Path

from google.adk.tools.mcp_tool.mcp_toolset import McpToolset as MCPToolset, StdioServerParameters

# Absolute path to mcp_server/server.py
_SERVER_PATH = str(Path(__file__).parent.parent / "mcp_server" / "server.py")
_PYTHON = sys.executable

# Singleton — created once at import time, shared by all agents.
_MCP_TOOLSET: MCPToolset | None = None


def get_mcp_toolset() -> MCPToolset:
    """Returns the shared MCPToolset singleton (one subprocess for the whole run)."""
    global _MCP_TOOLSET
    if _MCP_TOOLSET is None:
        _MCP_TOOLSET = MCPToolset(
            connection_params=StdioServerParameters(
                command=_PYTHON,
                args=[_SERVER_PATH],
            )
        )
    return _MCP_TOOLSET
