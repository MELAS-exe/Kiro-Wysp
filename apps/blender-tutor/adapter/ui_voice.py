"""Wysp's voice inside Blender: audio from the Core's ``/api/tts``, played with Blender's ``aud`` module.

Fetching runs on a short-lived thread per segment (started as soon as the segment arrives, so the next
one is ready when the current one ends); playback and every ``aud`` call stay on the main thread.
The Core synthesises with local voices; nothing here talks to any other host.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import urllib.error
import urllib.request
import wave

log = logging.getLogger("wysp.blender.ui")

FETCH_TIMEOUT_S = 20.0


def tts_url(adapter_url: str) -> str:
    base = adapter_url.rsplit("/ws/", 1)[0] if "/ws/" in adapter_url else adapter_url.rstrip("/")
    if base.startswith("wss://"):
        base = "https://" + base[len("wss://") :]
    elif base.startswith("ws://"):
        base = "http://" + base[len("ws://") :]
    return base + "/api/tts"


class VoicePlayer:
    """prepare(segment) -> ready(id) -> play(id) -> is_playing() / stop(). Main-thread API except fetching."""

    def __init__(self, url: str, lang: str = "en") -> None:
        self.url = url
        self.lang = lang
        self.available = True
        self.last_error: str | None = None
        self._lock = threading.Lock()
        self._results: dict[str, tuple[str, float] | bool | None] = {}  # id -> (path, seconds) | False | None
        self._files: list[str] = []
        self._device = None
        self._handle = None

    # ------------------------------------------------------------------ fetching
    def prepare(self, segment: dict) -> None:
        sid = segment["id"]
        if not self.available:
            return
        with self._lock:
            if sid in self._results:
                return
            self._results[sid] = None
        threading.Thread(target=self._fetch, args=(sid, str(segment.get("text", ""))), daemon=True).start()

    def _fetch(self, sid: str, text: str) -> None:
        result: tuple[str, float] | bool = False
        try:
            body = json.dumps({"text": text, "lang": self.lang}).encode("utf-8")
            req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:  # noqa: S310 - fixed local Core URL
                audio = resp.read()
            fd, path = tempfile.mkstemp(prefix="wysp-voice-", suffix=".wav")
            with os.fdopen(fd, "wb") as fh:
                fh.write(audio)
            with wave.open(path, "rb") as w:
                seconds = w.getnframes() / float(w.getframerate() or 1)
            with self._lock:
                self._files.append(path)
            result = (path, seconds)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404, 503):  # no voice on this Core: stop asking for every segment
                self.available = False
            self.last_error = f"voice unavailable ({exc.code})"
        except Exception as exc:  # noqa: BLE001 - a missing voice must never break the chat
            self.last_error = f"voice failed: {type(exc).__name__}: {exc}"[:160]
        with self._lock:
            if sid in self._results:
                self._results[sid] = result

    def ready(self, sid: str) -> float | bool | None:
        """Seconds of audio when ready, False when there will be none, None while it is being fetched."""
        with self._lock:
            r = self._results.get(sid, False)
        if r is None or r is False:
            return r
        return r[1]

    # ------------------------------------------------------------------ playback
    def play(self, sid: str) -> bool:
        with self._lock:
            r = self._results.get(sid)
        if not r:
            return False
        try:
            import aud

            if self._device is None:
                self._device = aud.Device()
            self.stop()
            self._handle = self._device.play(aud.Sound(r[0]))
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"cannot play audio: {exc}"[:160]
            log.warning(self.last_error)
            return False

    def is_playing(self) -> bool:
        h = self._handle
        try:
            return bool(h is not None and h.status)
        except Exception:  # noqa: BLE001
            return False

    def stop(self) -> None:
        h, self._handle = self._handle, None
        if h is not None:
            try:
                h.stop()
            except Exception:  # noqa: BLE001
                pass

    def forget(self, sid: str) -> None:
        """Drop a segment once it has been played or cancelled, and delete its audio file."""
        with self._lock:
            r = self._results.pop(sid, None)
            path = r[0] if r else None
            if path in self._files:
                self._files.remove(path)
        if path:
            try:
                os.remove(path)
            except OSError:
                pass

    def close(self) -> None:
        self.stop()
        with self._lock:
            files, self._files = self._files, []
            self._results.clear()
        for path in files:
            try:
                os.remove(path)
            except OSError:
                pass
