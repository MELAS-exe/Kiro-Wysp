"""Smoke probe run inside Blender: observe, list actions, run each action and undo it, check digests.

blender -b --python-use-system-env scene.blend --python probe_adapter.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import run_adapter  # noqa: E402

run_adapter.load_adapter()
from wysp_tutor.runtime import BlenderAdapter  # noqa: E402

adapter = BlenderAdapter()


def call(method, params=None):
    return adapter.handle(method, params or {})


obs = call("adapter.observe", {"level": "full"})
print("PROBE entities:", len(obs["entities"]), "kinds:", sorted({e["kind"] for e in obs["entities"]}))
print("PROBE focus:", obs["focus"])
pumpkin_mods = [e for e in obs["entities"] if e["kind"] == "modifier"]
print("PROBE modifiers:", [(e["label"], e["props"].get("type"), e["props"].get("index")) for e in pumpkin_mods])
print("PROBE sub props:", json.dumps(pumpkin_mods[0]["props"])[:300])
print("PROBE context:", call("adapter.get_context")["summary"])
specs = call("adapter.get_actions")
print("PROBE actions:", [s["id"] for s in specs])

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "core" / "src"))
import hashlib  # noqa: E402


def digest():
    o = call("adapter.observe", {"level": "full"})
    items = sorted(
        (e["ref"], e["kind"], e.get("parent"), json.dumps(e["props"], sort_keys=True)) for e in o["entities"]
    )
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()[:10]


def run(action_id, params):
    return call("adapter.execute", {"call": {"action_id": action_id, "params": params, "request_id": "t"}})


before = digest()
r = run("add_modifier", {"target": "blender://object/Candle", "type": "BEVEL"})
print("PROBE add:", r["status"], r["changed"], r.get("undo_token"))
mid = digest()
print("PROBE changed after add:", before != mid)
call("adapter.undo", {"token": r["undo_token"]})
print("PROBE undo restores digest:", digest() == before)

for aid, params in [
    (
        "set_modifier_property",
        {"target": "blender://object/Pumpkin/modifier/Subdivision", "property": "levels", "value": 1},
    ),
    ("move_modifier", {"target": "blender://object/Pumpkin/modifier/Solidify", "index": 0}),
    ("remove_modifier", {"target": "blender://object/Pumpkin/modifier/Solidify"}),
]:
    b = digest()
    r = run(aid, params)
    changed = digest() != b
    call("adapter.undo", {"token": r["undo_token"]})
    print(f"PROBE {aid}: changed={changed} undo_restores={digest() == b}")

d = run("apply_modifier", {"target": "blender://object/Pumpkin/modifier/Subdivision"})
print("PROBE apply (real run, irreversible):", d["status"], d["changed"])
errors = []
for aid, params in [("add_modifier", {"target": "blender://object/Nope", "type": "BEVEL"}), ("bogus", {})]:
    try:
        run(aid, params)
    except Exception as exc:  # noqa: BLE001
        errors.append((aid, getattr(exc, "code", None)))
print("PROBE errors:", errors)
print("PROBE-DONE")
