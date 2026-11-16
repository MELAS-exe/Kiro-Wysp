"""`wysp mcp-bridge`: a stdio MCP server that proxies a running Core's `/mcp` endpoint.

Clients that only speak stdio (Claude Desktop, Kiro, Claude Code) can inspect the tutor through it. The bridge
adds no tool of its own: it forwards `tools/list` and `tools/call` and authenticates upstream with the pairing
token from `~/.wysp/token`. The token is never printed, logged or returned in an error.

With `read_only` (the default) only the tools in `READ_ONLY` are listed and callable; any other call is refused
here and never reaches the Core. stdout carries the protocol, so every log line goes to stderr.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

import httpx2
import mcp_types as types
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from .. import __version__
from .server import MCP_PATH, READ_ONLY

log = logging.getLogger("wysp.mcp.bridge")

DEFAULT_URL = "http://127.0.0.1:8765"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def normalize_url(url: str) -> str:
    """The `/mcp` URL of a loopback Core. Anything else is refused (the pairing token must not leave the machine)."""
    parts = urlsplit(url)
    if parts.scheme != "http" or (parts.hostname or "") not in LOOPBACK_HOSTS:
        raise ValueError("the bridge only talks to a Core on this machine (http://127.0.0.1:<port>)")
    path = parts.path.rstrip("/")
    host = f"[{parts.hostname}]" if ":" in (parts.hostname or "") else parts.hostname
    netloc = f"{host}:{parts.port}" if parts.port else str(host)
    return f"http://{netloc}{path or MCP_PATH}"


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(text=message)], is_error=True)


class Bridge:
    """The stdio-facing `Server` plus the upstream client it forwards to."""

    def __init__(self, url: str, token: str, read_only: bool = True) -> None:
        self.url = normalize_url(url)
        self._token = token
        self.read_only = read_only
        self._upstream: Client | None = None
        self.server = Server(
            "wysp-bridge",
            version=__version__,
            title="Wysp tutor (bridge)",
            instructions=(
                "Bridge to a running Wysp Core. "
                + ("Read-only: only inspection tools are available." if read_only else "All Wysp tools are available.")
            ),
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool,
        )

    @asynccontextmanager
    async def running(self):
        """Hold the upstream connection open while the bridge serves."""
        http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {self._token}"}, timeout=None)
        try:
            async with Client(streamable_http_client(self.url, http_client=http)) as client:
                self._upstream = client
                yield self
        finally:
            self._upstream = None
            await http.aclose()

    def allowed(self, name: str) -> bool:
        return not self.read_only or name in READ_ONLY

    async def _list_tools(self, ctx: Any, params: Any) -> types.ListToolsResult:
        if self._upstream is None:
            return types.ListToolsResult(tools=[])
        tools = (await self._upstream.list_tools()).tools
        return types.ListToolsResult(tools=[t for t in tools if self.allowed(t.name)])

    async def _call_tool(self, ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        if not self.allowed(params.name):
            log.warning("refused tool '%s' (read-only bridge)", params.name)
            return _error(f"'{params.name}' is not available: this bridge is read-only.")
        if self._upstream is None:
            return _error("The bridge is not connected to the Wysp Core.")
        try:
            return await self._upstream.call_tool(params.name, dict(params.arguments or {}))
        except Exception as exc:  # network and protocol errors, never tokens: only the exception type is reported
            log.warning("upstream call failed: %s", type(exc).__name__)
            return _error(
                f"The Wysp Core did not answer ({type(exc).__name__}). Is `wysp serve --llm external` running?"
            )


async def serve_stdio(url: str, token: str, read_only: bool = True) -> None:
    bridge = Bridge(url, token, read_only)
    async with bridge.running(), stdio_server() as (read, write):
        await bridge.server.run(read, write, bridge.server.create_initialization_options())
