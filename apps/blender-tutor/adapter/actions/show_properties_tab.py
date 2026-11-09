"""show_properties_tab: switch the Properties editor to a tab. UI state only; needs a window (not headless)."""

from __future__ import annotations

import bpy
from wysp_adapter_sdk import ActionOutcome, ErrorCode, WyspError

from ._common import action_spec

TABS = ["OBJECT", "MODIFIER", "DATA", "MATERIAL"]


def properties_areas():
    wm = bpy.context.window_manager
    for window in getattr(wm, "windows", []):
        for area in window.screen.areas:
            if area.type == "PROPERTIES":
                yield area


def switch_tab(tab: str) -> bool:
    done = False
    for area in properties_areas():
        space = area.spaces.active
        try:
            space.context = tab
            area.tag_redraw()
            done = True
        except (TypeError, ValueError):
            continue  # tab not available for the active object
    return done


def spec() -> dict:
    return action_spec(
        "show_properties_tab",
        "Show a Properties tab",
        "Switch the Properties editor to a tab: MODIFIER (blue wrench), MATERIAL, OBJECT or DATA.",
        {"tab": {"type": "string", "enum": TABS}},
        ["tab"],
        "ui_state",
        [],
        [
            {
                "text": "In the Properties editor, click the ${params.tab} tab icon",
                "target": "blender://ui/properties/tab/${params.tab}",
            }
        ],
    )


def run(p: dict, dry: bool) -> ActionOutcome:
    if dry:
        return ActionOutcome()
    if not any(True for _ in properties_areas()):
        raise WyspError(ErrorCode.NOT_SUPPORTED, "there is no Properties editor (Blender is running without a window)")
    if not switch_tab(p["tab"]):
        raise WyspError(ErrorCode.PRECONDITION_FAILED, f"the {p['tab']} tab is not available for the active object")
    return ActionOutcome(message=f"Showing the {p['tab']} tab")
