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
import sys
import textwrap

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator, Panel

from . import board_tree, ui_icons
from .ui_client import PanelClient
from .ui_listen import VoiceInput
from .ui_state import STATUS_TEXT, UiState, preview_lines, tail_start
from .ui_voice import VoicePlayer, tts_url

log = logging.getLogger("wysp.blender.ui")

STATUS_ICONS = {
    "idle": "DOT",
    "thinking": "SORTTIME",
    "acting": "PLAY",
    "speaking": "PLAY_SOUND",
    "offline": "UNLINKED",
}
STEP_ICONS = {"pending": "LAYER_USED", "active": "RIGHTARROW", "done": "CHECKMARK", "failed": "CANCEL"}
RISK_ICONS = {"read_only": "HIDE_OFF", "ui_state": "WINDOW", "reversible": "LOOP_BACK", "irreversible": "ERROR"}
RISK_LABELS = {
    "read_only": "reads only",
    "ui_state": "changes the view only",
    "reversible": "reversible change",
    "irreversible": "cannot be undone",
}
# Same provenance language as the node tree and the browser Panel: observed (eye), likely (?), example (i).
PROVENANCE_ICONS = {"observed": "HIDE_OFF", "inferred": "QUESTION", "illustrative": "INFO"}
USER_INDENT_PX = 60  # extra width taken by the indent and box of a user message
# Average width of a character per unit of UI scale. Measured on Blender 5.2 at 5.8 px; 6.8 keeps a margin so that
# Blender never cuts a line with "...".
CHAR_PX = 6.8


def ui_url(adapter_url: str) -> str:
    base = adapter_url.rsplit("/ws/", 1)[0] if "/ws/" in adapter_url else adapter_url.rstrip("/")
    return base + "/ws/ui"


class PanelSession:
    def __init__(
        self, url: str, narrate: bool = True, voice: VoicePlayer | None = None, mic: VoiceInput | None = None
    ) -> None:
        self.client = PanelClient(url)
        self.voice = voice
        self.mic = mic  # push-to-talk through the Core
        self._mic_state = "idle"
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
            try:
                replies = self.state.handle(msg)
            except Exception:  # noqa: BLE001 - one odd message must not stop the panel
                log.exception("cannot apply Core message %r", t)
                replies = []
            for reply in replies:
                self.client.send(reply)
            if t == "session.state":
                self._sync_logging_prop()
                if self.voice is not None and self.state.session.get("lang"):
                    self.voice.lang = self.state.session["lang"]
        for reply in self.state.tick():
            self.client.send(reply)
        self._tick_mic()
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

    def talk_start(self) -> None:
        """Push-to-talk pressed: stop Wysp talking (barge-in) and open the microphone."""
        if self.mic is None:
            self.state.note("Speech input is off (extension preferences).", "info")
            return
        if self.state.status != "idle" or self.state.queued_segments():
            self.send(self.state.interrupt())  # barge-in: talking over Wysp stops it, as in the browser Panel
        else:
            self.state.cancel_narration()
        if self.voice is not None:
            self.voice.stop()
        self.mic.start()
        self._mic_changed()

    def talk_stop(self, cancel: bool = False) -> None:
        if self.mic is None:
            return
        if cancel:
            self.mic.cancel()
        else:
            self.mic.stop()
        self._mic_changed()

    def _mic_changed(self) -> None:
        if self.mic is not None and self.mic.state != self._mic_state:
            self._mic_state = self.mic.state
            self.state.revision += 1
            _redraw_viewports()

    def _tick_mic(self) -> None:
        if self.mic is None:
            return
        for r in self.mic.poll():
            if not r["ok"]:
                self.state.note(f"Microphone: {r['error']}", "error")
            elif r["kind"] == "stop":
                text = str(r.get("text", "")).strip()
                if not text:
                    self.state.note("I did not hear anything. Hold the key, speak, then release it.", "info")
                for message in self.state.route_transcript(text):
                    self.client.send(message)
        self._mic_changed()

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


def start(adapter_url: str, narrate: bool, speak: bool = True, listen: bool = True, token: str = "") -> None:
    global _session
    stop()
    voice = VoicePlayer(tts_url(adapter_url)) if speak else None
    mic = VoiceInput(adapter_url, token) if listen and token else None
    _session = PanelSession(ui_url(adapter_url), narrate=narrate or speak, voice=voice, mic=mic)
    try:  # keep the menu's Voice switch and the state in step after a reconnect
        _session.state.voice_on = bool(bpy.context.window_manager.wysp_voice_on)
    except AttributeError:
        pass
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
    region = bpy.context.region
    if s is None or region is None:
        return
    mic = s.mic.state if s.mic is not None else "idle"
    if mic in ("starting", "listening", "transcribing"):
        text = {
            "starting": "Opening the microphone…",
            "listening": "Listening… release Alt+Space (or click the red button) to send",
            "transcribing": "Understanding what you said…",
        }[mic]
        try:
            import gpu

            from .highlight import draw_callout

            gpu.state.blend_set("ALPHA")
            scale = bpy.context.preferences.system.ui_scale
            draw_callout(region, text, x=16 * scale, top=110 * scale)
            gpu.state.blend_set("NONE")
        except Exception:  # noqa: BLE001
            _banner_failed()
    req = s.state.permission
    if not req:
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
        _banner_failed()


def _banner_failed() -> None:
    """Log a drawing failure once (a draw handler runs on every redraw: do not flood the log)."""
    if not _banner.get("failed"):
        _banner["failed"] = True
        log.exception("the viewport banner cannot be drawn")


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
    # Blender writes the edited text back into the field after this callback returns, so clear it just after.
    bpy.app.timers.register(_clear_input, first_interval=0.01)
    _session.state.cancel_narration()  # like the browser Panel: a new message stops what Wysp was saying
    if _session.send({"type": "user.message", "text": text[:4000], "source": "typed"}):
        _session.state.add_user(text)


def _clear_input() -> None:
    wm = bpy.context.window_manager
    if getattr(wm, "wysp_input", ""):
        # Plain assignment: WindowManager properties are not stored as ID properties, so wm["..."] = "" does
        # nothing. It runs the update callback again, which returns at once for an empty text.
        wm.wysp_input = ""
        _redraw_panels()
    return None


def _on_logging(self, context) -> None:
    if _session is None or _session._syncing_logging:
        return
    _session.send({"type": "settings.update", "logging": self.wysp_logging})


def _on_voice(self, context) -> None:
    if _session is not None:
        _session.state.set_voice(bool(self.wysp_voice_on))


def register_props() -> None:
    wm = bpy.types.WindowManager
    wm.wysp_voice_on = BoolProperty(  # type: ignore[attr-defined]
        name="Voice",
        description="Read Wysp's sentences aloud. Off keeps the captions at reading pace",
        default=True,
        update=_on_voice,
        options={"SKIP_SAVE"},
    )
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
    for name in ("wysp_input", "wysp_logging", "wysp_voice_on"):
        if hasattr(wm, name):
            delattr(wm, name)


# ------------------------------------------------------------------------- operators
class _SessionOperator(Operator):
    @classmethod
    def poll(cls, context):
        return _session is not None and _session.client.connected


class WYSP_OT_view(Operator):
    """Switch between the conversation and the diagram (panel state only, no message to the Core)."""

    bl_idname = "wysp.view"
    bl_label = "View"
    bl_description = "Show the conversation or the diagram"
    view: StringProperty()  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context):
        return _session is not None

    def execute(self, context):
        _session.state.set_view(self.view)
        return {"FINISHED"}


class WYSP_OT_activate_adapter(_SessionOperator):
    bl_idname = "wysp.activate_adapter"
    bl_label = "Look at this application"
    bl_description = "Choose which connected application Wysp looks at"
    adapter_id: StringProperty()  # type: ignore[valid-type]

    def execute(self, context):
        _session.send({"type": "adapter.activate", "adapter_id": self.adapter_id})
        return {"FINISHED"}


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
# The layout mirrors the browser Panel (panel/src): one slim top row, then the conversation or the diagram.
# Blender draws sidebar panels with the user's theme, so brand colour only comes from the mascot icon.
def _wrap(text: str, context, indent: int = 0) -> list[str]:
    width = context.region.width if context.region else 300
    scale = context.preferences.system.ui_scale  # effective scale: user setting times monitor DPI
    chars = max(14, int((width - (44 + indent) * scale) / (CHAR_PX * scale)))
    return textwrap.wrap(text, chars) or [""]


def _draw_text(layout, text: str, context, icon: str = "NONE", indent: int = 0) -> int:
    """Draw wrapped text (Blender labels do not wrap). Returns the number of lines."""
    col = layout.column(align=True)
    lines = _wrap(text, context, indent)
    for i, line in enumerate(lines):
        col.label(text=line, icon=(icon if i == 0 else "BLANK1") if icon != "NONE" else "NONE")
    return len(lines)


def _line_budget(context, extra: float = 0.0) -> float:
    """How many text lines of conversation fit above the composer (the sidebar cannot be scrolled by a script).

    `extra` is what the panel already draws around the conversation (approval card, steps, Stop row...).
    """
    region = context.region
    if region is None:
        return 12
    line_px = 21 * context.preferences.system.ui_scale
    return max(3.0, region.height / line_px - 4.0 - extra)


def link_info() -> tuple[str, str]:
    """State of Blender's link to the Core (the adapter connection), owned by the add-on package."""
    pkg = sys.modules.get(__package__ or "")
    client = getattr(getattr(pkg, "_adapter", None), "client", None)
    if client is None:
        return "not connected", ""
    return str(client.status), str(client.last_error or "")


def draw_header(layout, context, show_switch: bool = True) -> None:
    """The only chrome: mascot, status, the Chat/Diagram switch and the "..." menu."""
    s = _session
    st = s.state if s is not None else None
    state = st.display_status if st is not None else "offline"
    switch = show_switch and st is not None and st.has_diagram
    row = layout.row(align=True)
    split = row.split(factor=0.42 if switch else 0.7, align=True)
    left = split.row(align=True)
    left.label(text="", **ui_icons.icon_args("mark"))
    left.label(text=st.status_text if st is not None else STATUS_TEXT["offline"], icon=STATUS_ICONS[state])
    right = split.row(align=True)
    right.alignment = "RIGHT"
    if switch:
        seg = right.row(align=True)
        view = st.effective_view
        seg.operator("wysp.view", text="Chat", depress=view == "chat").view = "chat"
        seg.operator("wysp.view", text="Diagram", depress=view == "board").view = "board"
    right.popover(panel="WYSP_PT_menu", text="", icon="THREE_DOTS")


def draw_hello(layout, title: str, hint: str) -> None:
    """Empty state: the large mascot with a short invitation, like the browser Panel's first screen."""
    col = layout.column(align=True)
    col.separator(factor=1.5)
    row = col.row()
    row.alignment = "CENTER"
    big = ui_icons.icon_id("mark_big")
    if big:
        row.template_icon(icon_value=big, scale=7)
    else:
        row.label(text="", icon="LIGHT_SUN")
    col.separator(factor=0.5)
    for text, dim in ((title, False), (hint, True)):
        line = col.row()
        line.alignment = "CENTER"
        line.active = not dim
        line.label(text=text)
    col.separator(factor=1.5)


def risk_badge(req: dict) -> tuple[str, str]:
    """(icon, short text) for the permission card, same wording as PermissionDialog.tsx."""
    risk = req.get("risk", "")
    return RISK_ICONS.get(risk, "QUESTION"), RISK_LABELS.get(risk, str(risk).replace("_", " "))


def draw_permission(layout, context, req: dict) -> None:
    irreversible = req.get("risk") == "irreversible"
    box = layout.box()
    box.alert = irreversible
    icon, badge = risk_badge(req)
    box.label(text=badge.capitalize(), icon=icon)
    _draw_text(box, req.get("title", ""), context)
    if req.get("target"):
        _draw_text(box, f"on {req['target']}", context)
    why = req.get("rationale") or "Wysp would like to make this change in Blender."
    dim = box.column(align=True)
    dim.active = False
    for line in _wrap(why, context):
        dim.label(text=line)
    if req.get("preview") is not None:
        pv = box.box()
        pv.scale_y = 0.85
        for line in preview_lines(req["preview"]):
            pv.label(text=line)
    note = "You can undo this afterwards." if req.get("reversible") else "Wysp cannot undo this."
    if not req.get("voice_allowed", True):
        note += " It needs a click."
    small = box.row()
    small.active = False
    small.label(text=note)
    row = box.row(align=True)
    row.scale_y = 1.3
    row.operator("wysp.permission", text="Deny", icon="X").decision = "deny"
    ok = row.row(align=True)
    ok.alert = irreversible
    ok.operator(
        "wysp.permission", text="Approve and apply" if irreversible else "Approve", icon="CHECKMARK"
    ).decision = "approve"
    if req.get("can_grant") and req.get("reversible"):
        box.operator("wysp.permission", text="Allow for this lesson", icon="UNLOCKED").decision = "grant_lesson"


def draw_steps(layout, context, steps: list[dict]) -> None:
    if not steps:
        return
    box = layout.box()
    box.label(text="Your steps", icon="SEQUENCE")
    for s in steps:
        _draw_text(
            box, f"{s.get('index', 0) + 1}. {s.get('text', '')}", context, STEP_ICONS.get(s.get("status"), "DOT")
        )


def _item_lines(item: dict, context) -> float:
    gap = 0.4  # the separator after each item
    if item["kind"] == "user":
        return len(_wrap(item["text"], context, USER_INDENT_PX)) + 0.6 + gap  # the box adds padding
    return len(_wrap(item.get("text", ""), context)) + gap


def _around_lines(st: UiState) -> float:
    """Rough height, in text lines, of everything drawn above/below the conversation besides the composer."""
    extra = 0.0
    if st.show_lesson_card:
        extra += 3.0 + (7.0 if st.active_exercise else 0.0)
    if st.steps:
        extra += 1.5 + 1.3 * len(st.steps)
    if st.clarification:
        extra += 2.5 + 1.2 * len(st.clarification["options"][:6])
    if st.busy:
        extra += 1.2
    if st.show_stop or st.show_continue:
        extra += 1.3
    return extra


def draw_transcript(layout, context, state: UiState) -> None:
    """The conversation, oldest first with the newest next to the composer, like the browser Panel."""
    items = state.visible_transcript()
    budget = _line_budget(context, _around_lines(state))
    first = tail_start([_item_lines(i, context) for i in items], budget)
    col = layout.column(align=False)
    if first > 0:
        hidden = col.row()
        hidden.active = False
        hidden.label(text=f"{first} earlier message{'s' if first != 1 else ''}", icon="TRIA_UP")
    for it in items[first:]:
        kind = it["kind"]
        if kind == "user":  # a boxed, indented bubble
            split = col.split(factor=0.14)
            split.label(text="")
            inner = split.box().column(align=True)
            for line in _wrap(it["text"], context, USER_INDENT_PX):
                inner.label(text=line)
        elif kind == "wysp":
            seg = it["segment"]
            marker = f"({seg['marker']}) " if seg.get("marker") else ""
            block = col.column(align=True)
            block.active = it["state"] != "cancelled"
            for line in _wrap(f"{marker}{it['text']}", context):
                block.label(text=line)
        elif kind == "evidence":
            label = UiState.evidence_label(it)
            declared = it.get("etype") == "declared"
            row = col.column(align=True)
            row.active = False
            for i, line in enumerate(_wrap(f"{label}: {it['text']}", context)):
                icon = "QUESTION" if declared else ("CHECKMARK" if it.get("ok") else "CANCEL")
                row.label(text=line, icon=icon if i == 0 else "BLANK1")
        else:
            row = col.column(align=True)
            row.active = False
            row.alert = it.get("tone") == "error"
            for line in _wrap(it["text"], context):
                row.label(text=line)
        col.separator(factor=0.4)


def draw_composer(layout, context, s: PanelSession) -> None:
    mic = s.mic.state if s.mic is not None else None
    listening = mic in ("starting", "listening")
    if listening:
        hint = "Listening…"
    elif mic == "transcribing":
        hint = "Understanding…"
    else:
        hint = "Ask about your scene"
    row = layout.row(align=True)
    row.scale_y = 1.25
    row.prop(context.window_manager, "wysp_input", text="", placeholder=hint)
    if mic is not None:
        btn = row.row(align=True)
        if mic == "transcribing":
            btn.enabled = False
            btn.operator("wysp.talk", text="", icon="SORTTIME")
        else:
            btn.alert = listening
            btn.operator("wysp.talk", text="", icon="REC", depress=listening)
        if listening:
            row.operator("wysp.talk_cancel", text="", icon="X")
    row.operator("wysp.send", text="", icon="TRIA_UP")


def draw_lesson_card(layout, context, st: UiState) -> None:
    """Lesson progress and the exercise Wysp is watching (mirrors ExerciseCard.tsx). Buttons only say what you could type."""
    if not st.show_lesson_card:
        return
    box = layout.box()
    lesson = st.lesson
    if lesson:
        head = box.row()
        head.label(text=str(lesson.get("title") or "Lesson"), icon="BOOKMARKS")
        step, total = int(lesson.get("step", 0)), int(lesson.get("total", 0))
        dim = box.row()
        dim.active = False
        dim.label(text=f"Step {step} of {total}")
        if total > 0:
            box.progress(factor=min(1.0, step / total), type="BAR", text="")
    ex = st.active_exercise
    if ex:
        _draw_text(box, str(ex.get("prompt", "")), context, "PINNED")
        dim = box.column(align=True)
        dim.active = False
        for line in _wrap("Wysp checks it in Blender.", context):
            dim.label(text=line)
        dim.label(
            text=f"Attempts {ex.get('attempts', 0)}/{ex.get('max_attempts', 0)} · "
            f"hints {ex.get('hints_used', 0)}/{ex.get('hints_total', 0)}"
        )
        row = box.row(align=True)
        hint = row.row(align=True)
        hint.enabled = st.can_hint
        hint.operator("wysp.say", text="Hint", icon="LIGHT").text = "Give me a hint."
        row.operator("wysp.say", text="I'm done", icon="CHECKMARK").text = "I think I am done, please check."


def draw_chat_body(layout, context, s: PanelSession) -> None:
    st = s.state
    if st.permission:
        draw_permission(layout, context, st.permission)
    draw_lesson_card(layout, context, st)
    draw_steps(layout, context, st.steps)
    if st.is_empty and not st.busy and not st.permission:
        draw_hello(layout, "Ask about your scene", "Hold Alt+Space to talk")
    elif not st.permission:  # like the browser Panel's dialog, the approval card covers the conversation
        draw_transcript(layout, context, st)
    if st.clarification:
        box = layout.box()
        _draw_text(box, st.clarification["question"], context, "QUESTION")
        for opt in st.clarification["options"][:6]:
            box.operator("wysp.say", text=opt[:60]).text = opt
    if st.busy:
        wait = layout.row()
        wait.active = False
        wait.label(text=f"{st.wait_text}…" if st.wait_text else "…", icon="SORTTIME")
    if st.show_stop or st.show_continue:
        quick = layout.row()
        if st.show_stop:
            quick.operator("wysp.interrupt", text="Stop", icon="PAUSE")
        else:
            quick.operator("wysp.resume", text="Continue", icon="PLAY")
    draw_composer(layout, context, s)


def draw_diagram(layout, context, s: PanelSession) -> None:
    """The board as a compact list (the full node view opens in a Node Editor)."""
    st = s.state
    if st.permission:
        draw_permission(layout, context, st.permission)
    draw_steps(layout, context, st.steps)
    rows, hidden = st.diagram_rows()
    if st.board.get("stale"):
        layout.label(text="The board may be out of date", icon="ERROR")
    col = layout.column(align=True)
    for r in rows:
        box = col.box() if r["focused"] else col.column(align=True)
        line = box.split(factor=0.7 if r["can_show"] else 0.84, align=True)
        label = line.row()
        label.active = r["provenance"] != "illustrative"
        label.label(text=r["text"], icon=PROVENANCE_ICONS.get(r["provenance"], "DOT"))
        btns = line.row(align=True)
        btns.alignment = "RIGHT"
        if r["can_show"]:
            btns.operator("wysp.board_show", text="", icon="RESTRICT_SELECT_OFF").node_id = r["id"]
        btns.operator("wysp.board_why", text="", icon="QUESTION").node_id = r["id"]
        if r["links"]:
            sub = box.row()
            sub.active = False
            sub.label(text=("→ " + ", ".join(r["links"]))[:60], icon="BLANK1")
    if hidden:
        more = layout.row()
        more.active = False
        more.label(text=f"+{hidden} more in the board editor")
    draw_board_legend(layout)
    row = layout.row(align=True)
    row.operator("wysp.board_open", text="Open in editor", icon="NODETREE")
    row.operator("wysp.board_here", text="", icon="SEQ_STRIP_DUPLICATE")


def draw_board_legend(layout) -> None:
    col = layout.box().column(align=True)
    col.active = False
    col.label(text="observed in Blender", icon=PROVENANCE_ICONS["observed"])
    col.label(text="likely (inferred)", icon=PROVENANCE_ICONS["inferred"])
    col.label(text="example, not your scene", icon=PROVENANCE_ICONS["illustrative"])


def draw_offline(layout, s: PanelSession | None) -> None:
    status, error = link_info()
    hint = f"Blender link: {status}" if status != "connected" else "Waiting for the Wysp Core…"
    draw_hello(layout, "Wysp is offline", hint)
    error = error or (s.client.last_error if s is not None and s.client.last_error else "")
    if error:
        row = layout.row()
        row.active = False
        row.label(text=str(error)[:60], icon="ERROR")
    if status != "connected":
        row = layout.row()
        row.scale_y = 1.3
        row.operator("wysp.connect", text="Connect", icon="LINKED")


def draw_main(layout, context, side: bool = False) -> None:
    """Everything the sidebar tab shows."""
    s = _session
    draw_header(layout, context, show_switch=not side)
    if s is None or not s.state.connected:
        draw_offline(layout, s)
        return
    if not side and s.state.effective_view == "board":
        draw_diagram(layout, context, s)
    else:
        draw_chat_body(layout, context, s)


class WYSP_PT_chat(Panel):
    """The Wysp tab in the 3D Viewport sidebar. No title bar: the slim top row is the whole header."""

    bl_label = "Wysp"
    bl_idname = "WYSP_PT_chat"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Wysp"
    bl_options = {"HIDE_HEADER"}  # noqa: RUF012

    def draw(self, context):
        draw_main(self.layout, context)


class WYSP_PT_menu(Panel):
    """The "..." popover: the rest of the settings, out of the way."""

    bl_label = "Wysp"
    bl_idname = "WYSP_PT_menu"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"

    def draw(self, context):
        layout = self.layout
        s = _session
        wm = context.window_manager
        layout.ui_units_x = 14
        st = s.state if s is not None else None
        if s is not None and st.connected:
            layout.label(text="Looking at")
            col = layout.column(align=True)
            if st.adapters:
                for a in st.adapters:
                    on = a.get("adapter_id") == st.session.get("active_adapter")
                    op = col.operator("wysp.activate_adapter", text=st.app_label(a), depress=on)
                    op.adapter_id = str(a.get("adapter_id", ""))
            else:
                col.label(text="no application connected")
            layout.separator()
            layout.label(text="Logs")
            layout.prop(wm, "wysp_logging", expand=True)
            if s.voice is not None:
                layout.prop(wm, "wysp_voice_on", text="Voice")
            else:
                dim = layout.row()
                dim.active = False
                dim.label(text="Voice is off (preferences)")
            layout.operator("wysp.undo_last", text="Undo Wysp's last change", icon="LOOP_BACK")
            layout.operator("wysp.board_open", text="Open the diagram editor", icon="NODETREE")
            model = st.session.get("model") or st.session.get("llm")
            if model:
                foot = layout.row()
                foot.active = False
                foot.label(text=f"Model: {model}"[:40])
            layout.separator()
        status, _error = link_info()
        row = layout.row(align=True)
        row.operator("wysp.connect", text="Connect", icon="LINKED")
        row.operator("wysp.disconnect", text="Disconnect", icon="UNLINKED")
        if status != "connected":
            dim = layout.row()
            dim.active = False
            dim.label(text=f"Blender link: {status}")


class WYSP_PT_board_side(Panel):
    """Sidebar of the board's Node Editor: legend, steps and chat."""

    bl_label = "Wysp"
    bl_idname = "WYSP_PT_board_side"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Wysp"
    bl_options = {"HIDE_HEADER"}  # noqa: RUF012

    @classmethod
    def poll(cls, context):
        return getattr(context.space_data, "tree_type", "") == board_tree.TREE_TYPE

    def draw(self, context):
        draw_board_legend(self.layout)
        draw_main(self.layout, context, side=True)


class WYSP_OT_talk(_SessionOperator):
    """Push-to-talk. From the keyboard: hold the key while speaking. From the button: click, speak, click."""

    bl_idname = "wysp.talk"
    bl_label = "Talk to Wysp"
    bl_description = "Speak to Wysp: hold Alt+Space while talking, or click to start and click again to send"

    _key: str | None = None

    def invoke(self, context, event):
        if getattr(event, "is_repeat", False):
            return {"CANCELLED"}  # keyboard auto-repeat while the key is held is not a second press
        mic = _session.mic
        if mic is not None and mic.active:  # second click: send what was said
            _session.talk_stop()
            return {"FINISHED"}
        _session.talk_start()
        if event.type in ("LEFTMOUSE", "RIGHTMOUSE", "MIDDLEMOUSE") or mic is None:
            return {"FINISHED"}  # button: toggle mode
        self._key = event.type
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if _session is None or _session.mic is None or not _session.mic.active:
            return {"FINISHED"}
        if event.type == "ESC" and event.value == "PRESS":
            _session.talk_stop(cancel=True)
            return {"CANCELLED"}
        if event.type == self._key and event.value == "RELEASE":
            _session.talk_stop()
            return {"FINISHED"}
        if event.type == self._key:
            return {"RUNNING_MODAL"}  # swallow auto-repeat presses so they do not reach the keymap again
        return {"PASS_THROUGH"}

    def execute(self, context):  # from a script or the F3 search: toggle
        mic = _session.mic
        if mic is not None and mic.active:
            _session.talk_stop()
        else:
            _session.talk_start()
        return {"FINISHED"}


class WYSP_OT_talk_cancel(_SessionOperator):
    bl_idname = "wysp.talk_cancel"
    bl_label = "Cancel"
    bl_description = "Stop listening and send nothing"

    def execute(self, context):
        _session.talk_stop(cancel=True)
        return {"FINISHED"}


_keymaps: list = []


def register_keymaps() -> None:
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:  # background mode
        return
    for name, space in (("3D View", "VIEW_3D"), ("Node Editor", "NODE_EDITOR")):
        km = kc.keymaps.new(name=name, space_type=space)
        kmi = km.keymap_items.new("wysp.talk", "SPACE", "PRESS", alt=True)
        _keymaps.append((km, kmi))


def unregister_keymaps() -> None:
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keymaps.clear()


CLASSES = (
    WYSP_OT_talk,
    WYSP_OT_talk_cancel,
    WYSP_OT_view,
    WYSP_OT_activate_adapter,
    WYSP_OT_send,
    WYSP_OT_say,
    WYSP_OT_interrupt,
    WYSP_OT_continue,
    WYSP_OT_undo_last,
    WYSP_OT_permission,
    WYSP_OT_board_why,
    WYSP_OT_board_show,
    WYSP_PT_menu,
    WYSP_PT_chat,
    WYSP_PT_board_side,
)
