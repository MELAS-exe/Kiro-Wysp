"""set_modifier_property: change one setting of a modifier. Reversible."""

from __future__ import annotations

from wysp_adapter_sdk import ActionOutcome, ErrorCode, WyspError

from ..rna_props import check_and_coerce, settable_properties
from ._common import MODIFIER_REF, action_spec, get_modifier


def spec() -> dict:
    return action_spec(
        "set_modifier_property",
        "Change a modifier setting",
        "Set one property of a modifier (for example levels of SUBSURF, segments or width of BEVEL, thickness of SOLIDIFY). "
        "The property names are the keys under `props` of the modifier entity.",
        {
            "target": MODIFIER_REF,
            "property": {"type": "string", "minLength": 1, "maxLength": 60},
            "value": {"type": ["string", "number", "boolean"]},
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
            {"text": "In the Modifiers tab, find the “${label:params.target}” panel", "target": "${params.target}"},
            {
                "text": "Set ${params.property} to ${params.value}",
                "target": "blender://ui/label/PROPERTIES/${params.property}",
            },
        ],
    )


def run(p: dict, dry: bool) -> ActionOutcome:
    obj, mod = get_modifier(p["target"])
    props = settable_properties(mod)
    pid = p["property"]
    if pid not in props:
        raise WyspError(
            ErrorCode.PRECONDITION_FAILED,
            f"'{pid}' is not a settable property of {mod.type}",
            {"settable": sorted(props)[:40]},
        )
    try:
        value = check_and_coerce(props[pid], p["value"])
    except ValueError as exc:
        raise WyspError(ErrorCode.INVALID_PARAMS, str(exc)) from exc
    before = getattr(mod, pid)
    if dry:
        return ActionOutcome(preview={"property": pid, "from": before, "to": value})
    try:
        setattr(mod, pid, value)
    except (TypeError, ValueError, OverflowError, RuntimeError) as exc:
        raise WyspError(ErrorCode.PRECONDITION_FAILED, f"Blender refused {pid}={value!r}: {exc}") from exc

    def undo() -> None:
        setattr(mod, pid, before)

    return ActionOutcome(changed=[p["target"]], undo=undo, message=f"{mod.name}.{pid}: {before} → {getattr(mod, pid)}")
