"""`wysp mcp-bridge`: stdio-side MCP server proxying a running Core's /mcp.

A second in-process Core (external mode, temp WYSP_HOME, free port) is the upstream. No model is called."""

from __future__ import annotations

import asyncio
import json
import logging
import socket

import pytest
import uvicorn
from mcp.client import Client
from wysp_core.app import Config, create_app
from wysp_core.llm import ExternalLLM
from wysp_core.mcp_server.bridge import Bridge, normalize_url
from wysp_core.mcp_server.server import READ_ONLY, tool_catalog
from wysp_core.orchestrator.tools import ToolBox
from wysp_core.store import clear_registered


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def core(tmp_path, monkeypatch):
    monkeypatch.setenv("WYSP_HOME", str(tmp_path))
    clear_registered()
    port = _free_port()
    app = create_app(Config(port=port), ExternalLLM())
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=1)
    )
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.02)
    assert server.started
    yield port, app.state.token
    server.should_exit = True
    await task


async def _bridge(core, read_only: bool = True):
    port, token = core
    return Bridge(f"http://127.0.0.1:{port}", token, read_only)


async def test_bridge_lists_only_read_only_tools(core):
    bridge = await _bridge(core)
    async with bridge.running(), Client(bridge.server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert names == READ_ONLY
    assert not {"propose_action", "narrate", "highlight"} & names


async def test_bridge_without_read_only_lists_the_whole_catalog(core):
    bridge = await _bridge(core, read_only=False)
    async with bridge.running(), Client(bridge.server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert names == {t.name for t in tool_catalog()}


async def test_prop_bridge_read_only_never_forwards_a_non_read_only_tool(core, monkeypatch):
    """A propose_action / narrate / any other tool call is refused by the bridge and never reaches the Core."""
    reached: list[str] = []
    real = ToolBox.call

    async def spy(self, name, args):
        reached.append(name)
        return await real(self, name, args)

    monkeypatch.setattr(ToolBox, "call", spy)
    bridge = await _bridge(core)
    forbidden = [t.name for t in tool_catalog() if t.name not in READ_ONLY]
    assert {"propose_action", "narrate"} <= set(forbidden)
    async with bridge.running(), Client(bridge.server) as client:
        for name in [*forbidden, "no_such_tool"]:
            result = await client.call_tool(name, {})
            assert result.is_error is True, name
            assert "read-only" in result.content[0].text
    assert reached == []


async def test_bridge_forwards_read_only_calls_with_the_token(core):
    bridge = await _bridge(core)
    async with bridge.running(), Client(bridge.server) as client:
        result = await client.call_tool("get_tutor_context", {})
    payload = json.loads(result.content[0].text)
    assert result.is_error is False and payload["ok"] and "narrate" in payload["context"]


async def test_bridge_with_a_wrong_token_fails_without_leaking_it(core, caplog):
    port, _ = core
    secret = "wrong-token-for-test-1234"
    bridge = Bridge(f"http://127.0.0.1:{port}", secret)
    caplog.set_level(logging.DEBUG)
    try:
        async with bridge.running(), Client(bridge.server) as client:
            result = await client.call_tool("get_tutor_context", {})
            text = result.content[0].text if result.content else ""
            assert result.is_error is True
            assert secret not in text
    except Exception as exc:  # the upstream handshake may be refused outright
        assert secret not in str(exc)
    assert secret not in caplog.text


async def test_bridge_reports_a_core_that_is_not_running(tmp_path):
    bridge = Bridge(f"http://127.0.0.1:{_free_port()}", "t")
    bridge._upstream = None  # not connected
    async with Client(bridge.server) as client:
        assert (await client.list_tools()).tools == []
        result = await client.call_tool("observe", {})
    assert result.is_error is True


@pytest.mark.parametrize(
    "url", ["http://evil.example:8765", "https://127.0.0.1:8765", "http://192.168.1.5:8765", "ftp://localhost"]
)
def test_bridge_refuses_a_non_loopback_url(url):
    with pytest.raises(ValueError):
        normalize_url(url)


def test_normalize_url_adds_the_mcp_path():
    assert normalize_url("http://127.0.0.1:8765") == "http://127.0.0.1:8765/mcp"
    assert normalize_url("http://localhost:9000/") == "http://localhost:9000/mcp"
    assert normalize_url("http://127.0.0.1:8765/mcp") == "http://127.0.0.1:8765/mcp"
