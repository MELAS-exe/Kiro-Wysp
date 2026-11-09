"""Provenance validator: no node may claim to be `observed` unless an observation backs it."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("wysp.provenance")


def validate_ops(ops: list[dict[str, Any]], observed_refs: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Downgrade unbacked `observed` nodes/edges to `inferred`. Returns (ops, warnings)."""
    warnings: list[str] = []
    out: list[dict[str, Any]] = []
    for op in ops:
        op = dict(op)
        if op.get("op") == "add_node":
            node = dict(op["node"])
            if node.get("provenance") == "observed":
                ref = node.get("ref")
                if not ref or ref not in observed_refs:
                    warnings.append(
                        f"node {node.get('id')} claimed 'observed' without a backing observation; downgraded"
                    )
                    node["provenance"] = "inferred"
                    node["ref"] = None
            op["node"] = node
        elif op.get("op") == "add_edge":
            edge = dict(op["edge"])
            if edge.get("provenance") == "observed" and not str(edge.get("id", "")).startswith("e:"):
                warnings.append(f"edge {edge.get('id')} claimed 'observed' without projection; downgraded")
                edge["provenance"] = "inferred"
            op["edge"] = edge
        elif op.get("op") == "add_annotation":
            ann = dict(op["annotation"])
            if ann.get("provenance") == "observed":
                warnings.append(f"annotation {ann.get('id')} cannot be 'observed'; downgraded")
                ann["provenance"] = "inferred"
            op["annotation"] = ann
        out.append(op)
    for w in warnings:
        log.warning(w)
    return out, warnings
