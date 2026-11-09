"""Blender interface elements Wysp can point at, by ref.

Grammar (all refs start with ``blender://ui/``):

* ``area/<VIEW_3D|OUTLINER|PROPERTIES|TIMELINE>``  a whole editor
* ``region/VIEW_3D/<HEADER|TOOLBAR|SIDEBAR|GIZMO>``  a part of the 3D Viewport
* ``properties/tab/<TAB>``                              a tab of the Properties editor

The Blender API does not expose button rectangles, so pointing is by region (exact) plus, for
Properties tabs and the viewport gizmo, an estimated marker (approximate). Everything here is pure
data and string handling so it can be tested without ``bpy``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PREFIX = "blender://ui/"

# Properties editor tabs in the order Blender lists them, with a plain-language label.
PROPERTIES_TABS: dict[str, str] = {
    "TOOL": "Tool",
    "RENDER": "Render",
    "OUTPUT": "Output",
    "VIEW_LAYER": "View Layer",
    "SCENE": "Scene",
    "WORLD": "World",
    "COLLECTION": "Collection",
    "OBJECT": "Object",
    "MODIFIER": "Modifiers (blue wrench)",
    "PARTICLES": "Particles",
    "PHYSICS": "Physics",
    "CONSTRAINT": "Object Constraints",
    "DATA": "Object Data (green triangle for meshes)",
    "MATERIAL": "Material",
    "TEXTURE": "Texture",
}


# Tabs about the active object; the first one shown starts a new group in the tab column.
OBJECT_LEVEL_TABS = ("COLLECTION", "OBJECT", "MODIFIER", "PARTICLES", "PHYSICS", "CONSTRAINT", "DATA", "MATERIAL")


@dataclass(frozen=True)
class UiTarget:
    ref: str
    label: str
    area: str  # area ui_type: VIEW_3D, OUTLINER, PROPERTIES, TIMELINE
    regions: tuple[str, ...]  # region types to outline; empty means every region of the area
    label_region: str = "WINDOW"  # where the callout text is drawn
    tab: str | None = None
    gizmo: bool = False


AREAS: dict[str, tuple[str, str]] = {
    "VIEW_3D": ("3D Viewport", "VIEW_3D"),
    "OUTLINER": ("Outliner", "OUTLINER"),
    "PROPERTIES": ("Properties editor", "PROPERTIES"),
    "TIMELINE": ("Timeline", "TIMELINE"),
}

VIEWPORT_REGIONS: dict[str, tuple[str, str, bool]] = {
    # name: (label, region type, is_gizmo)
    "HEADER": ("3D Viewport header (View, Select, Add, Object menus)", "HEADER", False),  # label below it
    "TOOLBAR": ("Toolbar (tools on the left)", "TOOLS", False),
    "SIDEBAR": ("Sidebar (press N to show or hide it)", "UI", False),
    "GIZMO": ("Navigation gizmo (drag to orbit, click an axis for a view)", "WINDOW", True),
}

_AREA_RE = re.compile(r"^blender://ui/area/([A-Z_0-9]+)$")
_REGION_RE = re.compile(r"^blender://ui/region/VIEW_3D/([A-Z_]+)$")
_TAB_RE = re.compile(r"^blender://ui/properties/tab/([A-Z_]+)$")


def is_ui_ref(ref: str) -> bool:
    return ref.startswith(PREFIX)


def parse(ref: str) -> UiTarget | None:
    """Turn a ``blender://ui/...`` ref into a target, or None when it is not a known element."""
    if m := _AREA_RE.match(ref):
        if m.group(1) in AREAS:
            label, ui_type = AREAS[m.group(1)]
            return UiTarget(ref, label, ui_type, ())
        return None
    if m := _REGION_RE.match(ref):
        if m.group(1) in VIEWPORT_REGIONS:
            label, region, gizmo = VIEWPORT_REGIONS[m.group(1)]
            # Labels go in the viewport itself so they never cover the header or toolbar buttons.
            return UiTarget(ref, label, "VIEW_3D", (region,), "WINDOW", gizmo=gizmo)
        return None
    if m := _TAB_RE.match(ref):
        if m.group(1) in PROPERTIES_TABS:
            return UiTarget(
                ref, f"{PROPERTIES_TABS[m.group(1)]} tab", "PROPERTIES", ("NAVIGATION_BAR",), "WINDOW", tab=m.group(1)
            )
    return None


def all_refs() -> list[str]:
    refs = [f"{PREFIX}area/{a}" for a in AREAS]
    refs += [f"{PREFIX}region/VIEW_3D/{r}" for r in VIEWPORT_REGIONS]
    refs += [f"{PREFIX}properties/tab/{t}" for t in PROPERTIES_TABS]
    return refs


def primer_text() -> str:
    """The vocabulary sentence that goes into the profile primer."""
    return ", ".join(all_refs())
