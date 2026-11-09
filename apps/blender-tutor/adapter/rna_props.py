"""Generic RNA property extraction for modifiers: no code per modifier type.

Every modifier type of the running Blender version is covered, because we read the RNA definition
instead of hard-coding properties. The same function decides which properties may be set.
"""

from __future__ import annotations

import bpy

SIMPLE_TYPES = {"BOOLEAN", "INT", "FLOAT", "ENUM", "STRING"}
# Properties that are UI state or identity, not part of the modifier's behaviour.
SKIP = {
    "name", "rna_type", "type", "show_expanded", "show_in_editmode", "show_on_cage", "is_active",
    "is_override_data", "use_pin_to_last", "persistent_uid", "execution_time",
}  # fmt: skip
MAX_PROPS = 30
FLOAT_DIGITS = 4


def _round(value):
    return round(value, FLOAT_DIGITS) if isinstance(value, float) else value


def _read(mod, prop):
    value = getattr(mod, prop.identifier)
    if prop.type == "ENUM" and prop.is_enum_flag:
        return sorted(value)
    if getattr(prop, "array_length", 0) > 0:
        if prop.array_length > 4:
            return None
        return [_round(float(v)) if prop.type == "FLOAT" else v for v in value]
    return _round(value)


def is_settable(prop) -> bool:
    """Only scalar, writable, simple-typed properties can be set by Wysp."""
    return (
        prop.type in SIMPLE_TYPES
        and not prop.is_readonly
        and prop.identifier not in SKIP
        and getattr(prop, "array_length", 0) == 0
        and not (prop.type == "ENUM" and prop.is_enum_flag)
    )


def modifier_props(mod) -> tuple[dict, list[str]]:
    """Return (props, referenced_object_names) for a modifier, JSON-serialisable and capped at 30."""
    props: dict = {}
    refs: list[str] = []
    for prop in mod.bl_rna.properties:
        if len(props) >= MAX_PROPS:
            break
        pid = prop.identifier
        if pid in SKIP:
            continue
        if prop.type == "POINTER":
            value = getattr(mod, pid, None)
            if isinstance(value, bpy.types.Object):
                props[pid] = value.name
                refs.append(value.name)
            continue
        if prop.type not in SIMPLE_TYPES:
            continue
        value = _read(mod, prop)
        if value is not None:
            props[pid] = value
    return props, refs


def settable_properties(mod) -> dict:
    return {p.identifier: p for p in mod.bl_rna.properties if is_settable(p)}


def settable_values(mod) -> dict:
    """Current values of every settable property, to restore a modifier on undo."""
    return {pid: getattr(mod, pid) for pid in settable_properties(mod)}


def check_and_coerce(prop, value):
    """Validate `value` for `prop` and return it in the type Blender expects. Raises ValueError."""
    if prop.type == "BOOLEAN":
        if not isinstance(value, bool):
            raise ValueError(f"{prop.identifier} expects true or false")
        return value
    if prop.type == "INT":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
            raise ValueError(f"{prop.identifier} expects a whole number")
        return int(value)
    if prop.type == "FLOAT":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{prop.identifier} expects a number")
        return float(value)
    if prop.type == "ENUM":
        allowed = [item.identifier for item in prop.enum_items]
        if value not in allowed:
            raise ValueError(f"{prop.identifier} must be one of {allowed}")
        return value
    if prop.type == "STRING":
        if not isinstance(value, str):
            raise ValueError(f"{prop.identifier} expects text")
        return value
    raise ValueError(f"{prop.identifier} cannot be set")
