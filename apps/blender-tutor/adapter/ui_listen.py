"""Push-to-talk from Blender: the Core records and transcribes (``POST /api/listen/{start,stop,cancel}``).

Blender's Python API cannot capture audio, so the local Core does it and this module only says when to start
and stop. Requests run on short-lived threads (Blender never freezes while Whisper works); the result is
picked up on the main thread with ``poll()``. The pairing token authorises turning the microphone on.
"""

from __future__ import annotations

import json
import queue
import threading
import urllib.error
import urllib.request
from typing import Any


def core_base(adapter_url: str) -> str:
    base = adapter_url.rsplit("/ws/", 1)[0] if "/ws/" in adapter_url else adapter_url.rstrip("/")
    if base.startswith("wss://"):
        return "https://" + base[len("wss://") :]
    if base.startswith("ws://"):
        return "http://" + base[len("ws://") :]
    return base


class VoiceInput:
    """States: idle -> starting -> listening -> transcribing -> idle (or error)."""

    def __init__(self, adapter_url: str, token: str) -> None:
        self.base = core_base(adapter_url)
        self._token = token
        self.state = "idle"
        self.last_error: str | None = None
        self._results: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stop_requested = False

    # ------------------------------------------------------------------ network
    def _post(self, path: str, timeout: float) -> dict[str, Any]:
        req = urllib.request.Request(
            self.base + path, data=b"{}", headers={"Content-Type": "application/json", "X-Wysp-Token": self._token}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - the local Core only
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                message = json.loads(exc.read().decode("utf-8")).get("error", "")
            except (ValueError, OSError):
                message = ""
            raise RuntimeError(message or f"the Core answered {exc.code}") from exc

    def _run(self, kind: str, path: str, timeout: float) -> None:
        def work() -> None:
            try:
                self._results.put({"kind": kind, "ok": True, **self._post(path, timeout)})
            except Exception as exc:  # noqa: BLE001 - reported in the chat, never raised in Blender
                self._results.put({"kind": kind, "ok": False, "error": str(exc)[:160] or type(exc).__name__})

        threading.Thread(target=work, name=f"wysp-listen-{kind}", daemon=True).start()

    # ------------------------------------------------------------------ main-thread API
    @property
    def active(self) -> bool:
        return self.state in ("starting", "listening")

    def start(self) -> None:
        if self.state != "idle" and self.state != "error":
            return
        self.state, self.last_error, self._stop_requested = "starting", None, False
        self._run("start", "/api/listen/start", 5)

    def stop(self) -> None:
        if self.state == "starting":
            self._stop_requested = True  # released before the microphone was even open: stop as soon as it is
        elif self.state == "listening":
            self.state = "transcribing"
            self._run("stop", "/api/listen/stop", 40)

    def cancel(self) -> None:
        if self.state in ("starting", "listening"):
            self.state = "idle"
            self._run("cancel", "/api/listen/cancel", 5)

    def poll(self) -> list[dict[str, Any]]:
        """Finished requests. A 'stop' result carries the transcript in ``text`` (empty when nothing was heard)."""
        done = []
        while True:
            try:
                r = self._results.get_nowait()
            except queue.Empty:
                return done
            if r["kind"] == "start":
                if not r["ok"]:
                    self.state, self.last_error = "error", r["error"]
                    done.append(r)
                elif self.state == "starting":
                    self.state = "listening"
                    if self._stop_requested:
                        self.stop()
                else:  # cancelled while starting: close the microphone again
                    self._run("cancel", "/api/listen/cancel", 5)
            elif r["kind"] == "stop":
                self.state = "idle" if r["ok"] else "error"
                self.last_error = None if r["ok"] else r["error"]
                done.append(r)
