"""Observation: the Blender scene as an application-independent entity graph."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import bpy

from . import refs
from .rna_props import modifier_props

MAX_ENTITIES = 500


def manifest() -> dict:
    return {
        "adapter_id": "blender-tutor",
        "app": {"name": "Blender", "version": bpy.app.version_string},
        "contract_version": "1.0.0",
        "integration_level": "native",
        "ref_scheme": "blender",
        "capabilities": [
            "observe",
            "context",
            "actions",
            "execute",
            "undo",
            "highlight",
            "events.state",
            "events.selection",
            "events.user_action",
        ],  # fmt: skip
        "entity_kinds": [
            {"kind": "scene", "label": "Scene", "description": "A Blender scene containing collections and objects"},
            {"kind": "collection", "label": "Collection", "description": "A group of objects"},
            {"kind": "object", "label": "Object", "description": "A 3D object (mesh, light, camera...)"},
            {
                "kind": "modifier",
                "label": "Modifier",
                "description": "A non-destructive operation in an object's modifier stack, evaluated top to bottom",
            },
            {"kind": "material", "label": "Material", "description": "Describes how a surface looks"},
        ],  # fmt: skip
        "volatile_props": [],
        "locales": ["en"],
        "profile_id": "blender-tutor",
    }


def _vec(v, digits: int = 3) -> list[float]:
    return [round(float(x), digits) for x in v]


def focus_refs(view_layer=None) -> list[str]:
    vl = view_layer or bpy.context.view_layer
    out: list[str] = []
    active = vl.objects.active
    if active is not None:
        out.append(refs.object_ref(active))
    for obj in vl.objects:
        if obj.select_get() and (active is None or obj.name != active.name):
            out.append(refs.object_ref(obj))
    return out


def build_entities(scene) -> tuple[list[dict], list[dict], bool]:
    """Return (entities, links, truncated). Order: scene, collections, objects, modifiers, materials."""
    scene_r = refs.scene_ref(scene)
    entities: list[dict] = [
        {"ref": scene_r, "kind": "scene", "label": scene.name, "props": {"objects": len(scene.objects)}}
    ]
    links: list[dict] = []
    truncated = False
    obj_parent: dict[str, str] = {}  # object name -> parent ref (collection or scene)

    def walk(coll, parent_ref: str) -> None:
        for obj in coll.objects:
            obj_parent.setdefault(obj.name, parent_ref)
        for child in coll.children:
            cref = refs.collection_ref(child)
            entities.append(
                {
                    "ref": cref,
                    "kind": "collection",
                    "label": child.name,
                    "parent": parent_ref,
                    "props": {"objects": len(child.objects)},
                }
            )
            walk(child, cref)

    walk(scene.collection, scene_r)
    objects = sorted(scene.objects, key=lambda o: o.name)
    present = {o.name for o in objects}
    materials: dict[str, object] = {}
    for obj in objects:
        props = {
            "type": obj.type,
            "modifiers_count": len(obj.modifiers),
            "location": _vec(obj.location),
            "dimensions": _vec(obj.dimensions),
            "hide_viewport": bool(obj.hide_viewport),
        }
        if obj.type == "MESH" and obj.data is not None:
            props["vertices"] = len(obj.data.vertices)
        mats = [slot.material for slot in obj.material_slots if slot.material is not None]
        if mats:
            props["material"] = mats[0].name
        entities.append(
            {
                "ref": refs.object_ref(obj),
                "kind": "object",
                "label": obj.name,
                "parent": obj_parent.get(obj.name, scene_r),
                "props": props,
            }
        )
        if obj.parent is not None and obj.parent.name in present:
            links.append({"from": refs.object_ref(obj), "to": refs.object_ref(obj.parent), "kind": "child_of"})
        for mat in mats:
            materials[mat.name] = mat
            links.append({"from": refs.object_ref(obj), "to": refs.material_ref(mat), "kind": "uses_material"})
    for obj in objects:
        for index, mod in enumerate(obj.modifiers):
            if len(entities) >= MAX_ENTITIES:
                truncated = True
                break
            props, referenced = modifier_props(mod)
            props.update(
                {
                    "type": mod.type,
                    "index": index,
                    "show_viewport": bool(mod.show_viewport),
                    "show_render": bool(mod.show_render),
                }
            )
            entities.append(
                {
                    "ref": refs.modifier_ref(obj, mod),
                    "kind": "modifier",
                    "label": mod.name,
                    "parent": refs.object_ref(obj),
                    "props": props,
                }
            )
            for name in referenced:
                if name in present:
                    links.append(
                        {
                            "from": refs.modifier_ref(obj, mod),
                            "to": refs.object_ref(bpy.data.objects[name]),
                            "kind": "references",
                        }
                    )
    for mat in sorted(materials.values(), key=lambda m: m.name):
        if len(entities) >= MAX_ENTITIES:
            truncated = True
            break
        entities.append(
            {"ref": refs.material_ref(mat), "kind": "material", "label": mat.name, "props": {"users": mat.users}}
        )
    known = {e["ref"] for e in entities}
    links = [ln for ln in links if ln["from"] in known and ln["to"] in known]
    return entities, links, truncated


def _descendants(entities: list[dict], root: str) -> set[str]:
    keep = {root}
    changed = True
    while changed:
        changed = False
        for e in entities:
            if e.get("parent") in keep and e["ref"] not in keep:
                keep.add(e["ref"])
                changed = True
    return keep


def build_observation(state_version: int, scope: dict | None = None) -> dict:
    scope = scope or {}
    scene = bpy.context.scene
    entities, links, truncated = build_entities(scene)
    counts: dict[str, int] = {}
    for e in entities:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    root = scope.get("root")
    if root:
        keep = _descendants(entities, root)
        entities = [e for e in entities if e["ref"] in keep]
        links = [ln for ln in links if ln["from"] in keep and ln["to"] in keep]
    known = {e["ref"] for e in entities}
    return {
        "observation_id": uuid.uuid4().hex[:8],
        "state_version": state_version,
        "captured_at": datetime.now(UTC).isoformat(),
        "scope": {k: v for k, v in scope.items() if k in ("level", "root", "depth")} or {"level": "focus"},
        "entities": entities,
        "links": links,
        "focus": [r for r in focus_refs() if r in known],
        "truncated": truncated,
        "counts": counts,
    }


def build_context(state_version: int) -> dict:
    scene = bpy.context.scene
    active = bpy.context.view_layer.objects.active
    selected = [o.name for o in bpy.context.view_layer.objects if o.select_get()]
    summary = f"Scene '{scene.name}' with {len(scene.objects)} objects."
    if active is not None:
        mods = ", ".join(m.name for m in active.modifiers) or "no modifiers"
        summary += f" Active object: '{active.name}' ({active.type}) with {mods}."
    else:
        summary += " No active object."
    return {
        "summary": summary,
        "mode": bpy.context.mode,
        "focus": focus_refs(),
        "facts": {
            "active_object": active.name if active else None,
            "selected": selected[:10],
            "frame": scene.frame_current,
            "blender": bpy.app.version_string,
        },
    }
