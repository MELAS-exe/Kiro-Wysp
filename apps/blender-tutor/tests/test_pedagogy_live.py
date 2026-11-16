"""Live pedagogy check: the real Core, the real adapter in headless Blender 5.2, the Pumpkin Patch scene.

    uv run pytest -m live -o addopts="" apps/blender-tutor/tests/test_pedagogy_live.py

A Core runs in this process (external LLM mode, temp WYSP_HOME, free port) and an agent drives its
tools over the real HTTP /mcp route. The "learner" is `live_driver.py` inside Blender: it changes the
scene with plain `bpy` calls and the adapter detects and tags those changes by itself.
Properties: PED-P4 (Wysp's changes never count), PED-P5 (verified on a fresh observation).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import httpx2
import pytest
import uvicorn
import websockets
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from test_blender_live import REPO, blender_exe
from wysp_core.app import Config, create_app
from wysp_core.contract import Scope
from wysp_core.llm import ExternalLLM
from wysp_core.store import clear_registered

pytestmark = pytest.mark.live

SCENE = REPO / "apps" / "blender-tutor" / "demo" / "pumpkin.blend"
DRIVER = REPO / "apps" / "blender-tutor" / "tests" / "live_driver.py"
PUMPKIN = "blender://object/Pumpkin"
CANDLE = "blender://object/Candle"
SOLIDIFY = f"{PUMPKIN}/modifier/Solidify"
SUBDIVISION = f"{PUMPKIN}/modifier/Subdivision"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Live:
    """A Core, a Panel-like socket, an MCP agent and a headless Blender with the real adapter."""

    def __init__(self, app, port: int, ui_ws, http: httpx2.AsyncClient, cmd: Path) -> None:
        self.app, self.port, self.http, self.cmd = app, port, http, cmd
        self.session = app.state.session
        self.messages: list[dict] = []
        self._ws = ui_ws
        self._pump = asyncio.create_task(self._read())

    async def _read(self) -> None:
        with contextlib.suppress(Exception):
            async for raw in self._ws:
                self.messages.append(json.loads(raw))

    async def tool(self, name: str, **arguments) -> dict:
        # one short MCP session per call: anyio scopes must open and close in the task that uses them
        async with Client(streamable_http_client(f"http://127.0.0.1:{self.port}/mcp", http_client=self.http)) as client:
            result = await client.call_tool(name, arguments)
        return json.loads(result.content[0].text)

    async def user(self, name: str, *args) -> None:
        """The learner acts in Blender (a plain bpy change that the adapter must notice by itself)."""
        self.cmd.write_text(json.dumps({"name": name, "args": list(args)}), encoding="utf-8")
        await self.until(lambda: not self.cmd.exists(), 15)

    async def until(self, pred, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pred():
                return
            await asyncio.sleep(0.05)
        raise AssertionError(
            f"not reached in {timeout}s; last messages: {[m.get('type') for m in self.messages[-12:]]}"
        )

    def of_type(self, kind: str) -> list[dict]:
        found = [m for m in self.messages if m.get("type") == kind]
        # evidence.added also carries the postconditions of Wysp's own actions (scope "wysp_action"); only
        # exercise evidence is the learner's achievement
        return [m for m in found if m.get("scope", "exercise") == "exercise"]

    async def entities(self) -> dict[str, dict]:
        obs = await self.session.conn.observe(Scope(level="full"))
        return {e.ref: e.model_dump() for e in obs.entities}

    async def propose(self, action_id: str, params: dict, approve: bool = False) -> dict:
        task = asyncio.create_task(self.tool("propose_action", action_id=action_id, params=params, mode="do"))
        if approve:
            await self.until(lambda: self.of_type("permission.request"), 10)
            req = self.of_type("permission.request")[-1]
            await self._ws.send(
                json.dumps(
                    {
                        "type": "permission.respond",
                        "request_id": req["request_id"],
                        "decision": "approve",
                        "via": "click",
                    }
                )
            )
        return await asyncio.wait_for(task, 20)

    async def settle(self, seconds: float = 1.6) -> None:
        """Let the adapter's 0.6 s "Wysp did it" window and the Core's debounce pass."""
        await asyncio.sleep(seconds)


@pytest.fixture
async def live(tmp_path, monkeypatch):
    exe = blender_exe()
    if not SCENE.exists():
        pytest.skip("demo/pumpkin.blend is missing (run test_blender_live first)")
    monkeypatch.setenv("WYSP_HOME", str(tmp_path / "home"))
    clear_registered()
    port = _free_port()
    app = create_app(Config(port=port), ExternalLLM())
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=1)
    )
    server_task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.02)
    assert server.started

    cmd = tmp_path / "cmd.json"
    log = (tmp_path / "blender.log").open("w", encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO / ".venv" / "Lib" / "site-packages"),
        "WYSP_HOME": str(tmp_path / "home"),
    }
    blender = subprocess.Popen(
        [str(exe), "-b", "--python-use-system-env", str(SCENE), "--python", str(DRIVER), "--",
         "--url", f"ws://127.0.0.1:{port}/ws/adapter", "--token", app.state.token, "--commands", str(cmd), "--seconds", "150"],
        stdout=log, stderr=subprocess.STDOUT, env=env,
    )  # fmt: skip
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {app.state.token}"}, timeout=30)
    ui_ws = await websockets.connect(f"ws://127.0.0.1:{port}/ws/ui")
    lv = Live(app, port, ui_ws, http, cmd)
    try:
        for _ in range(600):  # Blender takes a few seconds to start
            if lv.session.conn is not None:
                break
            await asyncio.sleep(0.1)
        assert lv.session.conn is not None, (tmp_path / "blender.log").read_text(errors="replace")[-1500:]
        await asyncio.sleep(1.0)  # the watcher takes its baseline
        yield lv
    finally:
        await http.aclose()
        lv._pump.cancel()
        await ui_ws.close()
        blender.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            blender.wait(15)
        if blender.poll() is None:
            blender.kill()
        log.close()
        server.should_exit = True
        await server_task


async def test_learner_status_lists_the_three_blender_lessons(live):
    status = await live.tool("learner_status")
    assert {lesson["id"] for lesson in status["lessons"]} == {
        "blender.scene.read",
        "blender.modifiers.stack",
        "blender.modifiers.bevel",
    }
    assert status["recommended"] == "blender.scene.read"


async def test_real_observation_matches_what_the_lessons_assume(live):
    """The predicates of move_solidify_first and bevel_segments read these exact fields."""
    ents = await live.entities()
    for ref, index, kind in ((SUBDIVISION, 0, "SUBSURF"), (SOLIDIFY, 1, "SOLIDIFY")):
        e = ents[ref]
        assert e["kind"] == "modifier" and e["parent"] == PUMPKIN
        assert e["props"]["index"] == index and e["props"]["type"] == kind
    assert ents[PUMPKIN]["kind"] == "object" and ents[CANDLE]["kind"] == "object"

    await live.user("add_modifier", "Candle", "BEVEL", "Bevel")
    await live.settle(1.0)
    bevel = (await live.entities())[f"{CANDLE}/modifier/Bevel"]
    assert bevel["parent"] == CANDLE and bevel["props"]["type"] == "BEVEL"
    assert bevel["props"]["segments"] == 1  # a number, so `eq 3` compares like with like


async def test_a_learner_selection_is_verified_and_raises_mastery(live):
    before = (await live.tool("learner_status"))["skills"]["scene_navigation"]["mastery"]
    started = await live.tool("start_exercise", exercise_id="select_candle")
    assert started["ok"], started
    await live.settle(0.5)
    assert not live.of_type("evidence.added"), "nothing is verified before the learner acts"

    await live.user("select", "Candle")  # the learner clicks the Candle
    await live.until(lambda: live.of_type("evidence.added"), 12)
    ev = live.of_type("evidence.added")[-1]
    assert ev["evidence"]["type"] == "verified" and ev["evidence"]["exercise_id"] == "select_candle"
    assert ev["evidence"]["outcomes"][0]["ok"] and ev["evidence"]["observation_id"]
    after = (await live.tool("learner_status"))["skills"]["scene_navigation"]["mastery"]
    assert after > before


async def test_prop_ped_p4_a_selection_made_through_wysp_never_counts(live):
    """PED-P4: `select_object` runs through the gate (ui_state), is tagged wysp, and proves nothing."""
    before = (await live.tool("learner_status"))["skills"]["scene_navigation"]["mastery"]
    assert (await live.tool("start_exercise", exercise_id="select_candle"))["ok"]
    out = await live.propose("select_object", {"target": CANDLE})
    assert out["ok"], out
    await live.settle()
    assert not live.of_type("evidence.added")
    refused = await live.tool("check_exercise")
    assert refused["status"] == "refused" and not live.of_type("evidence.added")

    assert (await live.tool("learner_status"))["skills"]["scene_navigation"]["mastery"] == before


async def test_prop_ped_p4_a_later_user_change_does_not_credit_wysps_selection(live):
    assert (await live.tool("start_exercise", exercise_id="select_candle"))["ok"]
    assert (await live.propose("select_object", {"target": CANDLE}))["ok"]
    await live.settle()
    # the learner then does something unrelated: Wysp's earlier change must not turn into their success
    levels = (await live.entities())[SUBDIVISION]["props"]["levels"]
    await live.user("set_modifier_property", "Pumpkin", "Subdivision", "levels", levels + 1)
    await live.settle()
    assert (await live.entities())[SUBDIVISION]["props"]["levels"] == levels + 1, "the user change really happened"
    assert live.session.tutoring.engine.active.status == "active"
    assert not live.of_type("evidence.added")


async def test_prop_ped_p4_an_approved_reversible_action_never_counts(live):
    before = (await live.tool("learner_status"))["skills"]["modifier_stack"]["mastery"]
    assert (await live.tool("start_exercise", exercise_id="move_solidify_first"))["ok"]
    out = await live.propose("move_modifier", {"target": SOLIDIFY, "index": 0}, approve=True)
    assert out["ok"], out
    assert (await live.entities())[SOLIDIFY]["props"]["index"] == 0  # it really moved
    await live.settle()
    assert not live.of_type("evidence.added")
    assert (await live.tool("check_exercise"))["status"] == "refused"
    assert (await live.tool("learner_status"))["skills"]["modifier_stack"]["mastery"] == before


async def test_user_reorders_the_stack_and_the_predicate_passes_on_real_data(live):
    assert (await live.tool("start_exercise", exercise_id="move_solidify_first"))["ok"]
    await live.user("move_modifier", "Pumpkin", "Solidify", 0)
    await live.until(lambda: live.of_type("evidence.added"), 12)
    ev = live.of_type("evidence.added")[-1]["evidence"]
    assert ev["type"] == "verified" and ev["exercise_id"] == "move_solidify_first"
    assert (await live.entities())[SOLIDIFY]["props"]["index"] == 0


async def test_user_bevel_with_three_segments_passes_and_one_segment_does_not(live):
    await live.user("select", "Candle")
    await live.settle(1.0)
    started = await live.tool("start_exercise", exercise_id="bevel_segments")
    assert started["ok"], started
    await live.user("add_modifier", "Candle", "BEVEL", "Bevel")
    await live.settle(1.2)
    assert not live.of_type("evidence.added"), "a Bevel with 1 segment is not the goal"
    await live.user("set_modifier_property", "Candle", "Bevel", "segments", 3)
    await live.until(lambda: live.of_type("evidence.added"), 12)
    ev = live.of_type("evidence.added")[-1]["evidence"]
    assert ev["type"] == "verified" and ev["exercise_id"] == "bevel_segments"
    assert all(o["ok"] for o in ev["outcomes"])
