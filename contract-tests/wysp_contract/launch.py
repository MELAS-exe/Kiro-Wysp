"""Launchers of the Contract Test Kit: start the adapter under test and hand its connection to the harness.

    command      a program from the fixture (Blender headless): {blender} {url} {token} {repo} {site_packages}
    playwright   Node driver loading the built Chrome extension in Chromium, plus the demo dashboard on a free port
    manual       prints the fixture's instructions and waits (IntelliJ: an IDE cannot be driven headlessly)
    in_process   an adapter started in this process (the mock adapter, with or without deliberate faults)

Everything a launcher starts is closed by `Launched.stop()`. Tokens are never printed and never logged: they go to
the adapter through a file (`{token_file}`) or, for Blender's command line, the throw-away token of this run only.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import shutil
import socket
import subprocess
import sysconfig
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .fixture import Fixture

REPO = Path(__file__).resolve().parents[2]
EXTENSION_ORIGIN = "chrome-extension://cnmikeniefgoeibijogfncggjkafakhk"  # fixed by the extension manifest "key"
DEFAULT_BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")
DASHBOARD_DEFAULT_SITE = "localhost:5180"  # what the web fixture says; the run uses a free port instead


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def rewrite(value: Any, old: str, new: str) -> Any:
    """Replace `old` by `new` in every string of a nested structure (the fixture names the default dashboard port)."""
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [rewrite(v, old, new) for v in value]
    if isinstance(value, dict):
        return {k: rewrite(v, old, new) for k, v in value.items()}
    return value


@dataclass
class Launched:
    stop: Callable[[], None] = lambda: None
    alive: Callable[[], str | None] = lambda: None  # None while fine, else why the adapter process ended
    substitutions: dict[str, str] = field(default_factory=dict)  # applied to the fixture's calls
    extra_origins: set[str] = field(default_factory=set)
    log: Path | None = None


def _process_alive(proc: subprocess.Popen, log: Path) -> Callable[[], str | None]:
    def alive() -> str | None:
        code = proc.poll()
        if code is None:
            return None
        tail = log.read_text(encoding="utf-8", errors="replace")[-600:] if log.exists() else ""
        return f"the adapter process exited with code {code} before connecting. Last output: {tail.strip()}"

    return alive


def _stop_process(proc: subprocess.Popen, grace: float = 8) -> None:
    if proc.poll() is None:
        proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(grace)
    if proc.poll() is None:
        proc.kill()
        with contextlib.suppress(Exception):
            proc.wait(5)


def blender_exe() -> str:
    return os.environ.get("WYSP_BLENDER") or str(DEFAULT_BLENDER)


def launch(fixture: Fixture, url: str, token: str, workdir: Path, instructions_out: Callable[[str], None]) -> Launched:
    kind = fixture.launch.kind
    values = {
        "repo": str(REPO),
        "url": url,
        "token": token,
        "token_file": str(workdir / "token"),
        "stop_file": str(workdir / "stop"),
        "site_packages": sysconfig.get_path("purelib"),
        "blender": blender_exe(),
        "node": shutil.which("node") or "node",
        "page": "",
        "page_port": "",
    }
    if kind == "manual":
        text = (fixture.launch.instructions or "").format(**values)
        instructions_out(
            f"Start {fixture.tutor} yourself and point it at {url}\n  {text}\n"
            "  The adapter authenticates with your usual pairing token (~/.wysp/token); the kit never prints it."
        )
        return Launched()
    if kind == "in_process":
        return _launch_in_process(fixture, url, token)
    substitutions: dict[str, str] = {}
    extra: set[str] = set(fixture.launch.allowed_origins)
    if kind == "playwright":
        page_port = free_port()
        values["page"] = f"http://localhost:{page_port}/"
        values["page_port"] = str(page_port)
        substitutions[DASHBOARD_DEFAULT_SITE] = f"localhost:{page_port}"
        extra.add(EXTENSION_ORIGIN)
    (workdir / "token").write_text(token, encoding="utf-8")  # read by the Node driver, never printed
    (workdir / "home").mkdir(exist_ok=True)
    log = workdir / "adapter.log"
    command = [part.format(**values) for part in fixture.launch.command]
    env = {**os.environ, "WYSP_HOME": str(workdir / "home")}  # never the user's ~/.wysp
    env.update({k: v.format(**values) for k, v in fixture.launch.env.items()})
    handle = log.open("wb")
    proc = subprocess.Popen(command, cwd=REPO, env=env, stdout=handle, stderr=subprocess.STDOUT)

    def stop() -> None:
        if kind == "playwright":  # the driver closes Chromium and the dashboard itself when this file appears
            (workdir / "stop").write_text("stop", encoding="utf-8")
            with contextlib.suppress(Exception):
                proc.wait(15)
        _stop_process(proc)
        handle.close()

    return Launched(stop, _process_alive(proc, log), substitutions, extra, log)


def _launch_in_process(fixture: Fixture, url: str, token: str) -> Launched:
    module_name, _, func_name = (fixture.launch.adapter or "").partition(":")
    start = getattr(importlib.import_module(module_name), func_name)
    stop = start(url, token, list(fixture.launch.faults))
    return Launched(stop=stop)


def temp_workdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="wysp-contract-"))


def cleanup(workdir: Path) -> None:
    shutil.rmtree(workdir, ignore_errors=True)
