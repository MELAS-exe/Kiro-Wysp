"""Online contract run for a tutor whose fixture says `launch.kind: playwright` (the web tutor).

    uv run --no-sync python contract-tests/launchers/playwright_launcher.py --tutor web-tutor

The `wysp-contract` command line has no online harness yet (adapter-contract task 9, owner A), so this script is
the launcher: it starts a throw-away Core (temp WYSP_HOME, free port), a copy of the demo dashboard on a free port
(never 5180), and the Playwright driver that loads the built extension in Chromium. When the adapter has connected
it runs the kit's observation checks (CON-P2, P3, P7, P10), the fixture's dry-run calls (no state change) and its
invalid calls (expected error codes). Everything it starts is closed at the end. Exit code 0 means all green.

Needs `npm.cmd run build -w apps/web-tutor/extension` first. The extension's Origin must be allowed by the Core:
this script sets WYSP_ALLOWED_ORIGINS for its own Core only.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from wysp_contract.checks import Finding, run_observation_checks
from wysp_core.app import Config, create_app
from wysp_core.contract import Scope, WyspError
from wysp_core.llm import ExternalLLM
from wysp_core.store import clear_registered

REPO = Path(__file__).resolve().parents[2]
EXTENSION_ORIGIN = "chrome-extension://cnmikeniefgoeibijogfncggjkafakhk"  # fixed by the manifest "key"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def rewrite(value, old: str, new: str):
    """The fixture names the dashboard on its default port; the run uses a free one."""
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [rewrite(v, old, new) for v in value]
    if isinstance(value, dict):
        return {k: rewrite(v, old, new) for k, v in value.items()}
    return value


async def run(tutor: str, timeout: float) -> int:
    fixture = yaml.safe_load((REPO / "apps" / tutor / "contract.fixture.yaml").read_text(encoding="utf-8"))
    launch = fixture["launch"]
    if launch.get("kind") != "playwright":
        print(f"{tutor}: launch.kind is {launch.get('kind')!r}, not 'playwright'", file=sys.stderr)
        return 2
    home = Path(tempfile.mkdtemp(prefix="wysp-contract-"))
    os.environ["WYSP_HOME"] = str(home / "home")
    os.environ["WYSP_ALLOWED_ORIGINS"] = EXTENSION_ORIGIN
    clear_registered()
    import uvicorn

    port, page_port = free_port(), free_port()
    app = create_app(Config(port=port), ExternalLLM())
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=1)
    )
    server_task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.02)
    token_file = home / "token"
    token_file.write_text(app.state.token, encoding="utf-8")
    values = {
        "repo": str(REPO),
        "url": f"ws://127.0.0.1:{port}/ws/adapter",
        "token_file": str(token_file),
        "page": f"http://localhost:{page_port}/",
        "page_port": str(page_port),
        "node": shutil.which("node") or "node",
    }
    values["stop_file"] = str(home / "stop")
    command = [str(part).format(**values) for part in launch["command"]]
    driver = subprocess.Popen(command, cwd=REPO, stdout=subprocess.DEVNULL)
    findings: list[Finding] = []
    try:
        conn = None
        for _ in range(int(timeout * 5)):
            conn = app.state.session.conn
            if conn is not None:
                break
            await asyncio.sleep(0.2)
        if conn is None:
            print("the adapter did not connect in time", file=sys.stderr)
            return 1
        loop = asyncio.get_running_loop()
        site = f"localhost:{page_port}"
        calls = rewrite(fixture.get("safe_calls", []), "localhost:5180", site)
        invalid = rewrite(fixture.get("invalid_calls", []), "localhost:5180", site)
        dry = rewrite(fixture.get("dry_run_calls", []), "localhost:5180", site)
        for _ in range(100):  # the content script reads the page once it is open
            obs = await conn.observe(Scope(level="full"))
            if len(obs.entities) >= fixture["expect"]["min_entities"]:
                break
            await asyncio.sleep(0.2)

        def request(method: str, params: dict):
            return asyncio.run_coroutine_threadsafe(conn.call(method, params), loop).result(30)

        findings += await asyncio.to_thread(run_observation_checks, request, conn.manifest, calls)
        findings += await asyncio.to_thread(dry_and_invalid, request, dry, invalid)
        got = {a.id for a in await conn.get_actions()}
        want = set(fixture["expect"]["actions"])
        findings.append(
            Finding("action_catalog", got == want, f"missing {sorted(want - got)}, extra {sorted(got - want)}")
        )
    finally:
        (home / "stop").write_text("stop", encoding="utf-8")  # the driver closes Chromium and the dashboard itself
        with contextlib.suppress(Exception):
            driver.wait(15)
        if driver.poll() is None:
            driver.kill()
        await asyncio.sleep(0.5)
        server.should_exit = True
        with contextlib.suppress(Exception):
            await server_task
        shutil.rmtree(home, ignore_errors=True)
    for f in findings:
        print(f, file=sys.stderr if not f.ok else sys.stdout)
    return 0 if findings and all(f.ok for f in findings) else 1


def dry_and_invalid(request, dry: list[dict], invalid: list[dict]) -> list[Finding]:
    out: list[Finding] = []
    digest_of = lambda: json.dumps(request("adapter.observe", {"scope": {"level": "full"}})["entities"], sort_keys=True)  # noqa: E731
    for call in dry:
        try:
            before = digest_of()
            result = request(
                "adapter.execute", {"call": {"action_id": call["action_id"], "params": call["params"], "dry_run": True}}
            )
            ok = digest_of() == before and result.get("status") in ("ok", "preview")
            out.append(Finding(f"dry_run {call['action_id']}", ok, "" if ok else "state changed or bad status"))
        except WyspError as exc:
            out.append(Finding(f"dry_run {call['action_id']}", False, str(exc)))
    for call in invalid:
        try:
            request("adapter.execute", {"call": {"action_id": call["action_id"], "params": call.get("params", {})}})
            out.append(Finding(f"invalid {call['action_id']}", False, "no error"))
        except WyspError as exc:
            ok = int(exc.code) == call["expect_error"]
            out.append(
                Finding(
                    f"invalid {call['action_id']}",
                    ok,
                    "" if ok else f"got {int(exc.code)}, wanted {call['expect_error']}",
                )
            )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(prog="playwright_launcher")
    parser.add_argument("--tutor", default="web-tutor")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    return asyncio.run(run(args.tutor, args.timeout))


if __name__ == "__main__":
    sys.exit(main())
