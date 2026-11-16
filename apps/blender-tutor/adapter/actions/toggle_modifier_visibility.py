"""toggle_modifier_visibility: show or hide a modifier in the viewport or in renders. Reversible."""

from __future__ import annotations

import bpy
from wysp_adapter_sdk import ActionOutcome, ErrorCode, WyspError

from ._common import MODIFIER_REF, action_spec, get_modifier

WHICH = ["viewport", "render"]


def spec() -> dict:
    return action_spec(
        "toggle_modifier_visibility",
        "Show or hide a modifier",
        "Turn a modifier on or off in the 3D viewport (which=viewport, the monitor icon) or in final renders "
        "(which=render, the camera icon). The modifier stays in the stack; only its effect is switched. "
        "Current values are `show_viewport` and `show_render` under `props` of the modifier entity.",
        {
            "target": MODIFIER_REF,
            "which": {"type": "string", "enum": WHICH},
            "value": {"type": "boolean"},
        },
        ["target", "which", "value"],
        "reversible",
        [
            {
                "ref": "${params.target}",
                "path": "get(props, 'show_${params.which}')",
                "op": "eq",
                "value": "${params.value}",
            }
        ],
        [
            {"text": "In the Modifiers tab, find the “${label:params.target}” panel", "target": "${params.target}"},
            {
                "text": "In its header, click the monitor icon (viewport) or the camera icon (render) "
                "to set ${params.which} to ${params.value}",
                "target": "${params.target}",
            },
        ],
    )


def run(p: dict, dry: bool) -> ActionOutcome:
    which, value = p["which"], p["value"]
    if which not in WHICH:
        raise WyspError(ErrorCode.INVALID_PARAMS, f"which must be one of {WHICH}")
    if not isinstance(value, bool):
        raise WyspError(ErrorCode.INVALID_PARAMS, "value must be true or false")
    obj, mod = get_modifier(p["target"])
    attr = f"show_{which}"
    before = bool(getattr(mod, attr))
    if dry:
        return ActionOutcome(preview={"which": which, "from": before, "to": value})
    try:
        setattr(mod, attr, value)
    except (TypeError, ValueError, RuntimeError) as exc:
        raise WyspError(ErrorCode.PRECONDITION_FAILED, f"Blender refused {attr}={value!r}: {exc}") from exc

    obj_name, mod_name = obj.name, mod.name

    def undo() -> None:
        # Look the modifier up again: it may have been removed and recreated since (see remove_modifier).
        o = bpy.data.objects.get(obj_name)
        m = o.modifiers.get(mod_name) if o else None
        if m is not None:
            setattr(m, attr, before)

    return ActionOutcome(changed=[p["target"]], undo=undo, message=f"{mod.name}.{attr}: {before} → {value}")
