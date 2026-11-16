"""Build every Wysp logo asset from the mascot image (docs/brand/source/mascot-original.jpeg).

    uv run --with pillow --with numpy --with vtracer python scripts/brand/make_assets.py

Writes docs/brand/*.png|svg|ico and copies the files the products use (IntelliJ plugin icons, Panel favicon and mascot).
Brand colours are measured from the mascot itself (see docs/brand/README.md).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "docs" / "brand"
SRC = BRAND / "source" / "mascot-original.jpeg"
FONT = BRAND / "source" / "Nunito-Variable.ttf"

# Brand palette, sampled from the mascot.
VIOLET = (0x65, 0x03, 0xFC)  # flame
VIOLET_DEEP = (0x4F, 0x03, 0xF5)  # outline
LILAC = (0xCA, 0x84, 0xFC)  # inner flame
LAVENDER = (0xF4, 0xE5, 0xFD)  # face
PINK = (0xFE, 0x7C, 0x9C)  # cheeks
INK = (0x0D, 0x01, 0x2F)  # eyes and glasses
NIGHT = (0x14, 0x07, 0x3B)

MASTER = 2048


def hexc(c: tuple[int, int, int]) -> str:
    return f"#{c[0]:02X}{c[1]:02X}{c[2]:02X}"


# ------------------------------------------------------------------------------------------------ cut-out
def cut_out() -> Image.Image:
    """The mascot on a transparent background (1254 px, clean edges), from the white-background JPEG."""
    im = Image.open(SRC).convert("RGB")
    probe = im.copy()
    magenta = (255, 0, 255)
    for seed in ((0, 0), (im.width - 1, 0), (0, im.height - 1), (im.width - 1, im.height - 1)):
        ImageDraw.floodfill(probe, seed, magenta, thresh=48)
    a = np.asarray(probe).astype(int)
    bg = (a[:, :, 0] == 255) & (a[:, :, 1] == 0) & (a[:, :, 2] == 255)
    rgb = np.asarray(im).astype(float)
    alpha = np.where(bg, 0.0, 255.0)
    # Soft edge: next to the background the outline mixes with white (JPEG), so the green channel tells the coverage.
    bgm = Image.fromarray((bg * 255).astype("uint8"))
    near = np.asarray(bgm.filter(ImageFilter.MaxFilter(7))) > 0  # within 3 px of the background
    edge = near & ~bg
    cov = 1.0 - np.clip((rgb[:, :, 1] - 8.0) / 240.0, 0, 1)
    alpha = np.where(edge, 255.0 * np.clip(cov * 1.15, 0, 1), alpha)
    # Remove the white fringe from the colour of edge pixels: they are outline-coloured.
    for ch, v in enumerate(VIOLET_DEEP):
        rgb[:, :, ch] = np.where(edge, v, rgb[:, :, ch])
    out = np.dstack([rgb, alpha]).astype("uint8")
    return Image.fromarray(out, "RGBA")


def upscale(im: Image.Image, size: int = MASTER) -> Image.Image:
    return im.resize((size, size), Image.LANCZOS)


def mono(color_mark: Image.Image, fill: tuple[int, int, int]) -> Image.Image:
    """One flat colour: the silhouette with the ink (eyes, glasses, smile) cut out so the face still reads."""
    a = np.asarray(color_mark).astype(float)
    lum = 0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]
    ink = np.clip((90 - lum) / 40.0, 0, 1)  # dark pixels become holes, softly
    alpha = a[:, :, 3] * (1 - ink)
    out = np.zeros_like(a)
    out[:, :, 0], out[:, :, 1], out[:, :, 2], out[:, :, 3] = fill[0], fill[1], fill[2], alpha
    return Image.fromarray(out.astype("uint8"), "RGBA")


def glyph_mask(color_mark: Image.Image, size: int = 512) -> Image.Image:
    """A bold shape that survives 16 px: the silhouette with two big round eyes cut out (black = shape, on white)."""
    sil = color_mark.resize((size, size), Image.LANCZOS).split()[3]
    sil = sil.point(lambda v: 255 if v > 110 else 0)
    holes = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(holes)
    k = size / 1254.0
    for cx in (405, 845):  # the two lenses of the glasses, scaled up a little
        cy, rx, ry = 860, 120, 135
        d.ellipse((cx * k - rx * k, cy * k - ry * k, cx * k + rx * k, cy * k + ry * k), fill=255)
    shape = ImageChops.subtract(sil, holes)
    # Round off the tiny details so every stroke is thick.
    shape = shape.filter(ImageFilter.GaussianBlur(1.6)).point(lambda v: 255 if v > 128 else 0)
    bw = Image.new("RGB", (size, size), (255, 255, 255))
    bw.paste((0, 0, 0), mask=shape)
    return bw


# ----------------------------------------------------------------------------------------------- vectors
def trace(src_png: Path, out_svg: Path, binary: bool, coarse: bool = False) -> str:
    import vtracer

    vtracer.convert_image_to_svg_py(
        str(src_png),
        str(out_svg),
        colormode="binary" if binary else "color",
        hierarchical="cutout" if binary else "stacked",
        mode="spline",
        filter_speckle=6 if binary else (24 if coarse else 10),
        color_precision=6 if not coarse else 4,
        layer_difference=20 if not coarse else 56,
        corner_threshold=60,
        length_threshold=4.0,
        splice_threshold=45,
        path_precision=2,
    )
    return out_svg.read_text(encoding="utf-8")


def layered_svg(color: Image.Image, view: int, work: Path, size: int = 768) -> str:
    """A clean flat-colour SVG: the mascot split into its real layers, each traced on its own (smooth, small).

    Layers, bottom to top: flame (violet), inner flame (lilac), face (lavender), cheeks (pink), glasses and eyes (ink),
    eye sparkles (white). Gradients are flattened, which is what a 40 px icon needs anyway.
    """
    im = color.resize((size, size), Image.LANCZOS)
    a = np.asarray(im).astype(float)
    opaque = a[:, :, 3] > 128
    pal = np.array([VIOLET, VIOLET_DEEP, LILAC, LAVENDER, PINK, INK, (255, 255, 255)], dtype=float)
    d = ((a[:, :, None, :3] - pal[None, None, :, :]) ** 2).sum(axis=3)
    cls = d.argmin(axis=2)
    cls = np.where(cls == 1, 0, cls)  # deep violet is the flame too
    # Eye sparkles are white, but so is nothing else inside the flame except the face (lavender): keep only tiny ones.
    layers = [
        (VIOLET, opaque),
        (LILAC, opaque & np.isin(cls, [2, 3, 4, 5, 6])),
        (LAVENDER, opaque & np.isin(cls, [3, 4, 5, 6])),
        (PINK, opaque & (cls == 4)),
        (INK, opaque & (cls == 5)),
        ((255, 255, 255), opaque & (cls == 6)),
    ]
    scale = view / size
    parts = []
    for i, (fill, mask) in enumerate(layers):
        m = Image.fromarray((mask * 255).astype("uint8"))
        m = (
            m.filter(ImageFilter.MedianFilter(5))
            .filter(ImageFilter.GaussianBlur(1.2))
            .point(lambda v: 255 if v > 128 else 0)
        )
        bw = Image.new("RGB", m.size, (255, 255, 255))
        bw.paste((0, 0, 0), mask=m)
        src = work / f"_layer{i}.png"
        bw.save(src)
        svg = trace(src, work / f"_layer{i}.svg", binary=True)
        for dd, tt, ff in svg_paths(svg):
            if ff.lower() in ("#000000", "#000"):
                parts.append(
                    f'  <path d="{dd}" fill="{hexc(fill)}" transform="scale({scale:.5f}) {tt}" fill-rule="evenodd"/>'
                )
    body = "\n".join(parts)
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{view}" height="{view}" viewBox="0 0 {view} {view}">\n{body}\n</svg>\n'


def svg_paths(svg: str) -> list[tuple[str, str, str]]:
    """(d, transform, fill) of every <path>."""
    out = []
    for m in re.finditer(r"<path\s+d=\"([^\"]+)\"\s+fill=\"([^\"]+)\"(?:\s+transform=\"([^\"]*)\")?", svg):
        out.append((m.group(1), m.group(3) or "", m.group(2)))
    return out


def mono_svg(svg: str, size: int, fill: str, view: int) -> str:
    """Wrap traced black shapes as one single-colour icon: explicit fill, no CSS (the IDE recolours by literal hex)."""
    scale = view / size
    paths = [(d, t) for d, t, f in svg_paths(svg) if f.lower() in ("#000000", "#000")]
    body = "\n".join(
        f'  <path d="{d}" transform="scale({scale:.5f}) {t}" fill="{fill}" fill-rule="evenodd"/>' for d, t in paths
    )
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{view}" height="{view}" viewBox="0 0 {view} {view}">\n{body}\n</svg>\n'


# ------------------------------------------------------------------------------------------------ layouts
def font(size: int, weight: str = "ExtraBold") -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT), size)
    f.set_variation_by_name(weight)
    return f


def paste_center(canvas: Image.Image, im: Image.Image, cx: int, cy: int) -> None:
    canvas.alpha_composite(im, (int(cx - im.width / 2), int(cy - im.height / 2)))


def lockup(
    mark: Image.Image, text_color: tuple[int, int, int], bg: tuple[int, int, int] | None, w: int = 3000, h: int = 1000
) -> Image.Image:
    canvas = Image.new("RGBA", (w, h), (*bg, 255) if bg else (0, 0, 0, 0))
    m = mark.resize((int(h * 0.78), int(h * 0.78)), Image.LANCZOS)
    f = font(int(h * 0.56))
    text_w = f.getlength("Wysp")
    gap = int(h * 0.07)
    total = m.width + gap + text_w
    x0 = (w - total) / 2
    canvas.alpha_composite(m, (int(x0), int((h - m.height) / 2)))
    d = ImageDraw.Draw(canvas)
    asc, desc = f.getmetrics()
    d.text((x0 + m.width + gap, (h - (asc + desc)) / 2 + h * 0.02), "Wysp", font=f, fill=(*text_color, 255))
    return canvas


def fit_font(text: str, start: int, avail: int, weight: str) -> ImageFont.FreeTypeFont:
    size = start
    f = font(size, weight)
    while f.getlength(text) > avail and size > 10:
        size -= 2
        f = font(size, weight)
    return f


def social(mark: Image.Image, w: int, h: int) -> Image.Image:
    base = Image.new("RGBA", (w, h), (*INK, 255))
    # Soft violet glow behind the mascot.
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r = int(h * 0.55)
    gd.ellipse((w * 0.27 - r, h * 0.5 - r, w * 0.27 + r, h * 0.5 + r), fill=(*VIOLET, 150))
    glow = glow.filter(ImageFilter.GaussianBlur(h * 0.16))
    base.alpha_composite(glow)
    m = mark.resize((int(h * 0.74), int(h * 0.74)), Image.LANCZOS)
    paste_center(base, m, int(w * 0.27), int(h * 0.5))
    d = ImageDraw.Draw(base)
    x = int(w * 0.50)
    avail = int(w - x - w * 0.06)
    name = fit_font("Wysp", int(h * 0.34), avail, "ExtraBold")
    d.text((x - 4, h * 0.24), "Wysp", font=name, fill=(*LAVENDER, 255))
    lines = ("A small light that guides you", "through unfamiliar software.")
    tag = fit_font(max(lines, key=len), int(h * 0.058), avail, "SemiBold")
    for i, line in enumerate(lines):
        d.text((x, h * 0.64 + i * h * 0.085), line, font=tag, fill=(*LILAC, 255))
    return base


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    def lin(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    def lum(c: tuple[int, int, int]) -> float:
        return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def main() -> None:
    BRAND.mkdir(parents=True, exist_ok=True)
    cut = cut_out()
    cut.save(BRAND / "mark-color-1254.png")
    color = upscale(cut)
    color.save(BRAND / "mark-color.png")
    for s in (512, 256, 128, 64):
        color.resize((s, s), Image.LANCZOS).save(BRAND / f"mark-color-{s}.png")

    # One-colour versions (transparent): white for dark backgrounds, black for light ones, violet for brand use.
    mono(color, (255, 255, 255)).save(BRAND / "mark-white.png")
    mono(color, (0, 0, 0)).save(BRAND / "mark-black.png")
    mono(color, VIOLET).save(BRAND / "mark-violet.png")

    # Lockups: mark + wordmark.
    lockup(color, LAVENDER, INK).convert("RGB").save(BRAND / "lockup-color-dark.png")
    lockup(color, VIOLET, (255, 255, 255)).convert("RGB").save(BRAND / "lockup-color-light.png")
    lockup(mono(color, (255, 255, 255)), (255, 255, 255), None).save(BRAND / "lockup-white.png")
    lockup(mono(color, (0, 0, 0)), (0, 0, 0), None).save(BRAND / "lockup-black.png")

    # Social images.
    social(color, 1500, 1000).convert("RGB").save(BRAND / "social-1500x1000.png")
    social(color, 1280, 640).convert("RGB").save(BRAND / "social-1280x640.png")

    # Favicons.
    fav = color.resize((256, 256), Image.LANCZOS)
    fav.save(BRAND / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    # Vectors: a full-colour SVG, and a one-colour glyph that reads at 16 px.
    tmp = BRAND / "source"
    (BRAND / "mark-color.svg").write_text(layered_svg(color, 1024, tmp, 1024), encoding="utf-8")
    glyph_mask(color, 512).save(tmp / "_glyph512.png")
    glyph = trace(tmp / "_glyph512.png", tmp / "_glyph.svg", binary=True)
    (BRAND / "glyph-black.svg").write_text(mono_svg(glyph, 512, "#000000", 40), encoding="utf-8")
    (BRAND / "glyph-white.svg").write_text(mono_svg(glyph, 512, "#FFFFFF", 40), encoding="utf-8")

    # ---- IntelliJ: plugin logo (40x40, light and dark) and tool window icon (16 and 20, grey, light and dark).
    res = ROOT / "apps" / "intellij-tutor" / "plugin" / "src" / "main" / "resources"
    (res / "META-INF").mkdir(parents=True, exist_ok=True)
    (res / "icons").mkdir(parents=True, exist_ok=True)
    plugin_svg = layered_svg(color, 40, tmp, 768)
    (res / "META-INF" / "pluginIcon.svg").write_text(plugin_svg, encoding="utf-8")
    (res / "META-INF" / "pluginIcon_dark.svg").write_text(plugin_svg, encoding="utf-8")  # the mascot reads on both
    for name, fill in (("wyspToolWindow", "#6C707E"), ("wyspToolWindow_dark", "#CED0D6")):
        (res / "icons" / f"{name}.svg").write_text(mono_svg(glyph, 512, fill, 16), encoding="utf-8")
        (res / "icons" / f"{name.replace('wyspToolWindow', 'wyspToolWindow@20x20')}.svg").write_text(
            mono_svg(glyph, 512, fill, 20), encoding="utf-8"
        )
    (res / "icons" / "wysp.svg").write_text(mono_svg(glyph, 512, "#6C707E", 16), encoding="utf-8")  # menu and actions
    (res / "icons" / "wysp_dark.svg").write_text(mono_svg(glyph, 512, "#CED0D6", 16), encoding="utf-8")

    # ---- Panel: favicon and the mascot for the empty chat.
    pub = ROOT / "panel" / "public"
    pub.mkdir(parents=True, exist_ok=True)
    color.resize((256, 256), Image.LANCZOS).save(pub / "favicon.png")
    shutil.copyfile(BRAND / "favicon.ico", pub / "favicon.ico")
    color.resize((384, 384), Image.LANCZOS).save(pub / "wysp-mark.png")

    print("contrast on night (#14073B):")
    for n, c in (("lavender text", LAVENDER), ("lilac accent", LILAC), ("pink accent", PINK), ("violet", VIOLET)):
        print(f"  {n:14s} {hexc(c)}  {contrast(c, NIGHT):.1f}:1")


def trace_to_view(svg: str, size: int, view: int) -> str:
    """Re-wrap a traced colour SVG for a `view` x `view` canvas."""
    paths = svg_paths(svg)
    scale = view / size
    body = "\n".join(f'  <path d="{d}" fill="{fill}" transform="scale({scale:.5f}) {t}"/>' for d, t, fill in paths)
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{view}" height="{view}" viewBox="0 0 {view} {view}">\n{body}\n</svg>\n'


if __name__ == "__main__":
    main()
