"""Wysp Tutor: Blender add-on (extension). Connects Blender to a local Wysp Core.

Interactive use: sidebar tab "Wysp" in the 3D Viewport. The package can also be imported without
calling register() (headless runner, tests); bpy is only used on the main thread.
"""

from __future__ import annotations

import logging
from pathlib import Path

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel

log = logging.getLogger("wysp.blender")

_adapter = None  # BlenderAdapter, created on first connect
_timer_running = False


def _prefs():
    return bpy.context.preferences.addons[__package__].preferences


def read_token(path_str: str = "") -> str:
    path = Path(path_str).expanduser() if path_str else Path.home() / ".wysp" / "token"
    return path.read_text(encoding="utf-8").strip()


def _pump() -> float | None:
    """bpy.app.timers callback: the only place where network requests touch bpy."""
    if _adapter is None:
        return None
    try:
        _adapter.tick()
    except Exception:  # noqa: BLE001 - never let the timer die silently
        log.exception("wysp tick failed")
    return 0.05


def connect() -> str:
    global _adapter, _timer_running
    from .runtime import BlenderAdapter

    prefs = _prefs()
    try:
        token = read_token(prefs.token_path)
    except OSError as exc:
        return f"Cannot read the pairing token: {exc}. Start the Core once with `wysp serve`."
    if _adapter is None:
        _adapter = BlenderAdapter()
    if _adapter.client is not None:
        _adapter.client.stop()
    client = _adapter.make_client(prefs.core_url, token)
    client.start()
    _adapter.watcher.start()
    if not _timer_running:
        bpy.app.timers.register(_pump, first_interval=0.05, persistent=True)
        _timer_running = True
    return "Connecting…"


def disconnect() -> None:
    global _adapter, _timer_running
    if _adapter is not None:
        _adapter.shutdown()
        _adapter = None
    if _timer_running and bpy.app.timers.is_registered(_pump):
        bpy.app.timers.unregister(_pump)
    _timer_running = False


class WYSP_Preferences(AddonPreferences):
    bl_idname = __package__

    core_url: StringProperty(name="Core address", default="ws://127.0.0.1:8765/ws/adapter")  # type: ignore[valid-type]
    token_path: StringProperty(  # type: ignore[valid-type]
        name="Token file", subtype="FILE_PATH", default="", description="Empty means ~/.wysp/token"
    )
    auto_connect: BoolProperty(name="Connect on startup", default=False)  # type: ignore[valid-type]

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "core_url")
        col.prop(self, "token_path")
        col.prop(self, "auto_connect")


class WYSP_OT_connect(Operator):
    bl_idname = "wysp.connect"
    bl_label = "Connect"
    bl_description = "Connect Blender to the local Wysp Core"

    def execute(self, context):
        message = connect()
        self.report({"INFO"} if message == "Connecting…" else {"ERROR"}, message)
        return {"FINISHED"}


class WYSP_OT_disconnect(Operator):
    bl_idname = "wysp.disconnect"
    bl_label = "Disconnect"

    def execute(self, context):
        disconnect()
        return {"FINISHED"}


class WYSP_PT_panel(Panel):
    bl_label = "Wysp"
    bl_idname = "WYSP_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Wysp"

    def draw(self, context):
        layout = self.layout
        client = _adapter.client if _adapter is not None else None
        status = client.status if client else "not connected"
        layout.label(text=f"Status: {status}")
        if client is not None and client.last_error and status != "connected":
            layout.label(text=client.last_error[:60], icon="ERROR")
        row = layout.row()
        row.operator("wysp.connect", icon="LINKED")
        row.operator("wysp.disconnect", icon="UNLINKED")
        layout.label(text="Open the Panel at http://127.0.0.1:8765")


_CLASSES = (WYSP_Preferences, WYSP_OT_connect, WYSP_OT_disconnect, WYSP_PT_panel)


@bpy.app.handlers.persistent
def _auto_connect(*_args) -> None:
    try:
        if _prefs().auto_connect and _adapter is None:
            connect()
    except Exception:  # noqa: BLE001
        log.exception("auto connect failed")


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.app.handlers.load_post.append(_auto_connect)
    if bpy.app.timers.is_registered(_pump):
        return
    bpy.app.timers.register(lambda: _auto_connect() or None, first_interval=1.0)


def unregister() -> None:
    disconnect()
    if _auto_connect in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_auto_connect)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
