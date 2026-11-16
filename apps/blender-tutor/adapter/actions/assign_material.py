"""assign_material: put an existing material on an object. Reversible.

Slot handling: the material goes into the object's first slot (index 0), the one the observation reports as
`props.material`. Other slots are never touched. When the object has no slot, one is created (and removed again
by undo). Materials are never created: the name must match a material that already exists in the file.
Mesh data is shared by every object that uses it, so assigning through a slot also changes those objects.
"""

from __future__ import annotations

import bpy
from wysp_adapter_sdk import ActionOutcome, ErrorCode, WyspError

from ._common import OBJECT_REF, action_spec, get_object


def spec() -> dict:
    return action_spec(
        "assign_material",
        "Assign a material",
        "Put an existing material (by name, see the material entities) on an object's first material slot. "
        "A slot is added when the object has none. The action never creates materials.",
        {"target": OBJECT_REF, "material": {"type": "string", "minLength": 1, "maxLength": 63}},
        ["target", "material"],
        "reversible",
        [{"ref": "${params.target}", "path": "props.material", "op": "eq", "value": "${params.material}"}],
        [
            {
                "text": "Select “${label:params.target}” in the 3D viewport or the Outliner",
                "target": "${params.target}",
            },
            {
                "text": "In the Properties editor, open the Material tab",
                "target": "blender://ui/properties/tab/MATERIAL",
            },
            {
                "text": "Click the browse-material button next to the slot and pick “${params.material}”",
                "target": "blender://ui/properties/tab/MATERIAL",
            },
        ],
    )


def run(p: dict, dry: bool) -> ActionOutcome:
    obj = get_object(p["target"])
    name = p["material"]
    if not isinstance(name, str) or not name:
        raise WyspError(ErrorCode.INVALID_PARAMS, "material must be a non-empty name")
    mat = bpy.data.materials.get(name)
    if mat is None:
        raise WyspError(
            ErrorCode.TARGET_NOT_FOUND,
            f"no material '{name}' (materials are never created)",
            {"materials": sorted(m.name for m in bpy.data.materials)[:40]},
        )
    slots = list(obj.material_slots)
    created = not slots
    if created and not hasattr(obj.data, "materials"):
        raise WyspError(ErrorCode.PRECONDITION_FAILED, f"{obj.type} objects cannot hold a material")
    before = slots[0].material if slots else None
    before_name = before.name if before is not None else None
    if dry:
        return ActionOutcome(preview={"from": before_name, "to": name, "new_slot": created})
    try:
        if created:
            obj.data.materials.append(mat)
        else:
            slots[0].material = mat
    except (TypeError, ValueError, RuntimeError) as exc:
        raise WyspError(ErrorCode.PRECONDITION_FAILED, f"Blender refused material '{name}': {exc}") from exc

    obj_name = obj.name

    def undo() -> None:
        o = bpy.data.objects.get(obj_name)
        if o is None:
            return
        if created:
            if len(o.material_slots) and hasattr(o.data, "materials"):
                o.data.materials.pop(index=0)
        elif len(o.material_slots):
            o.material_slots[0].material = bpy.data.materials.get(before_name) if before_name else None

    return ActionOutcome(changed=[p["target"]], undo=undo, message=f"{obj.name}: material {before_name} → {name}")
