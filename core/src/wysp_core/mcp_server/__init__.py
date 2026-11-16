"""MCP endpoint (`/mcp`): lets an AI agent the user already runs drive the tutor through the Wysp tools."""

from .server import MCP_PATH, McpEndpoint, build_server, tool_catalog

__all__ = ["MCP_PATH", "McpEndpoint", "build_server", "tool_catalog"]
