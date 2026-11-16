"""move_modifier: change the position of a modifier in the stack (evaluation order). Reversible."""

from __future__ import annotations

import bpy
from wysp_adapter_sdk import ActionOutcome, ErrorCode, WyspError

from ._common import MODIFIER_REF, action_spec, get_modifier, index_of


def spec() -> dict:
    return action_spec(
        "move_modifier",
        "Reorder a modifier",
        "Move a modifier to another position in the stack. Index 0 is evaluated first. Order changes the result.",
        {"target": MODIFIER_REF, "index": {"type": "integer", "minimum": 0, "maximum": 63}},
        ["target", "index"],
        "reversible",
        [{"ref": "${params.target}", "path": "props.index", "op": "eq", "value": "${params.index}"}],
        [
            {
                "text": "In the Modifiers tab, drag the grip (⠿) of “${label:params.target}” to position ${params.index}",
                "target": "${params.target}",
            },
        ],
    )


def run(p: dict, dry: bool) -> ActionOutcome:
    obj, mod = get_modifier(p["target"])
    current, target = index_of(obj, mod), p["index"]
    if target >= len(obj.modifiers):
        raise WyspError(
            ErrorCode.PRECONDITION_FAILED,
            f"the stack has {len(obj.modifiers)} modifiers: index {target} is out of range",
        )
    if dry:
        return ActionOutcome(preview={"from": current, "to": target})
    if current != target:
        obj.modifiers.move(current, target)

    obj_name, mod_name = obj.name, mod.name

    def undo() -> None:
        # Resolve by name at undo time: the modifier may have been removed and recreated since (see remove_modifier).
        o = bpy.data.objects.get(obj_name)
        m = o.modifiers.get(mod_name) if o else None
        if m is None:
            return
        now = index_of(o, m)
        if now != current and 0 <= current < len(o.modifiers):
            o.modifiers.move(now, current)

    return ActionOutcome(changed=[p["target"]], undo=undo, message=f"Moved '{mod.name}' from {current} to {target}")
