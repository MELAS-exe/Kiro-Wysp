"""Projection: observed entities become board nodes. The LLM picks refs; this code builds nodes.

Deterministic: the same observation and refs always give the same nodes and edges.
"""

from __future__ import annotations

from typing import Any

from ..contract import Entity, Observation

MAX_PROPS_VIEW = 6


def node_id(ref: str) -> str:
    return f"n:{ref}"


def format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(format_value(v) for v in value[:4]) + (", …" if len(value) > 4 else "") + "]"
    if isinstance(value, dict):
        return "{…}"
    return str(value)


def props_view(entity: Entity, wanted: list[str] | None) -> list[list[str]]:
    props = entity.props
    keys = [k for k in (wanted or []) if k in props]
    if not wanted:
        keys = [k for k in sorted(props) if not isinstance(props[k], (dict, list)) and props[k] is not None]
    return [[k, format_value(props[k])] for k in keys[:MAX_PROPS_VIEW]]


def entity_to_node(entity: Entity, props_config: dict[str, list[str]] | None = None) -> dict[str, Any]:
    order = entity.props.get("index")
    return {
        "id": node_id(entity.ref),
        "ref": entity.ref,
        "kind": entity.kind,
        "label": entity.label,
        "provenance": "observed",
        "confidence": entity.confidence,
        "props_view": props_view(entity, (props_config or {}).get(entity.kind)),
        "order": order if isinstance(order, int) and not isinstance(order, bool) else None,
    }


def project(
    observation: Observation,
    refs: list[str],
    include_children: bool = False,
    props_config: dict[str, list[str]] | None = None,
    max_depth: int = 2,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (ops, missing_refs). Ops add nodes and the edges between nodes that are both selected."""
    by_ref = {e.ref: e for e in observation.entities}
    selected: dict[str, Entity] = {}
    missing: list[str] = []

    def add(ref: str, depth: int) -> None:
        entity = by_ref.get(ref)
        if entity is None or ref in selected:
            return
        selected[ref] = entity
        if include_children and depth < max_depth:
            for child in observation.children_of(ref):
                add(child.ref, depth + 1)

    for ref in refs:
        if ref not in by_ref:
            missing.append(ref)
        else:
            add(ref, 0)

    ops: list[dict[str, Any]] = [{"op": "add_node", "node": entity_to_node(e, props_config)} for e in selected.values()]
    for e in selected.values():
        if e.parent and e.parent in selected:
            ops.append(
                {
                    "op": "add_edge",
                    "edge": {
                        "id": f"e:{e.parent}>{e.ref}:contains",
                        "source": node_id(e.parent),
                        "target": node_id(e.ref),
                        "kind": "contains",
                        "provenance": "observed",
                    },
                }
            )
    for link in observation.links:
        if link.from_ in selected and link.to in selected:
            ops.append(
                {
                    "op": "add_edge",
                    "edge": {
                        "id": f"e:{link.from_}>{link.to}:{link.kind}",
                        "source": node_id(link.from_),
                        "target": node_id(link.to),
                        "kind": link.kind,
                        "provenance": "observed",
                    },
                }
            )
    return ops, missing
