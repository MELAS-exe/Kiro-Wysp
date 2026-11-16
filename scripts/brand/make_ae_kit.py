"""Build an After Effects kit from the mascot: every part on its own layer, all on the same 1024 x 1024 canvas.

    uv run --with pillow --with numpy --with vtracer --with scipy python scripts/brand/make_ae_kit.py

Writes docs/brand/after-effects/: layers-svg/*.svg (vector, import and "Create Shapes from Vector Layer"),
layers-png/*.png (2048 px, transparent), wysp-mascot-layered.svg (named groups for Illustrator), layers.json (pivots),
Wysp-Build-Comp.jsx (builds the composition in After Effects) and README.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage as ndi

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_assets as ma  # noqa: E402

OUT = ma.BRAND / "after-effects"
SIZE = 1024  # the common canvas of every layer
PNG_SIZE = 2048
MIN_AREA = 40


def classify(color: Image.Image, size: int = SIZE):
    im = color.resize((size, size), Image.LANCZOS)
    a = np.asarray(im).astype(float)
    opaque = a[:, :, 3] > 128
    pal = np.array([ma.VIOLET, ma.VIOLET_DEEP, ma.LILAC, ma.LAVENDER, ma.PINK, ma.INK, (255, 255, 255)], dtype=float)
    d = ((a[:, :, None, :3] - pal[None, None, :, :]) ** 2).sum(axis=3)
    cls = d.argmin(axis=2)
    cls = np.where(cls == 1, 0, cls)  # deep violet is the flame too
    return opaque, cls


def components(mask: np.ndarray) -> list[dict]:
    lab, n = ndi.label(mask, structure=np.ones((3, 3)))
    out = []
    for i in range(1, n + 1):
        m = lab == i
        area = int(m.sum())
        if area < MIN_AREA:
            continue
        ys, xs = np.nonzero(m)
        out.append(
            {
                "mask": m,
                "area": area,
                "cx": float(xs.mean()),
                "cy": float(ys.mean()),
                "box": (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())),
            }
        )
    return out


def union(comps: list[dict], shape: tuple[int, int]) -> np.ndarray:
    m = np.zeros(shape, dtype=bool)
    for c in comps:
        m |= c["mask"]
    return m


def smooth(mask: np.ndarray) -> Image.Image:
    """Clean edges without eating small parts."""
    area = int(mask.sum())
    big = area > 4000
    im = Image.fromarray((mask * 255).astype("uint8"))
    im = im.filter(ImageFilter.MedianFilter(7 if big else 3)).filter(ImageFilter.GaussianBlur(1.6 if big else 0.8))
    return im.point(lambda v: 255 if v > 128 else 0)


def split_parts(color: Image.Image) -> list[dict]:
    """The mascot as named layers, bottom to top. Each layer is stacked (no holes): moving one never reveals a gap."""
    opaque, cls = classify(color)
    shape = opaque.shape
    parts: list[dict] = []

    def add(
        name: str, fill: tuple[int, int, int], mask: np.ndarray, pivot: str = "center", opacity: float = 1.0
    ) -> None:
        ys, xs = np.nonzero(mask)
        if xs.size == 0:
            return
        box = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
        px = (box[0] + box[2]) / 2
        py = box[3] if pivot == "bottom" else (box[1] + box[3]) / 2
        parts.append(
            {
                "name": name,
                "fill": fill,
                "mask": mask,
                "box": box,
                "pivot": (round(px, 1), round(py, 1)),
                "opacity": opacity,
            }
        )

    ink = components(opaque & (cls == 5))
    ink.sort(key=lambda c: -c["area"])
    glasses = ink[0] if ink else None
    rest = ink[1:]
    pupils = sorted(rest[:2], key=lambda c: c["cx"])
    mouth = rest[2:]

    white = components(opaque & (cls == 6))

    def inside(c: dict, p: dict) -> bool:
        x0, y0, x1, y1 = p["box"]
        return x0 <= c["cx"] <= x1 and y0 <= c["cy"] <= y1

    sparkles = sorted([c for c in white if any(inside(c, p) for p in pupils)], key=lambda c: c["cx"])
    spark_ids = {id(c) for c in sparkles}
    shine = [c for c in white if id(c) not in spark_ids]
    cheeks = sorted(sorted(components(opaque & (cls == 4)), key=lambda c: -c["area"])[:2], key=lambda c: c["cx"])

    add("01-flame-outer", ma.VIOLET, opaque, "bottom")
    if shine:
        add("02-flame-shine", ma.LAVENDER, union(shine, shape), "center", 0.7)
    add("03-flame-inner", ma.LILAC, opaque & np.isin(cls, [2, 3, 4, 5, 6]), "bottom")
    add("04-face", ma.LAVENDER, opaque & np.isin(cls, [3, 4, 5, 6]), "center")
    for name, c in zip(("05-cheek-left", "06-cheek-right"), cheeks, strict=False):
        add(name, ma.PINK, c["mask"])
    if glasses:
        add("07-glasses", ma.INK, glasses["mask"])
    for name, c in zip(("08-eye-left", "09-eye-right"), pupils, strict=False):
        add(name, ma.INK, c["mask"])
    for name, c in zip(("10-sparkle-left", "11-sparkle-right"), sparkles, strict=False):
        add(name, (255, 255, 255), c["mask"])
    if mouth:
        add("12-mouth", ma.INK, union(mouth, shape))
    return parts


def layer_svg(part: dict, work: Path) -> tuple[str, list[str]]:
    """(standalone svg, its paths) for one part, traced from its own mask."""
    m = smooth(part["mask"])
    bw = Image.new("RGB", m.size, (255, 255, 255))
    bw.paste((0, 0, 0), mask=m)
    src = work / "_part.png"
    bw.save(src)
    svg = ma.trace(src, work / "_part.svg", binary=True)
    fill = ma.hexc(part["fill"])
    op = f' fill-opacity="{part["opacity"]}"' if part["opacity"] < 1 else ""
    paths = [
        f'<path d="{d}"' + (f' transform="{t}"' if t else "") + f' fill="{fill}"{op} fill-rule="evenodd"/>'
        for d, t, f in ma.svg_paths(svg)
        if f.lower() in ("#000000", "#000")
    ]
    head = f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" viewBox="0 0 {SIZE} {SIZE}">'
    return head + "\n  " + "\n  ".join(paths) + "\n</svg>\n", paths


def layer_png(part: dict) -> Image.Image:
    m = smooth(part["mask"]).resize((PNG_SIZE, PNG_SIZE), Image.LANCZOS)
    out = Image.new("RGBA", m.size, (*part["fill"], 0))
    alpha = m.point(lambda v: int(v * part["opacity"]))
    out.putalpha(alpha)
    return out


JSX = r"""/*
 * Wysp mascot: builds the composition in After Effects.
 * File > Scripts > Run Script File... and pick this file (keep it next to the "layers-svg" and "layers-png" folders).
 * Not run in After Effects by the person who wrote it: if it stops with an error, use the manual way in README.md.
 */
(function () {
    var USE_SVG = true;          // false: use the PNG layers (2048 px, shown at 50%)
    var COMP_W = 1920, COMP_H = 1080, FPS = 30, DURATION = 6;
    var LAYERS = __LAYERS__;

    var here = File($.fileName).parent;
    var dir = new Folder(here.fsName + (USE_SVG ? "/layers-svg" : "/layers-png"));
    if (!dir.exists) { alert("Cannot find the folder " + dir.fsName); return; }

    app.beginUndoGroup("Wysp mascot");
    var comp = app.project.items.addComp("Wysp mascot", COMP_W, COMP_H, 1, DURATION, FPS);
    comp.bgColor = [0.071, 0.02, 0.196];   // night #120532
    var folder = app.project.items.addFolder("Wysp layers");
    var k = USE_SVG ? 1 : 2;               // layer pixels per canvas unit
    var left = COMP_W / 2 - 512, top = COMP_H / 2 - 512;   // where the 1024 canvas starts in the comp

    for (var i = 0; i < LAYERS.length; i++) {
        var spec = LAYERS[i];
        var file = new File(dir.fsName + "/" + spec.name + (USE_SVG ? ".svg" : ".png"));
        if (!file.exists) { alert("Missing " + file.fsName); continue; }
        var io = new ImportOptions(file);
        io.importAs = ImportAsType.FOOTAGE;
        var item = app.project.importFile(io);
        item.parentFolder = folder;
        var layer = comp.layers.add(item);
        layer.name = spec.name.replace(/^\d+-/, "");
        if (USE_SVG) { layer.collapseTransformation = true; }   // continuously rasterize: stays sharp when scaled
        // Pivot in canvas units -> position in the comp, so every layer still sits exactly where it was drawn.
        layer.anchorPoint.setValue([spec.pivot[0] * k, spec.pivot[1] * k]);
        layer.position.setValue([left + spec.pivot[0], top + spec.pivot[1]]);
        if (!USE_SVG) { layer.scale.setValue([50, 50]); }
    }
    comp.openInViewer();
    app.endUndoGroup();
})();
"""

README = """# Wysp mascot for After Effects

Every part of the mascot is on its own layer, all drawn on the same 1024 x 1024 canvas, so they stack exactly and each
has a sensible pivot (the point it rotates and scales around).

| Layer (bottom to top) | Pivot | Ideas |
|---|---|---|
| `flame-outer` | bottom centre | sway (rotation), squash and stretch, **Wave Warp** or **Turbulent Displace** to flicker |
| `flame-shine` | centre | opacity pulse |
| `flame-inner` | bottom centre | the same, slightly delayed (a little more lag looks alive) |
| `face` | centre | slight bob |
| `cheek-left`, `cheek-right` | centre | scale pop when happy |
| `glasses` | centre | push up and settle |
| `eye-left`, `eye-right` | centre | **blink**: Scale Y 100 to 10 and back; look around: Position |
| `sparkle-left`, `sparkle-right` | centre | scale or opacity twinkle |
| `mouth` | centre | scale, or morph the path (see below) |

## Way 1: the script (fastest)
1. In After Effects: **File > Scripts > Run Script File...** and pick `Wysp-Build-Comp.jsx` (keep it beside the `layers-svg` and `layers-png` folders).
2. It makes the composition "Wysp mascot" (1920 x 1080, 30 fps, 6 s, night background) with every layer named, in order, with the pivots set. Edit `USE_SVG`, `COMP_W`, `COMP_H` at the top of the script if you want something else.

The script has not been run in After Effects by whoever wrote it. If it errors, use Way 2.

## Way 2: by hand
1. **File > Import > File...**, select all the files in `layers-svg` (or `layers-png`), import as **Footage**.
2. Create a composition, drag the layers in, bottom to top by file number. They are all the same size, so they line up as they are (centre them with Layer > Transform > Fit to Comp Width if needed).
3. For vectors, turn on **Continuously Rasterize** (the sun icon) so they stay sharp when scaled.
4. Set each pivot with the Pan Behind tool (Y) using the table above.

## Real vector shapes (to morph paths or trim)
Right-click an SVG layer > **Create > Create Shapes from Vector Layer**. You get an editable shape layer (the paths, fill colours, Add > Wiggle Paths, Trim Paths, Repeater all work). This is the way to animate the mouth into a smile or an "o", or to flicker the flame tips by moving path points.

## Via Illustrator (layers kept as a comp)
Open `wysp-mascot-layered.svg` in Illustrator (each part is a named group), save it as `.ai`, then in After Effects import the `.ai` as **Composition - Retain Layer Sizes**.

## Files
- `layers-svg/` the layers as vectors, 1024 x 1024
- `layers-png/` the layers as transparent PNGs, 2048 x 2048 (shown at 50%)
- `wysp-mascot-layered.svg` all layers in one file, named groups
- `layers.json` names, colours, bounding boxes and pivots
- `Wysp-Build-Comp.jsx` the script

Colours: flame `#6503FC`, inner flame `#CA84FC`, face `#F4E5FD`, cheeks `#FE7C9C`, ink `#0D012F`, background night `#120532`.
Regenerate with `uv run --with pillow --with numpy --with vtracer --with scipy python scripts/brand/make_ae_kit.py`.
"""


def main() -> None:
    (OUT / "layers-svg").mkdir(parents=True, exist_ok=True)
    (OUT / "layers-png").mkdir(parents=True, exist_ok=True)
    work = ma.BRAND / "source"
    cut = ma.cut_out()
    color = ma.upscale(cut)
    parts = split_parts(color)

    meta, groups = [], []
    for p in parts:
        svg, paths = layer_svg(p, work)
        (OUT / "layers-svg" / f"{p['name']}.svg").write_text(svg, encoding="utf-8")
        layer_png(p).save(OUT / "layers-png" / f"{p['name']}.png")
        groups.append(f'  <g id="{p["name"]}">\n    ' + "\n    ".join(paths) + "\n  </g>")
        meta.append(
            {
                "name": p["name"],
                "fill": ma.hexc(p["fill"]),
                "opacity": p["opacity"],
                "box": list(p["box"]),
                "pivot": list(p["pivot"]),
            }
        )
    layered = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" viewBox="0 0 {SIZE} {SIZE}">\n'
        + "\n".join(groups)
        + "\n</svg>\n"
    )
    (OUT / "wysp-mascot-layered.svg").write_text(layered, encoding="utf-8")
    (OUT / "layers.json").write_text(json.dumps({"canvas": SIZE, "layers": meta}, indent=2), encoding="utf-8")
    jsx_layers = json.dumps([{"name": m["name"], "pivot": m["pivot"]} for m in meta], indent=8)
    (OUT / "Wysp-Build-Comp.jsx").write_text(JSX.replace("__LAYERS__", jsx_layers), encoding="utf-8")
    (OUT / "README.md").write_text(README, encoding="utf-8")

    # A check: the PNG layers stacked must look like the mascot.
    canvas = Image.new("RGBA", (PNG_SIZE, PNG_SIZE), (0, 0, 0, 0))
    for p in parts:
        canvas.alpha_composite(layer_png(p))
    bg = Image.new("RGBA", canvas.size, (*ma.INK, 255))
    bg.alpha_composite(canvas)
    bg.convert("RGB").resize((1024, 1024), Image.LANCZOS).save(work / "_stack_check.png")
    print(f"{len(parts)} layers:", ", ".join(p["name"] for p in parts))
    for m in meta:
        print(f"  {m['name']:18s} pivot {m['pivot']}  box {m['box']}")


if __name__ == "__main__":
    main()
