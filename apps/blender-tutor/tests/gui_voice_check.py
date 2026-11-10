"""GUI check of push-to-talk and of the message field, against tests/fake_voice_core.py (no real microphone).

blender --factory-startup --python-use-system-env scene.blend --python gui_voice_check.py -- OUTDIR ws://127.0.0.1:8799/ws/adapter TOKEN_FILE
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import run_adapter  # noqa: E402

pkg = run_adapter.load_adapter()
pkg.register()
from wysp_tutor import telemetry, ui_panel  # noqa: E402
from wysp_tutor.runtime import BlenderAdapter  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1 :]
OUT, URL, TOKEN = Path(argv[0]), argv[1], Path(argv[2]).read_text(encoding="utf-8").strip()
OUT.mkdir(parents=True, exist_ok=True)

telemetry.configure("full")
adapter = BlenderAdapter()
adapter.make_client(URL, TOKEN).start()
adapter.watcher.start()
pkg._adapter = adapter
ui_panel.start(URL, narrate=True, speak=False, listen=True, token=TOKEN)
bpy.app.timers.register(pkg._pump, first_interval=0.05, persistent=True)
for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        area.spaces.active.show_region_ui = True
bpy.utils.unregister_class(ui_panel.WYSP_PT_chat)
ui_panel.WYSP_PT_chat.bl_category = "Item"  # scripts cannot switch sidebar tabs: show the chat in the open one
bpy.utils.register_class(ui_panel.WYSP_PT_chat)

phase = {"name": "connect", "t": time.monotonic(), "n": 0}


def shoot(tag: str) -> None:
    win = bpy.context.window_manager.windows[0]
    with bpy.context.temp_override(window=win, screen=win.screen):
        bpy.ops.screen.screenshot(filepath=str(OUT / f"{phase['n']:02d}_{tag}.png"))
    phase["n"] += 1


def talk() -> None:
    win = bpy.context.window_manager.windows[0]
    with bpy.context.temp_override(window=win, screen=win.screen):
        bpy.ops.wysp.talk("EXEC_DEFAULT")


def step():
    s = ui_panel.get()
    now, name = time.monotonic(), phase["name"]
    wm = bpy.context.window_manager
    try:
        if name == "connect":
            if s and s.state.connected and adapter.client.connected:
                wm.wysp_input = "typed hello"  # what pressing Enter in the field does
                phase.update(name="typed", t=now)
            return 0.2
        if name == "typed" and now - phase["t"] > 0.6:
            print(
                "GUI_FIELD after send:",
                repr(wm.wysp_input),
                "| sent:",
                [t["text"] for t in s.state.transcript if t["kind"] == "user"],
            )
            talk()  # press
            phase.update(name="listening", t=now)
        elif name == "listening" and now - phase["t"] > 0.8:
            print("GUI_MIC while held:", s.mic.state)
            shoot("listening")
            talk()  # release
            phase.update(name="heard", t=now)
        elif name == "heard" and now - phase["t"] > 3.0:
            users = [(t["text"], t["source"]) for t in s.state.transcript if t["kind"] == "user"]
            print("GUI_MIC after release:", s.mic.state, "| user messages:", users)
            print("GUI_SAID:", [t["text"] for t in s.state.visible_transcript() if t["kind"] == "wysp"])
            shoot("answered")
            print("GUI_DONE")
            ui_panel.stop()
            adapter.shutdown()
            bpy.ops.wm.quit_blender()
            return None
        return 0.1
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        print("GUI_FAIL", repr(exc))
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(step, first_interval=2.0)
