"""Generates the Wysp browser connector icons from the brand mascot.

    uv run --with pillow python scripts/make_web_tutor_icons.py

Writes apps/web-tutor/extension/public/icons/icon-{16,32,48,128}.png and mark-64.png (the in-page launcher image,
inlined into the content script). The mascot is cropped to its visible pixels, padded to a square with a little
clear space and resized with Lanczos. Do not recolour it (docs/brand/README.md).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "brand" / "mark-color-256.png"
OUT = ROOT / "apps" / "web-tutor" / "extension" / "public" / "icons"
SIZES = (16, 32, 48, 128)


def square_mark() -> Image.Image:
    img = Image.open(SRC).convert("RGBA")
    box = img.getchannel("A").getbbox()
    if box:
        img = img.crop(box)
    side = max(img.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)
    return canvas


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    mark = square_mark()
    for size in SIZES:
        # Leave about 1 px of clear space at 16 px, proportionally less visible at larger sizes.
        pad = max(0, round(size * 0.04))
        inner = size - 2 * pad
        tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        tile.paste(mark.resize((inner, inner), Image.LANCZOS), (pad, pad))
        tile.save(OUT / f"icon-{size}.png", optimize=True)
    mark.resize((64, 64), Image.LANCZOS).save(OUT / "mark-64.png", optimize=True)
    print(f"wrote {len(SIZES) + 1} files to {OUT}")


if __name__ == "__main__":
    main()
