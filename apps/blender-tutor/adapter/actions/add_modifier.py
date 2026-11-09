"""add_modifier: add a modifier to an object. Reversible (the undo removes it)."""

from __future__ import annotations

import bpy
from wysp_adapter_sdk import ActionOutcome, ErrorCode, WyspError

from .. import refs
from ._common import OBJECT_REF, action_spec, get_object

DEFAULT_NAMES = {
    "SUBSURF": "Subdivision", "BEVEL": "Bevel", "SOLIDIFY": "Solidify", "MIRROR": "Mirror", "ARRAY": "Array",
    "DECIMATE": "Decimate", "WIREFRAME": "Wireframe", "SMOOTH": "Smooth", "TRIANGULATE": "Triangulate",
}  # fmt: skip


def modifier_types() -> list[str]:
    return [e.identifier for e in bpy.types.Modifier.bl_rna.properties["type"].enum_items]


def spec() -> dict:
    types = modifier_types()
    return action_spec(
        "add_modifier",
        "Add a modifier",
        "Add a modifier to an object. Common types: SUBSURF (Subdivision Surface), BEVEL, SOLIDIFY, MIRROR, ARRAY, "
        "DECIMATE, WIREFRAME, SMOOTH, TRIANGULATE.",
        {
            "target": OBJECT_REF,
            "type": {"type": "string", "enum": types},
            "name": {"type": "string", "minLength": 1, "maxLength": 40, "description": "Optional name"},
        },
        ["target", "type"],
        "reversible",
        [
            {
                "path": "entities[?kind=='modifier' && parent=='${params.target}' && props.type=='${params.type}'] | length(@)",
                "op": "gte",
                "value": 1,
            }
        ],
        [
            {
                "text": "Select “${label:params.target}” in the 3D viewport or the Outliner",
                "target": "${params.target}",
            },
            {"text": "Open the Properties editor and click the blue wrench tab (Modifiers)"},
            {"text": "Click Add Modifier, pick the category, then choose ${params.type}"},
        ],
    )


def run(p: dict, dry: bool) -> ActionOutcome:
    obj = get_object(p["target"])
    mod_type = p["type"]
    name = p.get("name") or DEFAULT_NAMES.get(mod_type) or mod_type.replace("_", " ").title()
    if dry:
        return ActionOutcome(
            preview={"would_add": mod_type, "to": obj.name, "existing_modifiers": [m.name for m in obj.modifiers]}
        )
    try:
        mod = obj.modifiers.new(name=name, type=mod_type)
    except (TypeError, RuntimeError, ValueError) as exc:
        raise WyspError(
            ErrorCode.PRECONDITION_FAILED, f"cannot add {mod_type} to {obj.name} ({obj.type}): {exc}"
        ) from exc
    obj_name, mod_name = obj.name, mod.name

    def undo() -> None:
        o = bpy.data.objects.get(obj_name)
        m = o.modifiers.get(mod_name) if o else None
        if m is not None:
            o.modifiers.remove(m)

    return ActionOutcome(
        changed=[refs.object_ref(obj), refs.modifier_ref(obj, mod)],
        undo=undo,
        message=f"Added {mod_type} modifier '{mod_name}' to {obj_name}",
    )
