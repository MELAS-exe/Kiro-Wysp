"""Wysp Tutor: Blender add-on (extension). Connects Blender to a local Wysp Core.

Interactive use: sidebar tab "Wysp" in the 3D Viewport (connection, chat, steps) and the Wysp board in a
Node Editor. The package can also be imported without calling register() (headless runner, tests);
bpy is only used on the main thread.
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
MIN_SDK = (0, 2)  # AdapterClient(on_request_done=...) appeared in SDK 0.2


def _prefs():
    return bpy.context.preferences.addons[__package__].preferences


def read_token(path_str: str = "") -> str:
    path = Path(path_str).expanduser() if path_str else Path.home() / ".wysp" / "token"
    return path.read_text(encoding="utf-8").strip()


def _pump() -> float | None:
    """bpy.app.timers callback: the only place where network messages touch bpy."""
    if _adapter is None:
        return None
    try:
        _adapter.tick()
    except Exception:  # noqa: BLE001 - never let the timer die silently
        log.exception("wysp tick failed")
    try:
        from . import ui_panel

        ui_panel.tick()
    except Exception:  # noqa: BLE001
        log.exception("wysp panel tick failed")
    return 0.05


def _sdk_problem() -> str | None:
    """A readable message when Blender loaded an older SDK wheel than this add-on needs."""
    import wysp_adapter_sdk

    have = getattr(wysp_adapter_sdk, "__version__", "0.1.0")
    if tuple(int(x) for x in have.split(".")[:2]) < MIN_SDK:
        return (
            f"Blender is using an old Wysp SDK ({have}). Rebuild and reinstall the extension "
            "(scripts/build_blender_extension.py --install), then restart Blender."
        )
    return None


def connect() -> str:
    global _adapter, _timer_running
    from . import telemetry, ui_panel
    from .runtime import BlenderAdapter

    problem = _sdk_problem()
    if problem:
        log.error(problem)
        return problem
    prefs = _prefs()
    try:
        token = read_token(prefs.token_path)
    except OSError as exc:
        return f"Cannot read the pairing token: {exc}. Start the Core once with `wysp serve`."
    telemetry.configure(prefs.log_level)
    if _adapter is None:
        _adapter = BlenderAdapter()
    if _adapter.client is not None:
        _adapter.client.stop()
    client = _adapter.make_client(prefs.core_url, token)
    client.start()
    _adapter.watcher.start()
    if prefs.in_blender_ui:
        ui_panel.start(
            prefs.core_url,
            narrate=prefs.narrate_silently,
            speak=prefs.speak_in_blender,
            listen=prefs.listen_in_blender,
            token=token,
        )
    if not _timer_running:
        bpy.app.timers.register(_pump, first_interval=0.05, persistent=True)
        _timer_running = True
    return "Connecting…"


def disconnect() -> None:
    global _adapter, _timer_running
    from . import telemetry, ui_panel

    ui_panel.stop()
    if _adapter is not None:
        _adapter.shutdown()
        _adapter = None
    if _timer_running and bpy.app.timers.is_registered(_pump):
        bpy.app.timers.unregister(_pump)
    _timer_running = False
    telemetry.close()


class WYSP_Preferences(AddonPreferences):
    bl_idname = __package__

    core_url: StringProperty(name="Core address", default="ws://127.0.0.1:8765/ws/adapter")  # type: ignore[valid-type]
    token_path: StringProperty(  # type: ignore[valid-type]
        name="Token file", subtype="FILE_PATH", default="", description="Empty means ~/.wysp/token"
    )
    auto_connect: BoolProperty(name="Connect on startup", default=False)  # type: ignore[valid-type]
    in_blender_ui: BoolProperty(  # type: ignore[valid-type]
        name="Chat and board in Blender",
        default=True,
        description="Show the conversation, permission prompts, steps and the board inside Blender",
    )
    narrate_silently: BoolProperty(  # type: ignore[valid-type]
        name="Pace narration in Blender",
        default=True,
        description="Fire narration cues at reading pace. Turn off when the browser Panel speaks aloud",
    )
    listen_in_blender: BoolProperty(  # type: ignore[valid-type]
        name="Talk to Wysp in Blender",
        default=True,
        description="Push-to-talk (hold Alt+Space, or the Talk button). The Core records only while you hold it, "
        "then transcribes the clip with its speech service (Whisper on Groq by default)",
    )
    speak_in_blender: BoolProperty(  # type: ignore[valid-type]
        name="Speak in Blender",
        default=True,
        description="Read Wysp's narration aloud in Blender (local Windows voices through the Core). "
        "Turn off the browser Panel's voice to avoid hearing it twice",
    )
    log_level: bpy.props.EnumProperty(  # type: ignore[valid-type]
        name="Blender-side logs",
        description="Adapter telemetry written to ~/.wysp/logs (merged with the Core's by `wysp logs summary`)",
        items=[
            ("off", "Off", "Record nothing"),
            ("basic", "Basic", "Request timings, slow ticks, errors"),
            ("full", "Full", "Also request summaries and every wysp log line"),
        ],
        default="full",
    )

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "core_url")
        col.prop(self, "token_path")
        col.prop(self, "auto_connect")
        col.prop(self, "in_blender_ui")
        col.prop(self, "narrate_silently")
        col.prop(self, "speak_in_blender")
        col.prop(self, "listen_in_blender")
        col.prop(self, "log_level")


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
    bl_order = 0

    def draw(self, context):
        from . import ui_panel

        layout = self.layout
        client = _adapter.client if _adapter is not None else None
        status = client.status if client else "not connected"
        layout.label(text=f"Blender link: {status}", icon="LINKED" if status == "connected" else "UNLINKED")
        if client is not None and client.last_error and status != "connected":
            layout.label(text=client.last_error[:60], icon="ERROR")
        row = layout.row()
        row.operator("wysp.connect", icon="LINKED")
        row.operator("wysp.disconnect", icon="UNLINKED")
        session = ui_panel.get()
        if session is not None and session.state.connected:
            info = session.state.session
            model = info.get("model") or info.get("llm") or "?"
            layout.label(text=f"Model: {model}"[:48], icon="LIGHT_SUN")
            layout.prop(context.window_manager, "wysp_logging")
            row = layout.row(align=True)
            row.operator("wysp.board_open", icon="NODETREE")
            row.operator("wysp.board_here", text="", icon="SEQ_STRIP_DUPLICATE")
        session = ui_panel.get()
        if session is not None and session.voice is not None and not session.voice.available:
            layout.label(text="Voice off: no voice on the Core", icon="MUTE_IPO_OFF")


_CLASSES = (WYSP_Preferences, WYSP_OT_connect, WYSP_OT_disconnect, WYSP_PT_panel)


@bpy.app.handlers.persistent
def _auto_connect(*_args) -> None:
    try:
        if _prefs().auto_connect and _adapter is None:
            connect()
    except Exception:  # noqa: BLE001
        log.exception("auto connect failed")


@bpy.app.handlers.persistent
def _before_save(*_args) -> None:
    """Never write the board into the user's file: it is a view and needs the add-on to be read."""
    from . import board_tree

    try:
        board_tree.remove_tree()
    except Exception:  # noqa: BLE001
        log.exception("could not remove the board before saving")


@bpy.app.handlers.persistent
def _after_save_or_load(*_args) -> None:
    from . import ui_panel

    session = ui_panel.get()
    if session is not None:
        session.state.board_revision += 1  # rebuild the board tree on the next tick


_HANDLERS = (
    (bpy.app.handlers.load_post, _auto_connect),
    (bpy.app.handlers.save_pre, _before_save),
    (bpy.app.handlers.save_post, _after_save_or_load),
    (bpy.app.handlers.load_post, _after_save_or_load),
)


def register() -> None:
    from . import board_tree, ui_panel

    for cls in _CLASSES + board_tree.CLASSES + ui_panel.CLASSES:
        bpy.utils.register_class(cls)
    ui_panel.register_props()
    ui_panel.register_keymaps()
    for lst, fn in _HANDLERS:
        lst.append(fn)
    if bpy.app.timers.is_registered(_pump):
        return
    bpy.app.timers.register(lambda: _auto_connect() or None, first_interval=1.0)


def unregister() -> None:
    from . import board_tree, ui_panel

    disconnect()
    for lst, fn in _HANDLERS:
        if fn in lst:
            lst.remove(fn)
    try:
        board_tree.remove_tree()
    except Exception:  # noqa: BLE001
        pass
    ui_panel.unregister_keymaps()
    ui_panel.unregister_props()
    for cls in reversed(_CLASSES + board_tree.CLASSES + ui_panel.CLASSES):
        bpy.utils.unregister_class(cls)
