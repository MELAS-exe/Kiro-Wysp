"""Helpers shared by actions: resolving refs and building ActionSpec dicts."""

from __future__ import annotations

from typing import Any

import bpy
from wysp_adapter_sdk import ErrorCode, WyspError

from .. import refs


def get_object(ref: str):
    name = refs.parse_object_ref(ref)
    obj = bpy.data.objects.get(name) if name else None
    if obj is None:
        raise WyspError(ErrorCode.TARGET_NOT_FOUND, f"no object {ref}")
    return obj


def get_modifier(ref: str):
    parsed = refs.parse_modifier_ref(ref)
    if parsed is None:
        raise WyspError(ErrorCode.TARGET_NOT_FOUND, f"not a modifier ref: {ref}")
    obj_name, mod_name = parsed
    obj = bpy.data.objects.get(obj_name)
    mod = obj.modifiers.get(mod_name) if obj else None
    if obj is None or mod is None:
        raise WyspError(ErrorCode.TARGET_NOT_FOUND, f"no modifier {ref}")
    return obj, mod


def index_of(obj, mod) -> int:
    for i, m in enumerate(obj.modifiers):
        if m.name == mod.name:
            return i
    return -1


def action_spec(
    id_: str,
    title: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
    risk: str,
    postconditions: list[dict[str, Any]],
    ui_path: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": id_,
        "title": {"en": title},
        "description": description,
        "params_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        "risk": risk,
        "reversible": risk == "reversible",
        "preconditions": [],
        "postconditions": postconditions,
        "guide": {"ui_path": ui_path},
    }


OBJECT_REF = {
    "type": "string",
    "pattern": refs.OBJECT_PATTERN,
    "description": "Ref of an object, e.g. blender://object/Cube",
}
MODIFIER_REF = {
    "type": "string",
    "pattern": refs.MODIFIER_PATTERN,
    "description": "Ref of a modifier, e.g. blender://object/Cube/modifier/Bevel",
}
