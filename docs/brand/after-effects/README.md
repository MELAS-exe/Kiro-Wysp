# Wysp mascot for After Effects

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
