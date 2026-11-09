"""select_object: make an object the active, selected object. UI state only."""

from __future__ import annotations

import bpy
from wysp_adapter_sdk import ActionOutcome

from ._common import OBJECT_REF, action_spec, get_object


def spec() -> dict:
    return action_spec(
        "select_object",
        "Select an object",
        "Select an object and make it the active object, so that the Properties editor shows it.",
        {"target": OBJECT_REF},
        ["target"],
        "ui_state",
        [{"path": "focus", "op": "contains", "value": "${params.target}"}],
        [
            {
                "text": "Click “${label:params.target}” in the 3D viewport or in the Outliner",
                "target": "${params.target}",
            }
        ],
    )


def run(p: dict, dry: bool) -> ActionOutcome:
    obj = get_object(p["target"])
    if dry:
        return ActionOutcome()
    view_layer = bpy.context.view_layer
    for other in view_layer.objects:
        if other.select_get():
            other.select_set(False)
    obj.select_set(True)
    view_layer.objects.active = obj
    return ActionOutcome(changed=[p["target"]], message=f"Selected {obj.name}")
