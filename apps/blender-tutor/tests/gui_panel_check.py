"""GUI check of the in-Blender Panel and board (developer tool, needs a window and a running Core).

blender --python-use-system-env --window-geometry 0 0 1600 900 scene.blend --python gui_panel_check.py -- \
    OUTDIR ws://127.0.0.1:8799/ws/adapter TOKEN_FILE "message to send"

Connects like the add-on does (adapter + Panel client), sends one message, waits for the answer,
opens the board in a new window and saves screenshots of every window.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import run_adapter  # noqa: E402

pkg = run_adapter.load_adapter()
pkg.register()
from wysp_tutor import board_tree, telemetry, ui_panel  # noqa: E402
from wysp_tutor.runtime import BlenderAdapter  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1 :]
OUT, URL, TOKEN_FILE = Path(argv[0]), argv[1], argv[2]
MESSAGES = argv[3].split("||")  # several messages, sent a few seconds apart
MESSAGE = MESSAGES[0]
OUT.mkdir(parents=True, exist_ok=True)

telemetry.configure("full")
adapter = BlenderAdapter()
adapter.make_client(URL, Path(TOKEN_FILE).read_text(encoding="utf-8").strip()).start()
adapter.watcher.start()
pkg._adapter = adapter
ui_panel.start(URL, narrate=True, speak=True)
bpy.app.timers.register(pkg._pump, first_interval=0.05, persistent=True)

for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        area.spaces.active.show_region_ui = True

# Scripts cannot switch sidebar tabs, so show the chat under the default "Item" tab for the screenshot.
bpy.utils.unregister_class(ui_panel.WYSP_PT_chat)
ui_panel.WYSP_PT_chat.bl_category = "Item"
bpy.utils.register_class(ui_panel.WYSP_PT_chat)
# Same for the board window: show the Wysp sidebar panel where the node-group panels would be.
for _name in dir(bpy.types):
    _cls = getattr(bpy.types, _name, None)
    if getattr(_cls, "bl_space_type", "") == "NODE_EDITOR" and getattr(_cls, "bl_category", "") == "Group":
        try:
            bpy.utils.unregister_class(_cls)
        except RuntimeError:
            pass
bpy.utils.unregister_class(ui_panel.WYSP_PT_board_side)
ui_panel.WYSP_PT_board_side.bl_category = "Group"
bpy.utils.register_class(ui_panel.WYSP_PT_board_side)
for _name in [n for n in dir(bpy.types) if n.startswith("VIEW3D_PT_") and "transform" in n.lower()]:
    try:  # make room for the chat in the screenshot
        bpy.utils.unregister_class(getattr(bpy.types, _name))
        print("GUI_NOTE hid", _name)
    except (AttributeError, RuntimeError) as exc:
        print("GUI_NOTE cannot hide", _name, exc)

phase = {"name": "wait_connect", "t": time.monotonic(), "shots": 0}


def shoot(tag: str) -> None:
    wm = bpy.context.window_manager
    for i, win in enumerate(wm.windows):
        path = OUT / f"{phase['shots']:02d}_{tag}_w{i}.png"
        with bpy.context.temp_override(window=win, screen=win.screen):
            bpy.ops.screen.screenshot(filepath=str(path))
        print("GUI_SHOT", path)
    phase["shots"] += 1


def step():
    s = ui_panel.get()
    now = time.monotonic()
    try:
        if phase["name"] == "wait_connect":
            if s and s.state.connected and adapter.client.connected:
                print("GUI_CONNECTED", s.state.session.get("llm"), s.state.session.get("logging"))
                s.send({"type": "user.message", "text": MESSAGE, "source": "typed"})
                s.state.add_user(MESSAGE)
                phase.update(name="wait_answer", t=now)
            elif now - phase["t"] > 20:
                print("GUI_FAIL not connected", adapter.client.status, s.client.status if s else None)
                bpy.ops.wm.quit_blender()
                return None
            return 0.2
        if phase["name"] == "wait_answer":
            if len(MESSAGES) > 1 and now - phase["t"] > 6:
                nxt = MESSAGES.pop(1)
                s.state.cancel_narration()  # what the sidebar's Send does
                s.send({"type": "user.message", "text": nxt, "source": "typed"})
                s.state.add_user(nxt)
                phase["t"] = now
                return 0.3
            if now - phase["t"] > float(os.environ.get("WYSP_TEST_WAIT", "9")):
                items = [(i["kind"], i.get("text", "")[:50], i.get("state")) for i in s.state.transcript]
                print("GUI_TRANSCRIPT", items)
                print(
                    "GUI_STATE received",
                    s.received,
                    "status",
                    s.state.status,
                    "permission",
                    s.state.permission,
                    "client",
                    s.client.status,
                    s.client.last_error,
                    "inbox",
                    s.client.inbox.qsize(),
                )
                print("GUI_BOARD nodes", len(s.state.board["nodes"]), "tree nodes", len(board_tree.get_tree().nodes))
                shoot("chat")
                with bpy.context.temp_override(window=bpy.context.window_manager.windows[0]):
                    print("GUI_BOARD_OPEN", board_tree.open_window(bpy.context))
                phase.update(name="board", t=now)
            return 0.3
        if phase["name"] == "board":
            if now - phase["t"] > 2.5:
                for win in bpy.context.window_manager.windows[1:]:
                    for area in win.screen.areas:
                        if area.ui_type == board_tree.TREE_TYPE:
                            with bpy.context.temp_override(window=win, area=area, region=area.regions[-1]):
                                try:
                                    bpy.ops.node.view_all()
                                except RuntimeError as exc:
                                    print("GUI_NOTE view_all", exc)
                phase.update(name="shoot_board", t=now)
            return 0.3
        if phase["name"] == "shoot_board":
            if now - phase["t"] > 1.0:
                shoot("board")
                print("GUI_LOG", telemetry.tm.path)
                print("GUI_DONE")
                ui_panel.stop()
                adapter.shutdown()
                bpy.ops.wm.quit_blender()
                return None
            return 0.3
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        print("GUI_FAIL", repr(exc))
        bpy.ops.wm.quit_blender()
        return None
    return 0.3


bpy.app.timers.register(step, first_interval=2.0)
