"""Push-to-talk client against a stand-in Core (a tiny local HTTP server). No microphone, no Blender."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ADAPTER = Path(__file__).resolve().parents[1] / "adapter"
_spec = importlib.util.spec_from_file_location("wysp_test_ui_listen", ADAPTER / "ui_listen.py")
ui_listen = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ui_listen
_spec.loader.exec_module(ui_listen)


class FakeCore(BaseHTTPRequestHandler):
    calls: list[tuple[str, str]] = []
    start_status = 200

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        self.rfile.read(int(self.headers.get("Content-Length") or 0))  # unread data aborts the socket on Windows
        FakeCore.calls.append((self.path, self.headers.get("X-Wysp-Token", "")))
        if self.path.endswith("/start") and FakeCore.start_status != 200:
            body, status = {"error": "no speech recognition configured"}, FakeCore.start_status
        elif self.path.endswith("/stop"):
            body, status = {"text": "show me the add menu", "seconds": 1.2}, 200
        else:
            body, status = {"ok": True}, 200
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args) -> None:
        pass


def _server():
    httpd = HTTPServer(("127.0.0.1", 0), FakeCore)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _poll_until(mic, pred, timeout: float = 3.0) -> list[dict]:
    got: list[dict] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        got += mic.poll()
        if pred(got):
            return got
        time.sleep(0.01)
    raise AssertionError(f"timed out; state={mic.state} got={got}")


def test_hold_and_release_returns_the_transcript() -> None:
    FakeCore.calls, FakeCore.start_status = [], 200
    httpd = _server()
    try:
        mic = ui_listen.VoiceInput(f"ws://127.0.0.1:{httpd.server_port}/ws/adapter", "tok")
        mic.start()
        assert mic.state == "starting" and mic.active
        _poll_until(mic, lambda _g: mic.state == "listening")
        mic.stop()
        assert mic.state == "transcribing"
        got = _poll_until(mic, lambda g: any(r["kind"] == "stop" for r in g))
        assert got[-1]["text"] == "show me the add menu" and mic.state == "idle"
        assert [c[0] for c in FakeCore.calls] == ["/api/listen/start", "/api/listen/stop"]
        assert all(token == "tok" for _, token in FakeCore.calls), "the pairing token goes with every request"
    finally:
        httpd.shutdown()


def test_quick_release_still_sends_once_the_microphone_opened() -> None:
    FakeCore.calls, FakeCore.start_status = [], 200
    httpd = _server()
    try:
        mic = ui_listen.VoiceInput(f"ws://127.0.0.1:{httpd.server_port}/ws/adapter", "tok")
        mic.start()
        mic.stop()  # released before the Core answered "started"
        got = _poll_until(mic, lambda g: any(r["kind"] == "stop" for r in g))
        assert got[-1]["ok"] and [c[0] for c in FakeCore.calls] == ["/api/listen/start", "/api/listen/stop"]
    finally:
        httpd.shutdown()


def test_unavailable_speech_is_reported_not_raised() -> None:
    FakeCore.calls, FakeCore.start_status = [], 503
    httpd = _server()
    try:
        mic = ui_listen.VoiceInput(f"ws://127.0.0.1:{httpd.server_port}/ws/adapter", "tok")
        mic.start()
        got = _poll_until(mic, lambda g: bool(g))
        assert got[0]["ok"] is False and "speech" in got[0]["error"] and mic.state == "error"
        mic.start()  # can try again after an error
        assert mic.state == "starting"
    finally:
        httpd.shutdown()
