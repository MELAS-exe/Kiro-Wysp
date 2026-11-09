"""remove_modifier: delete a modifier. Reversible (the undo recreates it with its settings and position)."""

from __future__ import annotations

import bpy
from wysp_adapter_sdk import ActionOutcome

from .. import refs
from ..rna_props import settable_values
from ._common import MODIFIER_REF, action_spec, get_modifier, index_of


def spec() -> dict:
    return action_spec(
        "remove_modifier",
        "Remove a modifier",
        "Delete a modifier from an object's stack.",
        {"target": MODIFIER_REF},
        ["target"],
        "reversible",
        [{"ref": "${params.target}", "path": "label", "op": "not_exists"}],
        [
            {"text": "In the Modifiers tab, find “${label:params.target}”"},
            {"text": "Click the small arrow in its header and choose Delete (or press Ctrl+X over it)"},
        ],
    )


def run(p: dict, dry: bool) -> ActionOutcome:
    obj, mod = get_modifier(p["target"])
    saved = {"type": mod.type, "name": mod.name, "index": index_of(obj, mod), "values": settable_values(mod)}
    if dry:
        return ActionOutcome(preview={"would_remove": saved["name"], "type": saved["type"]})
    obj_name = obj.name
    ref_obj = refs.object_ref(obj)
    ref_mod = refs.modifier_ref(obj, mod)
    obj.modifiers.remove(mod)

    def undo() -> None:
        o = bpy.data.objects.get(obj_name)
        if o is None:
            return
        new = o.modifiers.new(name=saved["name"], type=saved["type"])
        for pid, value in saved["values"].items():
            try:
                setattr(new, pid, value)
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass  # read-only or context-dependent in this state; the rest is still restored
        last = len(o.modifiers) - 1
        if saved["index"] != last and 0 <= saved["index"] <= last:
            o.modifiers.move(last, saved["index"])

    return ActionOutcome(changed=[ref_obj, ref_mod], undo=undo, message=f"Removed modifier '{saved['name']}'")
