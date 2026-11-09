"""The Blender adapter runtime: ties the SDK client, the main-thread pump and the scene together.

bpy is only ever touched from the main thread. The network thread (inside AdapterClient) hands each
request to a QueueDispatcher; `pump()` runs on the main thread, driven by a bpy.app.timers callback
(interactive) or a manual loop (headless, demo/run_adapter.py).
"""

from __future__ import annotations

import logging

import bpy
from wysp_adapter_sdk import AdapterRuntime, QueueDispatcher
from wysp_adapter_sdk.client import AdapterClient

from . import observe
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

    def observe(self, scope: dict) -> dict:
        return observe.build_observation(self.state_version(), scope)

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
        self.dispatcher.pump(0.02)
        self.watcher.poll()

    def get_context(self) -> dict:
        return observe.build_context(self.state_version())

    def highlight(self, ref: str, style: str, duration_ms: int) -> dict:
        return highlight_object(ref, style, duration_ms)

    def make_client(self, url: str, token: str, heartbeat_s: float = 15.0) -> AdapterClient:
        client = AdapterClient(
            manifest=observe.manifest(),
            url=url,
            token=token,
            handler=self.handle,
            dispatcher=self.dispatcher,
            heartbeat_s=heartbeat_s,
            state_version=self.state_version,
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
