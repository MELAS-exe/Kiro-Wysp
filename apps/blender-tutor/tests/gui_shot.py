"""GUI check run inside a real Blender window: highlights interface elements and saves screenshots.

blender --python-use-system-env --window-geometry 0 0 1600 900 scene.blend --python gui_shot.py -- OUTDIR REF [REF...]

Not a pytest: a developer tool to look at what Wysp draws (it needs a window, not a background Blender).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import run_adapter  # noqa: E402

run_adapter.load_adapter()
from wysp_adapter_sdk import Deferred  # noqa: E402
from wysp_tutor import highlight  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
OUT = Path(argv[0])
REFS = argv[1:]
OUT.mkdir(parents=True, exist_ok=True)
if os.environ.get("WYSP_TEST_CORE"):  # label refs need a Core for OCR, e.g. ws://127.0.0.1:8799/ws/adapter
    highlight.set_core_url(os.environ["WYSP_TEST_CORE"])
for _area in bpy.context.screen.areas:  # sidebar open, as in real use: its text must never be matched
    if _area.type == "VIEW_3D":
        _area.spaces.active.show_region_ui = True
if os.environ.get("WYSP_TEST_UI_SCALE"):  # check that markers follow Blender's Resolution Scale
    bpy.context.preferences.view.ui_scale = float(os.environ["WYSP_TEST_UI_SCALE"])
_queue = list(REFS)
_phase = {"n": 0, "ref": None}


def _step():
    try:
        if _phase["ref"] is None:
            if not _queue:
                print("GUI_DONE")
                bpy.ops.wm.quit_blender()
                return None
            ref = _queue.pop(0)
            _phase["ref"] = ref
            try:
                t0 = time.monotonic()
                result = highlight.highlight(ref, "pulse", 6000)
                busy_ms = round((time.monotonic() - t0) * 1000, 1)
                if isinstance(result, Deferred):  # label refs answer later, off the main thread
                    result.attach(
                        lambda r, e, ref=ref, busy=busy_ms: print(
                            "GUI_HIGHLIGHT", ref, r or f"ERROR {e}", "main-thread ms", busy
                        )
                    )
                else:
                    print("GUI_HIGHLIGHT", ref, result, "main-thread ms", busy_ms)
                print("GUI_RECTS tab", highlight._state.get("tab_rect"), "label", highlight._state.get("label_rect"))
            except Exception as exc:  # noqa: BLE001
                print("GUI_ERROR", ref, exc)
            return 0.6
        name = _phase["ref"].replace("blender://", "").replace("/", "_")
        path = OUT / f"{_phase['n']:02d}_{name}.png"
        wm = bpy.context.window_manager
        with bpy.context.temp_override(window=wm.windows[0]):
            bpy.ops.screen.screenshot(filepath=str(path))
        print(
            "GUI_SHOT",
            path,
            "tabs",
            highlight._state["tabs"],
            "drawn",
            sorted(highlight._state["drawn"]),
            "handlers",
            highlight._state["handlers"][:3],
        )
        highlight.clear_highlight()
        _phase["n"] += 1
        _phase["ref"] = None
        return 0.4
    except Exception as exc:  # noqa: BLE001
        print("GUI_FAIL", repr(exc))
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(_step, first_interval=2.5)
