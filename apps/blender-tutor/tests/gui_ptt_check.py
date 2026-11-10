"""Hold-to-talk through the real keymap: simulated Alt+Space press, auto-repeats, release.

blender --enable-event-simulate --factory-startup --python-use-system-env scene.blend --python gui_ptt_check.py -- \
    ws://127.0.0.1:8799/ws/adapter TOKEN_FILE

Needs tests/fake_voice_core.py on that port. --enable-event-simulate blocks real input: only for a test Blender.
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
from wysp_tutor import ui_panel  # noqa: E402
from wysp_tutor.runtime import BlenderAdapter  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1 :]
URL, TOKEN = argv[0], Path(argv[1]).read_text(encoding="utf-8").strip()
adapter = BlenderAdapter()
adapter.make_client(URL, TOKEN).start()
pkg._adapter = adapter
ui_panel.start(URL, narrate=True, speak=False, listen=True, token=TOKEN)
bpy.app.timers.register(pkg._pump, first_interval=0.05, persistent=True)

win = bpy.context.window_manager.windows[0]
view = next(a for a in win.screen.areas if a.type == "VIEW_3D")
X, Y = view.x + view.width // 2, view.y + view.height // 2
phase = {"name": "connect", "t": time.monotonic(), "states": []}


def sim(value: str) -> None:
    win.event_simulate(type="MOUSEMOVE", value="NOTHING", x=X, y=Y)
    win.event_simulate(type="SPACE", value=value, x=X, y=Y, alt=True)


def step():
    s = ui_panel.get()
    now, name = time.monotonic(), phase["name"]
    if name == "connect":
        if s and s.state.connected and adapter.client.connected:
            sim("PRESS")
            phase.update(name="held", t=now)
        return 0.2
    phase["states"].append(s.mic.state)
    if name == "held":
        if now - phase["t"] > 1.2:
            print("PTT while held:", s.mic.state)
            sim("RELEASE")
            phase.update(name="released", t=now)
        else:
            sim("PRESS")  # what keyboard auto-repeat sends while the key is held
        return 0.1
    if name == "released" and now - phase["t"] > 2.5:
        users = [(t["text"], t["source"]) for t in s.state.transcript if t["kind"] == "user"]
        print("PTT states seen:", sorted(set(phase["states"])), "| final:", s.mic.state, "| messages:", users)
        print("PTT_DONE")
        ui_panel.stop()
        adapter.shutdown()
        bpy.ops.wm.quit_blender()
        return None
    return 0.1


bpy.app.timers.register(step, first_interval=2.0)
