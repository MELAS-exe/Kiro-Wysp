"""The Blender adapter runtime: ties the SDK client, the main-thread pump and the scene together.

bpy is only ever touched from the main thread. The network thread (inside AdapterClient) hands each
request to a QueueDispatcher; `pump()` runs on the main thread, driven by a bpy.app.timers callback
(interactive) or a manual loop (headless, demo/run_adapter.py).
"""

from __future__ import annotations

import logging
import time

import bpy
from wysp_adapter_sdk import AdapterRuntime, QueueDispatcher
from wysp_adapter_sdk.client import AdapterClient

from . import highlight as highlight_mod
from . import observe, telemetry
from .actions import register_all
from .events import SceneWatcher
from .highlight import clear_highlight, highlight_object

log = logging.getLogger("wysp.blender")


class BlenderAdapter(AdapterRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.dispatcher = QueueDispatcher()
        register_all(self.registry)
        self.watcher = SceneWatcher(self)
        self._was_connected = False

    def observe(self, scope: dict) -> dict:
        started = time.monotonic()
        obs = observe.build_observation(self.state_version(), scope)
        telemetry.tm.emit(
            "observe",
            duration_ms=round((time.monotonic() - started) * 1000, 1),
            entities=len(obs["entities"]),
            truncated=obs["truncated"],
        )
        return obs

    def handle(self, method: str, params: dict):
        result = super().handle(method, params)
        is_dry = bool((params.get("call") or {}).get("dry_run"))
        if method in ("adapter.execute", "adapter.undo") and not is_dry:
            # Blender's own history gets a step, so Ctrl+Z also reverts what Wysp did.
            try:
                bpy.ops.ed.undo_push(message="Wysp: " + method.split(".")[-1])
            except (RuntimeError, AttributeError):
                pass
        return result

    def tick(self) -> None:
        """Main-thread heartbeat: run queued requests, then look for scene changes."""
        started = time.monotonic()
        ran = self.dispatcher.pump(0.02)
        self.watcher.poll()
        self._clear_if_disconnected()
        elapsed = (time.monotonic() - started) * 1000
        if elapsed > telemetry.SLOW_TICK_MS:
            telemetry.tm.emit("slow_tick", duration_ms=round(elapsed, 1), jobs=ran)

    def get_context(self) -> dict:
        return observe.build_context(self.state_version())

    def highlight(self, ref: str, style: str, duration_ms: int) -> dict:
        return highlight_object(ref, style, duration_ms)

    def clear_highlight(self) -> dict:
        """Contract 1.1: remove the persistent highlight. {"cleared": False} when nothing was shown."""
        return highlight_mod.clear_active()

    def on_focus_changed(self, old: list[str], new: list[str]) -> None:
        """Called by the SceneWatcher (main thread) when the selection or active object changed."""
        ref = highlight_mod.dismissed_by_selection(old, new, self.origin.current())
        if ref is not None:
            self.report_highlight_dismissed(ref)

    def _clear_if_disconnected(self) -> None:
        """A highlight must not outlive the Core connection (the Core no longer knows about it)."""
        connected = self.client is not None and self.client.connected
        if self._was_connected and not connected:
            clear_highlight()
        self._was_connected = connected

    def make_client(self, url: str, token: str, heartbeat_s: float = 15.0) -> AdapterClient:
        from . import highlight

        highlight.set_core_url(url)  # label highlighting asks this Core's local OCR
        client = AdapterClient(
            manifest=observe.manifest(),
            url=url,
            token=token,
            handler=self.handle,
            dispatcher=self.dispatcher,
            heartbeat_s=heartbeat_s,
            state_version=self.state_version,
            on_request_done=telemetry.on_request_done,
        )
        self.client = client
        return client

    def shutdown(self) -> None:
        try:
            clear_highlight()
        except Exception:  # noqa: BLE001
            pass
        self.watcher.stop()
        if self.client is not None:
            self.client.stop()
