"""Wysp's mascot as Blender icons, loaded with ``bpy.utils.previews`` from ``adapter/icons/``.

Blender draws icons from a fixed built-in set; custom pictures go through a preview collection and are
drawn with ``icon_value``. Everything degrades to a built-in icon when a file is missing or previews are
unavailable, so a broken install never breaks the panel. Main thread only.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("wysp.blender.ui")

ICON_DIR = Path(__file__).resolve().parent / "icons"
# name -> (file, built-in icon used when the picture cannot be loaded)
ICON_FILES: dict[str, tuple[str, str]] = {
    "mark": ("mark-color-64.png", "LIGHT_SUN"),  # small mascot: the panel's top row
    "mark_big": ("mark-color-256.png", "LIGHT_SUN"),  # large mascot: the empty chat
}

_collection = None


def register() -> None:
    """Load the pictures. Safe to call twice; missing files are skipped."""
    global _collection
    if _collection is not None:
        return
    try:
        import bpy.utils.previews as previews
    except ImportError:
        return
    coll = previews.new()
    for name, (filename, _fallback) in ICON_FILES.items():
        path = ICON_DIR / filename
        if not path.is_file():
            log.warning("icon file missing: %s", path)
            continue
        try:
            coll.load(name, str(path), "IMAGE")
        except Exception:  # noqa: BLE001 - an icon must never stop the add-on from loading
            log.exception("cannot load icon %s", path)
    _collection = coll


def unregister() -> None:
    global _collection
    coll, _collection = _collection, None
    if coll is not None:
        import bpy.utils.previews as previews

        previews.remove(coll)


def icon_id(name: str) -> int:
    """The icon_value of a loaded picture, or 0 when it is not available."""
    if _collection is None:
        return 0
    try:
        return int(_collection[name].icon_id)
    except (KeyError, AttributeError):
        return 0


def icon_args(name: str) -> dict[str, object]:
    """Keyword arguments for ``layout.label`` / ``operator`` / ``template_icon``: ``icon_value`` or a fallback."""
    value = icon_id(name)
    if value:
        return {"icon_value": value}
    return {"icon": ICON_FILES[name][1]}
