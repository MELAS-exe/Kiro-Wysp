"""Screenshots of the in-Blender Wysp panel in each state (developer tool, needs a window, no Core, no network).

    apps\\blender-tutor\\tests\\shoot_panel.ps1   # sets an isolated Blender profile, then runs this file

    blender --python-use-system-env --window-geometry 0 0 1600 900 pumpkin.blend --python gui_panel_states.py -- OUTDIR

The panel is fed the same protocol messages the Core sends (``UiState.handle``), so what you see is what a real
session draws. Nothing connects to the network. Run it with BLENDER_USER_RESOURCE_PATH set to a temp folder so your
own Blender profile is never read or written.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import run_adapter  # noqa: E402

pkg = run_adapter.load_adapter()
pkg.register()
from wysp_tutor import board_tree, ui_panel  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
OUT = Path(argv[0])
ONLY = set(argv[1:])  # optional: only these state names
OUT.mkdir(parents=True, exist_ok=True)

# Only the Wysp tab in the sidebar: without other categories Blender draws no tab bar and shows our panel.
for _name in dir(bpy.types):
    _cls = getattr(bpy.types, _name, None)
    if (
        getattr(_cls, "bl_space_type", "") == "VIEW_3D"
        and getattr(_cls, "bl_region_type", "") == "UI"
        and _name != "WYSP_PT_chat"
        and hasattr(_cls, "bl_rna")
    ):
        try:
            bpy.utils.unregister_class(_cls)
        except (RuntimeError, ValueError):
            pass

session = ui_panel.PanelSession("ws://127.0.0.1:1/ws/ui", narrate=False)  # never started: no socket
session.client.status = "connected"  # lets the operators' poll pass; nothing is sent
session.voice = state_voice = ui_panel.VoicePlayer("http://127.0.0.1:1/api/tts")  # never asked to speak
ui_panel._session = session
state = session.state
state.voice = state_voice

for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        area.spaces.active.show_region_ui = True

bpy.context.window.cursor_warp(300, 300)  # park the mouse over the viewport: no tooltip on the panel
ui_panel._add_banner()  # the viewport callout shown while an approval is pending


def feed(*messages: dict) -> None:
    for m in messages:
        state.handle(m)


def seg(i: int, text: str, marker: str | None = None) -> dict:
    return {
        "type": "narration.segment",
        "segment": {"id": f"g{i}", "turn_id": "t", "index": i, "text": text, "marker": marker, "cues": []},
    }


def node(i: str, label: str, kind: str, prov: str, ref: str | None = None, props=None) -> dict:
    return {
        "id": i,
        "ref": ref,
        "kind": kind,
        "label": label,
        "provenance": prov,
        "confidence": 1.0,
        "props_view": props or [],
        "group": None,
        "badges": [],
        "order": None,
    }


def reset() -> None:
    state.__init__(narrate=False, voice=state_voice)  # a fresh state, same object so the session keeps pointing at it
    state.set_connected(True)
    feed(
        {"type": "session.state", "active_adapter": "blender-1", "model": "llama-3.3-70b", "logging": "full"},
        {
            "type": "adapters.list",
            "adapters": [
                {"adapter_id": "blender-1", "app": {"name": "Blender", "version": "5.2.0"}},
                {"adapter_id": "idea-1", "app": {"name": "IntelliJ IDEA", "version": "2026.2"}},
            ],
        },
        {"type": "status", "state": "idle"},
    )


def s_empty() -> None:
    reset()


def s_chat() -> None:
    reset()
    state.add_user("What does the Subdivision Surface modifier do on my pumpkin?")
    feed(
        seg(1, "Subdivision Surface smooths a mesh by splitting every face into smaller ones."),
        seg(2, "On the Pumpkin it turns the rough 482-vertex shape into a round one.", "likely"),
        {
            "type": "evidence.added",
            "title": "Pumpkin has a Subdivision Surface modifier",
            "scope": "observation",
            "evidence": {"outcomes": [{"ok": True}]},
        },
    )
    state.add_user("And Solidify?")
    feed(seg(3, "Solidify gives the surface a thickness, so the shell is no longer paper thin."))


def s_busy() -> None:
    s_chat()
    feed({"type": "status", "state": "thinking"})


def s_continue() -> None:
    s_chat()
    state.interrupt()
    feed({"type": "status", "state": "idle"})


def s_approval() -> None:
    s_chat()
    feed(
        {"type": "status", "state": "acting"},
        {
            "type": "permission.request",
            "request_id": "r1",
            "title": "Add a Bevel modifier to Candle",
            "target": "blender://object/Candle",
            "risk": "reversible",
            "reversible": True,
            "rationale": "You asked to round the candle's edges. A Bevel modifier does it without changing the mesh.",
            "preview": {"modifier": "BEVEL", "segments": 3, "width": "0.02 m"},
            "voice_allowed": True,
            "can_grant": True,
            "timeout_s": 60,
        },
    )


def s_diagram() -> None:
    reset()
    nodes = [
        node("n1", "Pumpkin", "object", "observed", "blender://object/Pumpkin"),
        node("n2", "Subdivision Surface", "modifier", "observed", "blender://object/Pumpkin/modifier/Subdivision"),
        node("n3", "Solidify", "modifier", "observed", "blender://object/Pumpkin/modifier/Solidify"),
        node("n4", "Smooth surface", "effect", "inferred"),
        node("n5", "What if Solidify came first", "idea", "illustrative"),
    ]
    edges = [
        {"id": "e1", "source": "n1", "target": "n2", "kind": "has", "label": None, "provenance": "observed"},
        {"id": "e2", "source": "n2", "target": "n3", "kind": "then", "label": None, "provenance": "observed"},
        {"id": "e3", "source": "n2", "target": "n4", "kind": "gives", "label": None, "provenance": "inferred"},
    ]
    feed(
        {
            "type": "board.snapshot",
            "board": {
                **{"version": 3, "layout": "stack", "annotations": [], "stale": False},
                "focus": ["n2"],
                "nodes": nodes,
                "edges": edges,
                "steps": [{"id": "s1", "index": 0, "text": "Open the Modifiers tab", "status": "active"}],
            },
        }
    )


def s_lesson() -> None:
    """Lesson in progress, no exercise yet."""
    s_chat()
    feed(
        {
            "type": "lesson.update",
            "lesson_id": "blender-tutor.modifiers.bevel",
            "title": "Round an edge with Bevel",
            "status": "running",
            "step": 2,
            "total": 5,
        }
    )


def s_exercise() -> None:
    """Exercise card with a declared-evidence note in the conversation."""
    reset()
    state.add_user("I think I am done, please check.")
    feed(
        {
            "type": "evidence.added",
            "title": "Give the Bevel 3 segments",
            "scope": "user_action",
            "evidence": {"type": "declared", "outcomes": [{"ok": True}]},
        },
        seg(1, "Thanks. I cannot check that in Blender, so I count it as declared."),
        {
            "type": "lesson.update",
            "lesson_id": "blender-tutor.modifiers.bevel",
            "title": "Round an edge with Bevel",
            "status": "running",
            "step": 4,
            "total": 5,
        },
        {
            "type": "exercise.update",
            "exercise_id": "bevel_segments",
            "prompt": "Give the Candle's Bevel 3 segments.",
            "skills": ["bevel_modifier"],
            "status": "active",
            "attempts": 1,
            "max_attempts": 3,
            "hints_used": 1,
            "hints_total": 2,
        },
    )


def s_menu() -> None:
    s_chat()


def s_offline() -> None:
    reset()
    state.set_connected(False)


STATES = [
    ("empty", s_empty),
    ("chat", s_chat),
    ("busy", s_busy),
    ("continue", s_continue),
    ("approval", s_approval),
    ("diagram", s_diagram),
    ("lesson", s_lesson),
    ("exercise", s_exercise),
    ("offline", s_offline),
    ("menu", s_menu),  # last: the popover stays open until Blender quits
]
queue = [(n, f) for n, f in STATES if not ONLY or n in ONLY]
phase = {"name": "next", "t": time.monotonic(), "cur": None}


def sidebar_override():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "UI":
                        return {"window": window, "screen": window.screen, "area": area, "region": region}
    return None


def redraw() -> None:
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()
            for region in area.regions:
                region.tag_redraw()


def shoot(name: str) -> None:
    path = OUT / f"blender-panel-{name}.png"
    with bpy.context.temp_override(window=bpy.context.window_manager.windows[0]):
        bpy.ops.screen.screenshot(filepath=str(path))
    ov = sidebar_override()
    region = ov["region"] if ov else None
    print("GUI_SHOT", path, "sidebar", (region.x, region.y, region.width, region.height) if region else None)
    if region is not None:  # the crop tool reads this: the sidebar position changes with the window layout
        win = bpy.context.window_manager.windows[0]
        path.with_suffix(".json").write_text(
            json.dumps({"x": region.x, "y": region.y, "w": region.width, "h": region.height, "win_h": win.height}),
            encoding="utf-8",
        )


def step():
    try:
        now = time.monotonic()
        if phase["name"] == "next":
            if not queue:
                print("GUI_DONE")
                ui_panel._session = None
                bpy.ops.wm.quit_blender()
                return None
            name, fn = queue.pop(0)
            fn()
            phase.update(cur=name, name="settle", t=now)
            redraw()
            if name == "menu":
                ov = sidebar_override()
                bpy.context.window.cursor_warp(
                    1245, 757
                )  # the popover opens under the mouse: put it on the "..." button
                with bpy.context.temp_override(**ov):
                    try:
                        print("GUI_MENU", bpy.ops.wm.call_panel(name="WYSP_PT_menu", keep_open=True))
                    except RuntimeError as exc:
                        print("GUI_NOTE menu", exc)
            return 0.8
        if phase["name"] == "settle":
            redraw()
            phase.update(name="shoot", t=now)
            return 0.7
        if phase["name"] == "shoot":
            shoot(phase["cur"])
            phase.update(name="next")
            return 0.3
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        print("GUI_FAIL", repr(exc))
        bpy.ops.wm.quit_blender()
        return None
    return 0.3


_ = board_tree
bpy.app.timers.register(step, first_interval=2.5)
