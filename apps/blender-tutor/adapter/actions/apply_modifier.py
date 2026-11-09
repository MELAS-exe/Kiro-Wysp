"""apply_modifier: bake a modifier into the mesh. IRREVERSIBLE through Wysp (Blender's own Ctrl+Z still works)."""

from __future__ import annotations

import bpy
from wysp_adapter_sdk import ActionOutcome, ErrorCode, WyspError

from .. import refs
from ._common import MODIFIER_REF, action_spec, get_modifier


def spec() -> dict:
    return action_spec(
        "apply_modifier",
        "Apply a modifier",
        "Apply a modifier: its effect is baked into the mesh and the modifier disappears. Wysp cannot undo this.",
        {"target": MODIFIER_REF},
        ["target"],
        "irreversible",
        [{"ref": "${params.target}", "path": "label", "op": "not_exists"}],
        [
            {
                "text": "In the Modifiers tab, open the arrow menu in the header of “${label:params.target}”",
                "target": "${params.target}",
            },
            {"text": "Choose Apply (or hover the panel and press Ctrl+A). This bakes it into the mesh"},
        ],
    )


def _evaluated_vertices(obj) -> int | None:
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            return len(mesh.vertices)
        finally:
            evaluated.to_mesh_clear()
    except (AttributeError, RuntimeError, ReferenceError):
        return None


def run(p: dict, dry: bool) -> ActionOutcome:
    obj, mod = get_modifier(p["target"])
    if obj.type != "MESH":
        raise WyspError(ErrorCode.PRECONDITION_FAILED, f"only mesh objects are supported (this is {obj.type})")
    if dry:
        return ActionOutcome(
            preview={
                "modifier": mod.name,
                "vertices_in_base_mesh": len(obj.data.vertices),
                "vertices_with_all_modifiers": _evaluated_vertices(obj),
                "warning": "The modifier is baked into the mesh. Wysp cannot undo this (Blender's Ctrl+Z can).",
            }
        )
    obj_ref, mod_ref, name = refs.object_ref(obj), refs.modifier_ref(obj, mod), mod.name
    with bpy.context.temp_override(object=obj, active_object=obj):
        result = bpy.ops.object.modifier_apply(modifier=name)
    if "FINISHED" not in result:
        raise WyspError(
            ErrorCode.EXECUTION_FAILED, f"Blender refused to apply '{name}' (shape keys or shared mesh data?)"
        )
    return ActionOutcome(changed=[obj_ref, mod_ref], message=f"Applied modifier '{name}'")
