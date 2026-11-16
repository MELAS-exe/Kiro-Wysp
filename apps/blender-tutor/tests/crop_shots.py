"""Crop full-window Blender screenshots to the sidebar (developer tool).

    uv run --with pillow --no-project python apps/blender-tutor/tests/crop_shots.py SRC_DIR DST_DIR [--wide NAME ...]

gui_panel_states.py writes the sidebar rectangle next to each shot (NAME.json, Blender window coordinates, origin
bottom-left). `--wide` names keep much more of the left side: the "..." popover opens under the mouse.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
wide = set(sys.argv[sys.argv.index("--wide") + 1 :]) if "--wide" in sys.argv else set()
viewport = {"approval"}
dst.mkdir(parents=True, exist_ok=True)
for path in sorted(src.glob("blender-panel-*.png")):
    name = path.stem.removeprefix("blender-panel-")
    im = Image.open(path).convert("RGB")
    info = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    top = im.height - info["y"] - info["h"]
    left, right = info["x"] - 10, info["x"] + info["w"] + 10
    if name in wide:
        left = max(0, left - 260)
        right = min(im.width, right + 10)
    box = (max(0, left), max(0, top - 10), min(im.width, right), min(im.height, top + info["h"] + 20))
    out = dst / path.name
    im.crop(box).save(out)
    print(out, im.size, "->", box)
    if name in viewport:  # the viewport callout (bottom left of the 3D Viewport), brand colours
        vp = dst / f"blender-panel-{name}-viewport.png"
        im.crop((0, 600, 880, 830)).save(vp)
        print(vp)
