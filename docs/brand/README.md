# Wysp brand

The mascot is a small violet flame with round glasses. Its colours are the brand colours, measured from the image
(`source/mascot-original.jpeg`). Everything else in this folder is generated from it by
`scripts/brand/make_assets.py`, so the logo can be changed in one place:

```powershell
uv run --with pillow --with numpy --with vtracer python scripts/brand/make_assets.py
```

## Colours

| Name | Hex | Where it comes from | Use |
|---|---|---|---|
| Violet | `#6503FC` | the flame | fills, borders, the IDE frame on light themes. **Never text on a dark background** (2.7:1) |
| Violet deep | `#4F03F5` | the flame's outline | outlines, pressed states |
| Lilac | `#CA84FC` | the inner flame | glow, links, accents and highlights on dark (7.5:1 on night) |
| Lavender | `#F4E5FD` | the face | text on dark (16:1 on night), light surfaces |
| Pink | `#FE7C9C` | the cheeks | secondary accent: speaking state, markers, notes (7.8:1) |
| Ink | `#0D012F` | eyes and glasses | text on lilac or lavender (7.7:1), the darkest background |
| Night | `#120532` | ink, lightened | the Panel background |
| Surface | `#1D0E4A` | | cards, composer, menus |
| Surface 2 | `#2A1766` | | hover, bubbles, board grid |
| Line | `#3B2A80` / `#5440A6` | | borders |
| Muted | `#B9A3E3` | | secondary text (8.6:1 on night) |

Status colours stay semantic and are not brand colours: success `#22C55E`, danger `#EF4444`, warning banners brown-orange.

## Files

| File | Use |
|---|---|
| `mark-color.png` (2048), `-1254`, `-512`, `-256`, `-128`, `-64` | the mascot on a transparent background |
| `mark-color.svg` | flat-colour vector (6 traced layers, 18 KB) |
| `mark-white.png`, `mark-black.png`, `mark-violet.png` | one colour, eyes and glasses cut out, transparent |
| `lockup-color-dark.png`, `lockup-color-light.png` | mascot and "Wysp" wordmark, 3000x1000, on ink / white |
| `lockup-white.png`, `lockup-black.png` | the same in one colour, transparent |
| `glyph-white.svg`, `glyph-black.svg` | a bold one-colour flame with two eyes that reads at 16 px |
| `social-1500x1000.png` | Devpost thumbnail and gallery (3:2) |
| `social-1280x640.png` | GitHub social preview (2:1) |
| `favicon.ico` | 16 to 256 px |

Used by the products (copied by the script):

- IntelliJ plugin: `META-INF/pluginIcon.svg` (+ `_dark`), the 40x40 plugin logo; `icons/wyspToolWindow.svg` (16x16) and `@20x20`, each with `_dark`, the grey tool window icon; `icons/wysp.svg` (+ `_dark`) for menus.
- Panel: `panel/public/favicon.png`, `favicon.ico`, `wysp-mark.png` (the mascot on the empty chat).
- Blender: no icon is embedded. For the extension listing use `mark-color-256.png` (confirm the size the extensions website asks for when uploading).

## After Effects

`after-effects/` holds the mascot split into 12 animatable layers on one shared canvas (flame, shine, inner flame, face, two cheeks, glasses, two eyes, two sparkles, mouth), as vector SVGs and 2048 px PNGs, with pivots, a layered SVG for Illustrator and a script that builds the composition. See `after-effects/README.md`. Regenerate with `uv run --with pillow --with numpy --with vtracer --with scipy python scripts/brand/make_ae_kit.py`.

## Rules

- Keep clear space around the mascot of at least a quarter of its width. Minimum size: 16 px for the glyph, 24 px for the full mascot.
- On dark backgrounds use the colour mascot or `mark-white`. On light backgrounds use the colour mascot or `mark-black`/`mark-violet`.
- The wordmark is Nunito ExtraBold. Nunito is under the SIL Open Font License; the font file used to draw it is in `source/`.
- Do not recolour the mascot, put text over its face, or stretch it.
- Provenance styles (observed, likely, example) keep their meaning: solid, dashed and hatched borders, now in lilac.
