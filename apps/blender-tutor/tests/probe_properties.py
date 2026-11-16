"""Property probe run inside a headless Blender: BLD-P2 (compensation undo) and BLD-P3 (projection is total).

blender -b --python-use-system-env scene.blend --python probe_properties.py

Prints `PROP ...` lines read by test_prop_bld_live.py. Hypothesis runs inside Blender (PYTHONPATH holds the venv).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "apps" / "blender-tutor" / "demo"))
import run_adapter  # noqa: E402

run_adapter.load_adapter()
import jsonschema  # noqa: E402
from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402
from wysp_adapter_sdk import WyspError  # noqa: E402
from wysp_tutor.actions.add_modifier import modifier_types  # noqa: E402
from wysp_tutor.runtime import BlenderAdapter  # noqa: E402

adapter = BlenderAdapter()
ENTITY_SCHEMA = json.loads((REPO / "schemas" / "entity.schema.json").read_text(encoding="utf-8"))


def call(method, params=None):
    return adapter.handle(method, params or {})


def run(action_id, params):
    return call("adapter.execute", {"call": {"action_id": action_id, "params": params, "request_id": "p"}})


def observe():
    return call("adapter.observe", {"level": "full"})


def digest() -> str:
    items = sorted(
        (e["ref"], e["kind"], e.get("parent"), json.dumps(e["props"], sort_keys=True)) for e in observe()["entities"]
    )
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()[:12]


# ------------------------------------------------------------------------------------------ BLD-P3
def probe_p3() -> None:
    target = "blender://object/Candle"
    added = skipped = 0
    for mod_type in modifier_types():
        before = digest()
        try:
            result = run("add_modifier", {"target": target, "type": mod_type, "name": "Probe"})
        except WyspError as exc:
            skipped += 1
            print(f"PROP p3 skip {mod_type} code={exc.code}")
            continue
        mods = [e for e in observe()["entities"] if e["kind"] == "modifier" and e["label"].startswith("Probe")]
        try:
            assert len(mods) == 1, f"{len(mods)} modifier entities"
            entity = mods[0]
            jsonschema.validate(entity, ENTITY_SCHEMA)
            json.loads(json.dumps(entity, allow_nan=False))
            assert entity["props"]["type"] == mod_type
            assert len(entity["props"]) <= 34, len(entity["props"])
            print(f"PROP p3 ok {mod_type} props={len(entity['props'])}")
            added += 1
        except Exception as exc:  # noqa: BLE001
            print(f"PROP p3 BAD {mod_type}: {type(exc).__name__}: {str(exc)[:200]}")
        call("adapter.undo", {"token": result["undo_token"]})
        if digest() != before:
            print(f"PROP p3 BAD {mod_type}: undo did not restore the digest")
    print(f"PROP p3 summary added={added} skipped={skipped}")


# ------------------------------------------------------------------------------------------ BLD-P2
OBJECTS = ["Pumpkin", "Candle", "Stem"]
ADD_TYPES = ["BEVEL", "SUBSURF", "SOLIDIFY", "MIRROR", "ARRAY", "WIREFRAME", "TRIANGULATE"]
SETTERS = {"BEVEL": ("segments", lambda n: 1 + n % 8), "SUBSURF": ("levels", lambda n: n % 3),
           "SOLIDIFY": ("thickness", lambda n: round((n % 20) / 20, 2)), "ARRAY": ("count", lambda n: 1 + n % 5)}  # fmt: skip
ops = st.lists(
    st.tuples(st.sampled_from(["add", "set", "move", "toggle", "remove"]), st.integers(0, 50), st.integers(0, 50)),
    max_size=14,
)
P2_STATE = {"examples": 0, "bad": 0}


def current_modifiers() -> list[dict]:
    return [e for e in observe()["entities"] if e["kind"] == "modifier"]


@settings(max_examples=25, deadline=None, database=None, suppress_health_check=list(HealthCheck))
@given(plan=ops)
def p2_property(plan) -> None:
    start = digest()
    tokens: list[str] = []
    for kind, a, b in plan:
        mods = current_modifiers()
        try:
            if kind == "add" or not mods:
                obj = OBJECTS[a % len(OBJECTS)]
                r = run("add_modifier", {"target": f"blender://object/{obj}", "type": ADD_TYPES[b % len(ADD_TYPES)]})
            else:
                m = mods[a % len(mods)]
                ref, props = m["ref"], m["props"]
                if kind == "set":
                    setter = SETTERS.get(props["type"])
                    if setter is None:
                        continue
                    r = run("set_modifier_property", {"target": ref, "property": setter[0], "value": setter[1](b)})
                elif kind == "move":
                    siblings = [x for x in mods if x["parent"] == m["parent"]]
                    r = run("move_modifier", {"target": ref, "index": b % len(siblings)})
                elif kind == "toggle" and not adapter.registry.has("toggle_modifier_visibility"):
                    continue  # missing from the catalog for now (requirement 4.1)
                elif kind == "toggle":
                    r = run("toggle_modifier_visibility", {"target": ref, "viewport": not props["show_viewport"]})
                else:
                    r = run("remove_modifier", {"target": ref})
        except WyspError:
            continue  # a refused call must leave the state unchanged; undoing the rest still has to restore it
        if r.get("undo_token"):
            tokens.append(r["undo_token"])
    for token in reversed(tokens):
        call("adapter.undo", {"token": token})
    P2_STATE["examples"] += 1
    if digest() != start:
        P2_STATE["bad"] += 1
        raise AssertionError(f"undo in reverse order did not restore the digest for plan {plan}")


def probe_p2() -> None:
    try:
        p2_property()
        print(f"PROP p2 ok examples={P2_STATE['examples']}")
    except BaseException as exc:  # noqa: BLE001  (Hypothesis may raise an ExceptionGroup)
        print(f"PROP p2 BAD {type(exc).__name__}: {str(exc)[:600]}")


probe_p3()
probe_p2()
print("PROP-DONE")
