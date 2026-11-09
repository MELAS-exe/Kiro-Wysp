"""Fixtures: a real Core (uvicorn, in-process) + the mock adapter + a Panel-like WebSocket client."""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import pytest
import uvicorn
import websockets
from wysp_core.app import Config, create_app
from wysp_core.llm import ScriptedLLM
from wysp_core.store import clear_registered
from wysp_mock.cli import start_mock


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class UiClient:
    """Plays the Panel: collects every Core message, sends Panel messages."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.messages: list[dict[str, Any]] = []
        self._task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        with contextlib.suppress(Exception):
            async for raw in self.ws:
                self.messages.append(json.loads(raw))

    async def send(self, **msg: Any) -> None:
        await self.ws.send(json.dumps(msg))

    async def wait_for(
        self, pred: Callable[[dict[str, Any]], bool], timeout: float = 8.0, start: int = 0
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for m in self.messages[start:]:
                if pred(m):
                    return m
            await asyncio.sleep(0.02)
        types = [m.get("type") for m in self.messages[start:]]
        raise AssertionError(f"timeout waiting for message; got types: {types}")

    def of_type(self, type_: str) -> list[dict[str, Any]]:
        return [m for m in self.messages if m.get("type") == type_]

    async def close(self) -> None:
        self._task.cancel()
        await self.ws.close()


@dataclass
class Stack:
    port: int
    app: Any
    session: Any
    mock: Any
    client: Any
    ui: UiClient
    llm: ScriptedLLM

    @property
    def audit(self):
        return self.session.audit.records


async def _start_stack(
    tmp_path, monkeypatch, steps: list[dict[str, Any]], connect_mock: bool = True
) -> tuple[Stack, Callable[[], Awaitable[None]]]:
    monkeypatch.setenv("WYSP_HOME", str(tmp_path))
    clear_registered()
    port = free_port()
    llm = ScriptedLLM(steps)
    app = create_app(Config(port=port), llm)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=1)
    )
    server_task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.02)
    assert server.started, "uvicorn did not start"

    mock = client = None
    if connect_mock:
        mock, client = start_mock(f"ws://127.0.0.1:{port}/ws/adapter", app.state.token)
        for _ in range(200):
            if client.connected:
                break
            await asyncio.sleep(0.02)
        assert client.connected, f"mock adapter did not connect: {client.last_error}"
    ws = await websockets.connect(f"ws://127.0.0.1:{port}/ws/ui")
    ui = UiClient(ws)
    # wait until the Panel has the initial state and the adapter is listed
    if connect_mock:
        await ui.wait_for(lambda m: m.get("type") == "adapters.list" and bool(m["adapters"]))
    stack = Stack(port, app, app.state.session, mock, client, ui, llm)

    async def stop() -> None:
        await ui.close()
        if client:
            await asyncio.to_thread(client.stop)  # joins a thread: must not block the loop that serves the Core
        server.should_exit = True
        await server_task

    return stack, stop


@pytest.fixture
async def make_stack(tmp_path, monkeypatch):
    """Factory fixture: `stack = await make_stack(scripted_steps)`. Everything is stopped afterwards."""
    stops: list[Callable[[], Awaitable[None]]] = []

    async def factory(steps: list[dict[str, Any]], connect_mock: bool = True) -> Stack:
        stack, stop = await _start_stack(tmp_path, monkeypatch, steps, connect_mock)
        stops.append(stop)
        return stack

    yield factory
    for stop in reversed(stops):
        await stop()
