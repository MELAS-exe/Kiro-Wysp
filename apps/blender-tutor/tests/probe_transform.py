"""Probe: set_object_transform runs, satisfies its own postcondition, and undo restores the state digest.

blender -b --factory-startup --python-use-system-env pumpkin.blend --python probe_transform.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import run_adapter  # noqa: E402

run_adapter.load_adapter()
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "core" / "src"))
from wysp_core.contract import Observation  # noqa: E402
from wysp_core.contract.predicates import evaluate, substitute  # noqa: E402
from wysp_tutor.runtime import BlenderAdapter  # noqa: E402

adapter = BlenderAdapter()


def call(method, params=None):
    return adapter.handle(method, params or {})


def digest() -> str:
    obs = call("adapter.observe", {"level": "full"})
    return hashlib.sha1(json.dumps(obs["entities"], sort_keys=True).encode()).hexdigest()[:12]  # noqa: S324


spec = next(s for s in call("adapter.get_actions") if s["id"] == "set_object_transform")
for prop, value in (("scale", [1.5, 1.5, 1.5]), ("rotation", [0, 0, 45]), ("location", [0.6, -0.4, 0.15])):
    before = digest()
    params = {"target": "blender://object/Candle", "property": prop, "value": value}
    res = call("adapter.execute", {"call": {"action_id": "set_object_transform", "params": params, "request_id": "p"}})
    obs = Observation.model_validate(call("adapter.observe", {"level": "full"}))
    ok = all(evaluate(substitute(pc, params), obs).ok for pc in spec["postconditions"])
    call("adapter.undo", {"token": res["undo_token"]})
    print("PROBE", prop, "postcondition", ok, "undo restores digest", digest() == before)
try:
    call("adapter.execute", {"call": {"action_id": "set_object_transform", "request_id": "q",
                                       "params": {"target": "blender://object/Candle", "property": "scale", "value": [0, 1, 1]}}})  # fmt: skip
    print("PROBE zero scale accepted (BAD)")
except Exception as exc:  # noqa: BLE001
    print("PROBE zero scale refused:", getattr(exc, "code", None))
