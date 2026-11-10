"""set_object_transform: set an object's location, rotation (degrees) or scale. Reversible."""

from __future__ import annotations

import math

from wysp_adapter_sdk import ActionOutcome, ErrorCode, WyspError

from ._common import OBJECT_REF, action_spec, get_object

PROPERTIES = ["location", "rotation", "scale"]
LIMITS = {"location": 1.0e5, "rotation": 1.0e4, "scale": 1.0e4}
# The observation rounds location and scale to 3 decimals and rotation to 1: round the same way, so the
# postcondition (observed value == requested value) holds for any value Blender accepted.
DIGITS = {"location": 3, "rotation": 1, "scale": 3}


def spec() -> dict:
    return action_spec(
        "set_object_transform",
        "Move, rotate or scale an object",
        "Set an object's location (metres), rotation (degrees, XYZ Euler) or scale (1 = original size) to "
        "exact [x, y, z] values. To make an object bigger, multiply its current scale (see its props). "
        "Values are rounded to 3 decimals (1 for rotation).",
        {
            "target": OBJECT_REF,
            "property": {"type": "string", "enum": PROPERTIES},
            "value": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
        },
        ["target", "property", "value"],
        "reversible",
        [
            {
                "ref": "${params.target}",
                "path": "get(props, '${params.property}')",
                "op": "eq",
                "value": "${params.value}",
            }
        ],
        [
            {
                "text": "Select “${label:params.target}” in the 3D viewport or the Outliner",
                "target": "${params.target}",
            },
            {
                "text": "In the Properties editor, open the Object tab (orange square)",
                "target": "blender://ui/properties/tab/OBJECT",
            },
            {
                "text": "Under Transform, type ${params.value} into the ${params.property} fields",
                "target": "blender://ui/label/PROPERTIES/${params.property}",
            },
        ],
    )


def _validated(p: dict) -> tuple[str, list[float]]:
    prop = p["property"]
    if prop not in PROPERTIES:
        raise WyspError(ErrorCode.INVALID_PARAMS, f"property must be one of {PROPERTIES}")
    values = [float(v) for v in p["value"]]
    if any(not math.isfinite(v) or abs(v) > LIMITS[prop] for v in values):
        raise WyspError(ErrorCode.INVALID_PARAMS, f"{prop} values must be finite and within ±{LIMITS[prop]:g}")
    if prop == "scale" and any(v == 0 for v in values):
        raise WyspError(ErrorCode.INVALID_PARAMS, "a scale of 0 would flatten the object; use a small value instead")
    return prop, [round(v, DIGITS[prop]) for v in values]


def run(p: dict, dry: bool) -> ActionOutcome:
    obj = get_object(p["target"])
    prop, values = _validated(p)
    attr = "rotation_euler" if prop == "rotation" else prop
    before = tuple(getattr(obj, attr))
    if prop == "rotation":
        shown_before = [round(math.degrees(a), 1) for a in before]
        new = [math.radians(v) for v in values]
    else:
        shown_before = [round(v, 3) for v in before]
        new = values
    if dry:
        return ActionOutcome(preview={"property": prop, "from": shown_before, "to": values})
    setattr(obj, attr, new)

    def undo() -> None:
        setattr(obj, attr, before)

    return ActionOutcome(changed=[p["target"]], undo=undo, message=f"{obj.name}.{prop}: {shown_before} -> {values}")
