"""State digest: a canonical hash of an observation that defines "same application state"."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from typing import Any

from .observation import Observation

SIGNIFICANT_DIGITS = 6


def _round(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        if value == 0.0:
            return 0.0
        digits = SIGNIFICANT_DIGITS - int(math.floor(math.log10(abs(value)))) - 1
        return round(value, digits)
    if isinstance(value, dict):
        return {k: _round(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round(v) for v in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_round(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(obs: Observation, volatile_props: Iterable[str] = ()) -> str:
    """SHA-256 over entities (sorted by ref) and links (sorted), ignoring volatile props.

    Ignored on purpose: observation id, capture time, state version, focus, entity order.
    """
    volatile = set(volatile_props)
    entities = sorted(
        (
            {
                "ref": e.ref,
                "kind": e.kind,
                "parent": e.parent,
                "props": {k: v for k, v in e.props.items() if k not in volatile},
            }
            for e in obs.entities
        ),
        key=lambda d: d["ref"],
    )
    links = sorted(
        ({"from": ln.from_, "to": ln.to, "kind": ln.kind} for ln in obs.links),
        key=lambda d: (d["from"], d["to"], d["kind"]),
    )
    return hashlib.sha256(canonical_json({"entities": entities, "links": links}).encode("utf-8")).hexdigest()
