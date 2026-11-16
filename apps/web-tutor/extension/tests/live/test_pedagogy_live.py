"""Live pedagogy check of the web tutor: a real Core, the real extension in Chromium (Playwright), the demo dashboard.

    uv run --no-sync pytest -m live -o addopts="" -p no:cacheprovider apps/web-tutor/extension/tests/live/test_pedagogy_live.py

Needs `npm.cmd run build -w apps/web-tutor/extension` first and the Chromium that Playwright installs.
A second Core runs in this process (temp WYSP_HOME, free port, external LLM mode); the dashboard is served on
a free port (never 5180, which may be the user's), so the lesson refs are rewritten into a temp copy of the
profile. The "learner" is `playwright_driver.mjs`: real mouse and keyboard input, so every event is trusted.
Properties: WEB-P5 (origin tagging), PED-P4 (Wysp's changes never count), PED-P5 (verified on a fresh observation).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import random
import shutil
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
from wysp_core.app import Config, create_app
from wysp_core.contract import Scope
from wysp_core.llm import ExternalLLM
from wysp_core.store import clear_registered

pytestmark = pytest.mark.live

REPO = Path(__file__).resolve().parents[5]
TUTOR = REPO / "apps" / "web-tutor"
EXT = TUTOR / "extension"
EXTENSION_ORIGIN = "chrome-extension://cnmikeniefgoeibijogfncggjkafakhk"  # fixed by the manifest "key"
NODE = shutil.which("node") or "node"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Live:
    def __init__(self, app, port: int, dash_port: int, ui_ws, http, cmd: Path) -> None:
        self.app, self.port, self.http, self.cmd = app, port, http, cmd
        self.dash = f"web://localhost:{dash_port}"
        self.session = app.state.session
        self.messages: list[dict] = []
        self.raw: list[dict] = []  # adapter events as the extension sent them (origin untouched by the Core)
        self._ws = ui_ws
        self._pump = asyncio.create_task(self._read())
        self.session.bus.subscribe(self._on_event, "adapter.event")

    async def _on_event(self, event: dict) -> None:
        self.raw.append({"name": event["name"], "data": event["data"], "t": time.monotonic()})

    async def _read(self) -> None:
        with contextlib.suppress(Exception):
            async for raw in self._ws:
                self.messages.append(json.loads(raw))

    def ref(self, path: str) -> str:
        return f"{self.dash}/{path}"

    @property
    def region(self) -> str:
        return self.ref("region~filters/combobox~region")

    async def tool(self, name: str, **arguments) -> dict:
        async with Client(streamable_http_client(f"http://127.0.0.1:{self.port}/mcp", http_client=self.http)) as client:
            result = await client.call_tool(name, arguments)
        return json.loads(result.content[0].text)

    async def user(self, name: str, *args):
        """The learner acts in the browser with real input; returns what the driver reports."""
        out_file = Path(f"{self.cmd}.out")
        out_file.unlink(missing_ok=True)
        staging = Path(f"{self.cmd}.tmp")  # write then rename, so the driver never reads half a file
        staging.write_text(json.dumps({"name": name, "args": list(args)}), encoding="utf-8")
        os.replace(staging, self.cmd)
        await self.until(lambda: not self.cmd.exists() and out_file.exists(), 20)
        out = json.loads(out_file.read_text(encoding="utf-8"))
        assert out["ok"], out
        return out["value"]

    async def until(self, pred, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pred():
                return
            await asyncio.sleep(0.05)
        raise AssertionError(f"not reached in {timeout}s; last: {[m.get('type') for m in self.messages[-12:]]}")

    def of_type(self, kind: str) -> list[dict]:
        return [m for m in self.messages if m.get("type") == kind and m.get("scope", "exercise") == "exercise"]

    async def observe(self):
        return await self.session.conn.observe(Scope(level="full"))

    async def entities(self) -> dict[str, dict]:
        return {e.ref: e.model_dump() for e in (await self.observe()).entities}

    async def propose(self, action_id: str, params: dict, approve: bool = False) -> dict:
        before = len(self.of_type("permission.request"))
        task = asyncio.create_task(self.tool("propose_action", action_id=action_id, params=params, mode="do"))
        if approve:
            await self.until(lambda: len(self.of_type("permission.request")) > before, 10)
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
        await asyncio.sleep(seconds)


def _profile_copy(dest: Path, dash_port: int) -> Path:
    """The lessons name the dashboard by its refs (localhost:5180); the test dashboard is on another port."""
    root = dest / "apps"
    target = root / "web-tutor" / "profile"
    shutil.copytree(TUTOR / "profile", target)
    for f in target.rglob("*.yaml"):
        f.write_text(
            f.read_text(encoding="utf-8").replace("localhost:5180", f"localhost:{dash_port}"), encoding="utf-8"
        )
    return root


@pytest.fixture
async def live(tmp_path, monkeypatch):
    if not (EXT / "dist" / "manifest.json").exists():
        pytest.skip("build the extension first: npm.cmd run build -w apps/web-tutor/extension")
    monkeypatch.setenv("WYSP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("WYSP_ALLOWED_ORIGINS", EXTENSION_ORIGIN)
    clear_registered()
    port, dash_port = _free_port(), _free_port()
    app = create_app(Config(port=port, profile_roots=[_profile_copy(tmp_path, dash_port)]), ExternalLLM())
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=1)
    )
    server_task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.02)
    assert server.started

    dash = subprocess.Popen(
        [NODE, "serve.mjs"], cwd=TUTOR / "demo-dashboard", env={**os.environ, "PORT": str(dash_port)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    token_file = tmp_path / "token"
    token_file.write_text(app.state.token, encoding="utf-8")
    cmd = tmp_path / "cmd.json"
    log = (tmp_path / "driver.log").open("w", encoding="utf-8")
    driver = subprocess.Popen(
        [NODE, str(EXT / "tests" / "live" / "playwright_driver.mjs"), "--core", f"ws://127.0.0.1:{port}/ws/adapter",
         "--token-file", str(token_file), "--page", f"http://localhost:{dash_port}/", "--commands", str(cmd),
         "--seconds", "170"],
        cwd=EXT, stdout=log, stderr=subprocess.STDOUT,
    )  # fmt: skip
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {app.state.token}"}, timeout=30)
    ui_ws = await websockets.connect(f"ws://127.0.0.1:{port}/ws/ui")
    lv = Live(app, port, dash_port, ui_ws, http, cmd)
    try:
        for _ in range(400):
            if lv.session.conn is not None:
                break
            await asyncio.sleep(0.1)
        assert lv.session.conn is not None, (tmp_path / "driver.log").read_text(errors="replace")[-1500:]
        for _ in range(100):  # the content script is registered and the page is read once the page is open
            obs = await lv.observe()
            if any(e.ref == lv.region for e in obs.entities):
                break
            await asyncio.sleep(0.2)
        else:
            raise AssertionError(
                "the dashboard was not read: " + (tmp_path / "driver.log").read_text(errors="replace")[-800:]
            )
        await asyncio.sleep(0.8)  # the content script takes its baseline
        yield lv
    finally:
        await http.aclose()
        lv._pump.cancel()
        await ui_ws.close()
        with contextlib.suppress(Exception):
            cmd.write_text(json.dumps({"name": "quit"}), encoding="utf-8")
        for proc in (driver, dash):
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(8)
            if proc.poll() is None:
                proc.kill()
        log.close()
        await asyncio.sleep(0.5)  # let the extension's socket close before the server shuts down
        server.should_exit = True
        with contextlib.suppress(Exception):  # uvicorn can race a socket that is already closing
            await server_task


async def test_learner_status_lists_the_web_lessons(live):
    status = await live.tool("learner_status")
    ids = {lesson["id"] for lesson in status["lessons"]}
    assert {"web-tutor.dashboard.tour", "web-tutor.filters.region", "web-tutor.reports.create"} <= ids
    assert status["recommended"] == "web-tutor.dashboard.tour"


async def test_real_observation_matches_what_the_lessons_assume(live):
    """The predicates read these exact refs and props."""
    ents = await live.entities()
    region = ents[live.region]
    assert region["kind"] == "control" and region["props"]["value"] == "All regions"
    table = next(e for e in ents.values() if e["kind"] == "table")
    assert table["props"]["row_count"] > 0 and len(table["props"]["rows"][0]) == 4


async def test_focus_and_selection_only_changes_advance_state_version(live):
    """The Blender adapter's bug: a pure selection change did not advance state_version."""
    v0 = (await live.observe()).state_version
    await live.user("click_region")
    await live.settle(1.0)
    obs = await live.observe()
    assert obs.state_version > v0
    assert live.region in obs.focus, obs.focus


async def test_a_real_click_on_the_region_filter_is_verified(live):
    before = (await live.tool("learner_status"))["skills"]["dashboard_reading"]["mastery"]
    started = await live.tool("start_exercise", exercise_id="find_region_filter")
    assert started["ok"], started
    await live.settle(0.5)
    assert not live.of_type("evidence.added"), "nothing is verified before the learner acts"
    await live.user("click_region")
    await live.until(lambda: live.of_type("evidence.added"), 12)
    ev = live.of_type("evidence.added")[-1]["evidence"]
    assert ev["type"] == "verified" and ev["exercise_id"] == "find_region_filter"
    assert (await live.tool("learner_status"))["skills"]["dashboard_reading"]["mastery"] > before


async def test_transylvania_fails_with_another_region_then_passes(live):
    assert (await live.tool("start_exercise", exercise_id="show_only_transylvania"))["ok"]
    await live.user("select_region", "Salem")
    await live.settle(1.5)
    assert await live.user("region_value") == "Salem"
    assert not live.of_type("evidence.added"), "Salem is the wrong region"
    assert live.session.tutoring.engine.active.status == "active"
    await live.user("select_region", "Transylvania")
    await live.until(lambda: live.of_type("evidence.added"), 12)
    ev = live.of_type("evidence.added")[-1]["evidence"]
    assert ev["type"] == "verified" and ev["exercise_id"] == "show_only_transylvania"
    assert all(o["ok"] for o in ev["outcomes"])


async def test_prop_ped_p4_a_select_option_through_the_gate_never_counts(live):
    assert (await live.tool("start_exercise", exercise_id="show_only_transylvania"))["ok"]
    out = await live.propose("select_option", {"target": live.region, "option": "Transylvania"}, approve=True)
    assert out["ok"], out
    assert await live.user("region_value") == "Transylvania"  # it really changed
    await live.settle(2.0)
    assert not live.of_type("evidence.added")
    assert (await live.tool("check_exercise"))["status"] == "refused"
    assert not live.of_type("evidence.added")


async def test_prop_web_p5_origin_tagging_over_random_interleavings(live):
    """WEB-P5: events caused by Wysp's actions are tagged wysp, events from real user input are tagged user."""
    rng = random.Random(5)
    regions = ["Salem", "Bayou", "Sleepy Hollow", "Transylvania"]
    steps = ["user_select", "wysp_select", "user_click", "wysp_checked"]
    seen = {"user": 0, "wysp": 0}
    checked = True
    for _ in range(6):
        step = rng.choice(steps)
        mark = len(live.raw)
        if step == "user_select":
            await live.user("select_region", rng.choice(regions))
            expect = "user"
        elif step == "user_click":
            await live.user("click_region")
            expect = "user"
        elif step == "wysp_select":
            current = await live.user("region_value")
            option = rng.choice([r for r in regions if r != current])
            out = await live.propose("select_option", {"target": live.region, "option": option}, approve=True)
            assert out["ok"], out
            expect = "wysp"
        else:
            checked = not checked
            out = await live.propose(
                "set_checked", {"target": live.ref("region~filters/checkbox~potions"), "checked": checked}, approve=True
            )
            assert out["ok"], out
            expect = "wysp"
        await live.settle(1.8)
        tagged = [e["data"].get("origin") for e in live.raw[mark:] if e["name"] in ("state_changed", "user_action")]
        assert tagged, f"{step}: no event reached the Core"
        assert set(tagged) == {expect}, f"{step}: expected only {expect}, got {tagged}"
        seen[expect] += len(tagged)
    assert seen["user"] and seen["wysp"], f"the random sequence must exercise both origins: {seen}"


async def _save_report(live, fmt: str, tick_orders: bool = True) -> None:
    """The learner fills in and saves the dialog with real clicks and key presses."""
    await live.user("click", "#open-report")
    await live.user("type_into", "#report-name", "Weekly Revenue")
    if tick_orders:  # the dialog keeps the ticks of the previous save
        await live.user("click", 'input[name="metric"][value="Orders"]')
    await live.user("click", f'input[name="format"][value="{fmt}"]')
    await live.user("click", "#save")


async def test_the_report_predicate_sees_the_saved_list_and_the_status(live):
    ents = await live.entities()
    assert ents[live.ref("region~saved-reports/list~saved-reports")]["props"]["items"] == []
    await _save_report(live, "CSV")
    await live.settle(1.2)
    ents = await live.entities()
    assert ents[live.ref("region~saved-reports/list~saved-reports")]["props"]["items"] == [
        "Weekly Revenue (Revenue, Orders; CSV)"
    ]
    assert next(e for e in ents.values() if e["kind"] == "status")["props"]["text"] == "Report saved: Weekly Revenue"


async def test_a_report_saved_by_the_learner_is_verified_and_a_wrong_format_is_not(live):
    before = (await live.tool("learner_status"))["skills"]["report_creation"]["mastery"]
    assert (await live.tool("start_exercise", exercise_id="save_weekly_report"))["ok"]
    await _save_report(live, "PDF")  # right name and metrics, wrong format
    await live.settle(1.8)
    assert not live.of_type("evidence.added"), "a PDF report is not the goal"
    assert live.session.tutoring.engine.active.status == "active"
    await _save_report(live, "CSV", tick_orders=False)
    await live.until(lambda: live.of_type("evidence.added"), 12)
    ev = live.of_type("evidence.added")[-1]["evidence"]
    assert ev["type"] == "verified" and ev["exercise_id"] == "save_weekly_report"
    assert all(o["ok"] for o in ev["outcomes"])
    assert (await live.tool("learner_status"))["skills"]["report_creation"]["mastery"] > before


async def test_prop_ped_p4_a_report_saved_through_wysp_never_counts(live):
    assert (await live.tool("start_exercise", exercise_id="save_weekly_report"))["ok"]
    await live.user("click", "#open-report")  # the learner only opens the dialog
    name = live.ref("dialog~create-report/textbox~report-name")
    assert (await live.propose("fill_field", {"target": name, "value": "Weekly Revenue"}, approve=True))["ok"]
    assert (
        await live.propose(
            "set_checked", {"target": live.ref("dialog~create-report/checkbox~orders"), "checked": True}, approve=True
        )
    )["ok"]
    assert (await live.propose("click_element", {"target": live.ref("dialog~create-report/radio~csv")}, approve=True))[
        "ok"
    ]
    out = await live.propose("click_element", {"target": live.ref("dialog~create-report/button~save")}, approve=True)
    assert out["ok"], out
    await live.settle(2.0)
    assert (await live.user("reports")) == ["Weekly Revenue (Revenue, Orders; CSV)"]  # it really saved
    assert not live.of_type("evidence.added")
    assert (await live.tool("check_exercise"))["status"] == "refused"
