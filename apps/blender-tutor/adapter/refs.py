"""Entity refs for Blender data. Names are percent-encoded so that refs stay valid URIs."""

from __future__ import annotations

import re
from urllib.parse import quote, unquote

OBJECT_RE = re.compile(r"^blender://object/([^/]+)$")
MODIFIER_RE = re.compile(r"^blender://object/([^/]+)/modifier/([^/]+)$")
MATERIAL_RE = re.compile(r"^blender://material/([^/]+)$")

OBJECT_PATTERN = r"^blender://object/[^/]+$"
MODIFIER_PATTERN = r"^blender://object/[^/]+/modifier/[^/]+$"


def q(name: str) -> str:
    return quote(name, safe="")


def scene_ref(scene) -> str:
    return f"blender://scene/{q(scene.name)}"


def collection_ref(collection) -> str:
    return f"blender://collection/{q(collection.name)}"


def object_ref(obj) -> str:
    return f"blender://object/{q(obj.name)}"


def modifier_ref(obj, mod) -> str:
    return f"{object_ref(obj)}/modifier/{q(mod.name)}"


def material_ref(mat) -> str:
    return f"blender://material/{q(mat.name)}"


def parse_object_ref(ref: str) -> str | None:
    m = OBJECT_RE.match(ref)
    return unquote(m.group(1)) if m else None


def parse_modifier_ref(ref: str) -> tuple[str, str] | None:
    m = MODIFIER_RE.match(ref)
    return (unquote(m.group(1)), unquote(m.group(2))) if m else None
