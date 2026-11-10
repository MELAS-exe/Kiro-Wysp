"""Talk to Wysp inside Blender: chat, permission prompts, guided steps and the board.

``PanelSession`` owns a ``PanelClient`` (the UI protocol socket) and a ``UiState``. It is ticked on the
main thread by the add-on's timer. Operators and panels only read the state and send protocol
messages, exactly like the browser Panel's components: no tutoring logic here.

Voice stays in the browser Panel. When the browser Panel is not open, this panel "plays" narration
silently at reading pace so cues (highlights) still fire; turn it off in the add-on preferences when
the browser Panel speaks.
"""

from __future__ import annotations

import logging
import textwrap

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator, Panel

from . import board_tree
from .ui_client import PanelClient
from .ui_state import UiState
from .ui_voice import VoicePlayer, tts_url

log = logging.getLogger("wysp.blender.ui")

STATUS_ICONS = {"idle": "CHECKMARK", "thinking": "SORTTIME", "acting": "PLAY", "speaking": "OUTLINER_OB_SPEAKER"}
STEP_ICONS = {"pending": "LAYER_USED", "active": "RIGHTARROW", "done": "CHECKMARK", "failed": "CANCEL"}
RISK_ICONS = {"read_only": "HIDE_OFF", "ui_state": "WINDOW", "reversible": "LOOP_BACK", "irreversible": "ERROR"}
TRANSCRIPT_LINES = 14


def ui_url(adapter_url: str) -> str:
    base = adapter_url.rsplit("/ws/", 1)[0] if "/ws/" in adapter_url else adapter_url.rstrip("/")
    return base + "/ws/ui"


class PanelSession:
    def __init__(self, url: str, narrate: bool = True, voice: VoicePlayer | None = None) -> None:
        self.client = PanelClient(url)
        self.voice = voice
        self.state = UiState(narrate=narrate, voice=voice)
        self._had_permission = False
        self._voice_note_shown = False
        self._seen_revision = -1
        self._seen_board = -1
        self._last_active: str | None = None
        self._syncing_logging = False
        self.received = 0  # messages handled, for diagnostics

    def start(self) -> None:
        self.client.start()

    def stop(self) -> None:
        self.client.stop()
        if self.voice is not None:
            self.voice.close()

    def send(self, message: dict) -> bool:
        ok = self.client.send(message)
        if not ok:
            self.state.note("Not connected to the Wysp Core.", "error")
        return ok

    def tick(self) -> None:
        for msg in self.client.drain():
            self.received += 1
            t = msg.get("type")
            if t == "_connected":
                self.state.set_connected(True)
                self.client.send({"type": "board.snapshot_request"})
                continue
            if t == "_disconnected":
                self.state.set_connected(False)
                continue
            for reply in self.state.handle(msg):
                self.client.send(reply)
            if t == "session.state":
                self._sync_logging_prop()
                if self.voice is not None and self.state.session.get("lang"):
                    self.voice.lang = self.state.session["lang"]
        for reply in self.state.tick():
            self.client.send(reply)
        if self.voice is not None and not self.voice.available and not self._voice_note_shown:
            self._voice_note_shown = True
            self.state.note(f"No voice in Blender: {self.voice.last_error}. Captions only.", "info")
        has_permission = self.state.permission is not None
        if has_permission and not self._had_permission:
            _reveal_sidebar()
        if has_permission != self._had_permission:
            _redraw_viewports()
        self._had_permission = has_permission
        if self.state.board_revision != self._seen_board:
            self._seen_board = self.state.board_revision
            try:
                board_tree.sync(self.state.board)
            except Exception:  # noqa: BLE001
                log.exception("board sync failed")
            self._last_active = board_tree.active_node_id()
        else:
            active = board_tree.active_node_id()
            if active and active != self._last_active:
                self.client.send({"type": "board.select", "node_id": active})
            self._last_active = active
        if self.state.revision != self._seen_revision:
            self._seen_revision = self.state.revision
            _redraw_panels()

    def _sync_logging_prop(self) -> None:
        level = self.state.session.get("logging")
        wm = bpy.context.window_manager
        if level and getattr(wm, "wysp_logging", None) != level:
            self._syncing_logging = True
            try:
                wm.wysp_logging = level
            finally:
                self._syncing_logging = False


_session: PanelSession | None = None


def get() -> PanelSession | None:
    return _session


def start(adapter_url: str, narrate: bool, speak: bool = True) -> None:
    global _session
    stop()
    voice = VoicePlayer(tts_url(adapter_url)) if speak else None
    _session = PanelSession(ui_url(adapter_url), narrate=narrate or speak, voice=voice)
    _session.start()
    _add_banner()


def stop() -> None:
    global _session
    _remove_banner()
    if _session is not None:
        _session.stop()
        _session = None


def tick() -> None:
    if _session is not None:
        _session.tick()


def _reveal_sidebar() -> None:
    """An approval is waiting: make sure the 3D Viewport sidebar (where the Wysp tab lives) is open."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                if not space.show_region_ui:
                    space.show_region_ui = True
                    area.tag_redraw()


def _redraw_viewports() -> None:
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


# A banner in the viewport while an approval is pending: the Wysp sidebar tab may not be the one shown,
# and scripts cannot switch sidebar tabs.
_banner: dict = {"handle": None}


def _draw_banner() -> None:
    s = _session
    req = s.state.permission if s is not None else None
    region = bpy.context.region
    if not req or region is None:
        return
    try:
        import gpu

        from .highlight import draw_callout

        gpu.state.blend_set("ALPHA")
        scale = bpy.context.preferences.system.ui_scale  # bottom of the viewport: never over the header menus
        draw_callout(
            region,
            f"Wysp asks your approval: {req.get('title', '')}. Answer in the Wysp tab (N).",
            x=16 * scale,
            top=64 * scale,
        )
        gpu.state.blend_set("NONE")
    except Exception:  # noqa: BLE001 - drawing must never break Blender
        pass


def _add_banner() -> None:
    if _banner["handle"] is None and not bpy.app.background:
        _banner["handle"] = bpy.types.SpaceView3D.draw_handler_add(_draw_banner, (), "WINDOW", "POST_PIXEL")


def _remove_banner() -> None:
    handle, _banner["handle"] = _banner["handle"], None
    if handle is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
        except (ValueError, RuntimeError):
            pass


def _redraw_panels() -> None:
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in ("VIEW_3D", "NODE_EDITOR"):
                area.tag_redraw()
                for region in area.regions:
                    if region.type == "UI":
                        region.tag_redraw()


# ------------------------------------------------------------------------ properties
def _on_input(self, context) -> None:
    text = (self.wysp_input or "").strip()
    if not text or _session is None:
        return
    self["wysp_input"] = ""  # direct assignment: does not re-trigger this callback
    _session.state.cancel_narration()  # like the browser Panel: a new message stops what Wysp was saying
    if _session.send({"type": "user.message", "text": text[:4000], "source": "typed"}):
        _session.state.add_user(text)


def _on_logging(self, context) -> None:
    if _session is None or _session._syncing_logging:
        return
    _session.send({"type": "settings.update", "logging": self.wysp_logging})


def register_props() -> None:
    wm = bpy.types.WindowManager
    wm.wysp_input = StringProperty(  # type: ignore[attr-defined]
        name="Message", description="Ask Wysp something, then press Enter", update=_on_input, options={"SKIP_SAVE"}
    )
    wm.wysp_logging = EnumProperty(  # type: ignore[attr-defined]
        name="Logging",
        description="Session telemetry recorded by the Core in ~/.wysp/logs",
        items=[
            ("off", "Off", "Record nothing"),
            ("basic", "Basic", "Timings, counts and errors; no conversation content"),
            ("full", "Full", "Everything, including the conversation and prompts"),
        ],
        default="full",
        update=_on_logging,
        options={"SKIP_SAVE"},
    )


def unregister_props() -> None:
    wm = bpy.types.WindowManager
    for name in ("wysp_input", "wysp_logging"):
        if hasattr(wm, name):
            delattr(wm, name)


# ------------------------------------------------------------------------- operators
class _SessionOperator(Operator):
    @classmethod
    def poll(cls, context):
        return _session is not None and _session.client.connected


class WYSP_OT_send(_SessionOperator):
    bl_idname = "wysp.send"
    bl_label = "Send"
    bl_description = "Send the message to Wysp"

    def execute(self, context):
        _on_input(context.window_manager, context)
        return {"FINISHED"}


class WYSP_OT_say(_SessionOperator):
    bl_idname = "wysp.say"
    bl_label = "Say"
    bl_description = "Send this answer to Wysp"
    text: StringProperty()  # type: ignore[valid-type]

    def execute(self, context):
        _session.state.cancel_narration()
        if _session.send({"type": "user.message", "text": self.text[:4000], "source": "typed"}):
            _session.state.add_user(self.text)
            _session.state.clarification = None
        return {"FINISHED"}


class WYSP_OT_interrupt(_SessionOperator):
    bl_idname = "wysp.interrupt"
    bl_label = "Stop"
    bl_description = "Interrupt Wysp"

    def execute(self, context):
        _session.send(_session.state.interrupt())
        return {"FINISHED"}


class WYSP_OT_continue(_SessionOperator):
    bl_idname = "wysp.resume"
    bl_label = "Continue"
    bl_description = "Resume the interrupted explanation"

    def execute(self, context):
        _session.send({"type": "user.continue"})
        return {"FINISHED"}


class WYSP_OT_undo_last(_SessionOperator):
    bl_idname = "wysp.undo_last"
    bl_label = "Undo Wysp"
    bl_description = "Undo the last change Wysp made"

    def execute(self, context):
        _session.send({"type": "undo.last"})
        return {"FINISHED"}


class WYSP_OT_permission(_SessionOperator):
    """Answer a permission request. Always a click: this panel has no voice."""

    bl_idname = "wysp.permission"
    bl_label = "Answer"
    bl_description = "Approve or deny what Wysp proposes"
    decision: EnumProperty(  # type: ignore[valid-type]
        items=[
            ("approve", "Approve", "Let Wysp do it"),
            ("deny", "Deny", "Do not do it"),
            ("grant_lesson", "Allow for this lesson", "Approve similar reversible actions during this lesson"),
        ]
    )

    def execute(self, context):
        req = _session.state.permission
        if not req:
            return {"CANCELLED"}
        if self.decision == "grant_lesson" and not req.get("can_grant"):
            return {"CANCELLED"}
        _session.send(
            {"type": "permission.respond", "request_id": req["request_id"], "decision": self.decision, "via": "click"}
        )
        _session.state.permission = None
        return {"FINISHED"}


class WYSP_OT_board_why(_SessionOperator):
    bl_idname = "wysp.board_why"
    bl_label = "Why?"
    bl_description = "Ask Wysp why this is on the board"
    node_id: StringProperty()  # type: ignore[valid-type]

    def execute(self, context):
        _session.send({"type": "board.ask_why", "node_id": self.node_id})
        return {"FINISHED"}


class WYSP_OT_board_show(_SessionOperator):
    bl_idname = "wysp.board_show"
    bl_label = "Show"
    bl_description = "Highlight this element in Blender"
    node_id: StringProperty()  # type: ignore[valid-type]

    def execute(self, context):
        _session.send({"type": "board.select", "node_id": self.node_id})
        return {"FINISHED"}


# ---------------------------------------------------------------------------- drawing
def _wrap(text: str, context) -> list[str]:
    width = context.region.width if context.region else 300
    scale = context.preferences.system.ui_scale  # effective scale: user setting times monitor DPI
    chars = max(16, int((width - 44 * scale) / (8.2 * scale)))
    return textwrap.wrap(text, chars) or [""]


def _draw_text(layout, text: str, context, icon: str = "NONE") -> None:
    col = layout.column(align=True)
    for i, line in enumerate(_wrap(text, context)):
        col.label(text=line, icon=icon if i == 0 else "BLANK1")


def draw_permission(layout, context, req: dict) -> None:
    box = layout.box()
    box.alert = req.get("risk") == "irreversible"
    box.label(text="Wysp asks permission", icon=RISK_ICONS.get(req.get("risk", ""), "QUESTION"))
    _draw_text(box, req.get("title", ""), context)
    if req.get("target"):
        _draw_text(box, f"Target: {req['target']}", context)
    risk = req.get("risk", "")
    box.label(
        text=f"Risk: {risk.replace('_', ' ')}  ·  {'can be undone' if req.get('reversible') else 'cannot be undone'}"
    )
    if req.get("rationale"):
        _draw_text(box, f"Why: {req['rationale']}", context)
    if req.get("preview"):
        _draw_text(box, f"Preview: {str(req['preview'])[:300]}", context, "INFO")
    row = box.row(align=True)
    row.scale_y = 1.3
    row.operator("wysp.permission", text="Approve", icon="CHECKMARK").decision = "approve"
    row.operator("wysp.permission", text="Deny", icon="X").decision = "deny"
    if req.get("can_grant") and req.get("reversible"):
        box.operator("wysp.permission", text="Allow for this lesson", icon="UNLOCKED").decision = "grant_lesson"


def draw_steps(layout, context, steps: list[dict]) -> None:
    if not steps:
        return
    box = layout.box()
    box.label(text="Steps (you do them, Wysp checks)", icon="SEQUENCE")
    for s in steps:
        _draw_text(
            box, f"{s.get('index', 0) + 1}. {s.get('text', '')}", context, STEP_ICONS.get(s.get("status"), "DOT")
        )


def draw_transcript(layout, context, state: UiState) -> None:
    box = layout.box()
    # Newest first: Blender panels cannot be scrolled from a script, so the latest message must be on top.
    items = list(state.transcript)[-TRANSCRIPT_LINES:][::-1]
    if items:
        box.label(text="Newest first", icon="SORT_DESC")
    if not items:
        box.label(text="Ask Wysp about your scene.", icon="LIGHT_SUN")
    for it in items:
        kind = it["kind"]
        if kind == "user":
            _draw_text(box, f"You: {it['text']}", context, "USER")
        elif kind == "wysp":
            seg = it["segment"]
            marker = f"({seg['marker']}) " if seg.get("marker") else ""
            icon = "LIGHT_SUN" if it["state"] != "cancelled" else "PANEL_CLOSE"
            _draw_text(box, f"{marker}{it['text']}", context, icon)
        elif kind == "evidence":
            label = "Verified in Blender" if it.get("scope") == "user_action" else "Checked"
            _draw_text(box, f"{label}: {it['text']}", context, "CHECKMARK" if it.get("ok") else "CANCEL")
        else:
            _draw_text(box, it["text"], context, "ERROR" if it.get("tone") == "error" else "INFO")


def draw_chat(layout, context) -> None:
    s = _session
    if s is None:
        layout.label(text="Connect to talk to Wysp here.", icon="INFO")
        return
    st = s.state
    if not st.connected:
        layout.label(text=f"Chat: {s.client.status}", icon="UNLINKED")
        if s.client.last_error:
            layout.label(text=s.client.last_error[:60])
        return
    if st.permission:
        draw_permission(layout, context, st.permission)
    if st.clarification:
        box = layout.box()
        _draw_text(box, st.clarification["question"], context, "QUESTION")
        for opt in st.clarification["options"][:6]:
            box.operator("wysp.say", text=opt[:60]).text = opt
    row = layout.row()
    row.label(text=st.activity or st.status, icon=STATUS_ICONS.get(st.status, "DOT"))
    col = layout.column(align=True)
    col.prop(context.window_manager, "wysp_input", text="", icon="OUTLINER_OB_FONT")
    row = col.row(align=True)
    row.operator("wysp.send", icon="EXPORT")
    row.operator("wysp.interrupt", icon="PAUSE")
    row.operator("wysp.resume", text="", icon="PLAY")
    row.separator()
    row.operator("wysp.undo_last", text="Undo Wysp", icon="LOOP_BACK")
    draw_steps(layout, context, st.steps)
    draw_transcript(layout, context, st)


def draw_board_legend(layout) -> None:
    col = layout.column(align=True)
    col.label(text="observed in Blender", icon="HIDE_OFF")
    col.label(text="inferred (likely)", icon="QUESTION")
    col.label(text="example, not your scene", icon="INFO")


class WYSP_PT_chat(Panel):
    bl_label = "Talk to Wysp"
    bl_idname = "WYSP_PT_chat"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Wysp"
    bl_order = 1

    def draw(self, context):
        draw_chat(self.layout, context)


class WYSP_PT_board_side(Panel):
    """Sidebar of the board's Node Editor: legend, steps and chat."""

    bl_label = "Wysp"
    bl_idname = "WYSP_PT_board_side"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Wysp"

    @classmethod
    def poll(cls, context):
        return getattr(context.space_data, "tree_type", "") == board_tree.TREE_TYPE

    def draw(self, context):
        draw_board_legend(self.layout)
        if _session is not None and _session.state.board.get("stale"):
            self.layout.label(text="The board may be out of date", icon="ERROR")
        draw_chat(self.layout, context)


CLASSES = (
    WYSP_OT_send,
    WYSP_OT_say,
    WYSP_OT_interrupt,
    WYSP_OT_continue,
    WYSP_OT_undo_last,
    WYSP_OT_permission,
    WYSP_OT_board_why,
    WYSP_OT_board_show,
    WYSP_PT_chat,
    WYSP_PT_board_side,
)
