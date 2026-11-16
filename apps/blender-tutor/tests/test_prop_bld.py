"""Property-based tests of the Blender adapter that run against the fake `bpy` (fast, no Blender).

BLD-P1 main-thread confinement, BLD-P3 (projection of arbitrary RNA properties), BLD-P4 origin tagging,
BLD-P5 debounce. The real-Blender variants of BLD-P2 and BLD-P3 are in `test_prop_bld_live.py`.
"""

# ruff: noqa: F811  (the adapter_pkg fixture is imported from test_fake_bpy, then used as a test argument)
from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from test_fake_bpy import (  # noqa: F401  (adapter_pkg is a fixture)
    FakeBpy,
    FakeModifier,
    FakeObject,
    FakeScene,
    adapter_pkg,
)
from wysp_adapter_sdk import ActionOutcome

FAST = settings(
    max_examples=60,
    deadline=None,
    database=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
ENTITY_SCHEMA = json.loads((Path(__file__).resolve().parents[3] / "schemas" / "entity.schema.json").read_text("utf-8"))


# ------------------------------------------------------------------------------------ helpers
class RecordingClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.connected = True

    def notify(self, method: str, params: dict | None = None) -> bool:
        self.sent.append((method, params or {}))
        return True

    def of(self, method: str) -> list[dict]:
        return [p for m, p in self.sent if m == method]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


def poke_spec(action_id: str) -> dict:
    return {
        "id": action_id,
        "title": {"en": action_id},
        "description": "test action",
        "params_schema": {"type": "object", "properties": {"i": {"type": "integer"}}, "additionalProperties": True},
        "risk": "reversible",
        "reversible": True,
        "preconditions": [],
        "postconditions": [],
    }


class World:
    """A fake scene plus a BlenderAdapter whose only action moves an object or adds a modifier."""

    def __init__(self, pkg, n: int = 3) -> None:
        self.pkg = pkg
        self.objects = [FakeObject(f"O{i}") for i in range(n)]
        pkg.bpy.set_scene(FakeScene(self.objects))
        self.adapter = pkg.runtime.BlenderAdapter()
        self.client = RecordingClient()
        self.adapter.client = self.client
        self.counter = 0
        self.mod_counter = 0
        self.pending: dict[str, list[str]] = {}  # ref -> runs of who changed it, oldest first, until reported
        self.adapter.registry.register(poke_spec("poke"), self._poke)
        self.adapter.registry.register(poke_spec("add_mod"), self._add_mod)
        self.adapter.watcher.check_now()  # baseline

    def _mark(self, refs: list[str], who: str) -> None:
        for r in refs:
            runs = self.pending.setdefault(r, [])
            if not runs or runs[-1] != who:
                runs.append(who)

    def _obj_ref(self, i: int) -> str:
        return f"blender://object/{self.objects[i % len(self.objects)].name}"

    def _move(self, i: int, who: str) -> list[str]:
        obj = self.objects[i % len(self.objects)]
        self.counter += 1
        obj.location = (float(self.counter), 0.0, 0.0)
        ref = self._obj_ref(i)
        self._mark([ref], who)
        return [ref]

    def _add(self, i: int, who: str) -> list[str]:
        obj = self.objects[i % len(self.objects)]
        self.mod_counter += 1
        mod = FakeModifier(f"M{self.mod_counter}")
        obj.modifiers.append(mod)
        refs = [self._obj_ref(i), f"{self._obj_ref(i)}/modifier/{mod.name}"]
        self._mark(refs, who)
        return refs

    def _poke(self, params: dict, dry: bool) -> ActionOutcome:
        return ActionOutcome(changed=self._move(params.get("i", 0), "wysp"))

    def _add_mod(self, params: dict, dry: bool) -> ActionOutcome:
        return ActionOutcome(changed=self._add(params.get("i", 0), "wysp"))

    def wysp(self, action_id: str, i: int) -> None:
        self.adapter.handle("adapter.execute", {"call": {"action_id": action_id, "params": {"i": i}}})

    def user_move(self, i: int) -> None:
        self._move(i, "user")

    def user_add(self, i: int) -> None:
        self._add(i, "user")


# ======================================================================== BLD-P1
class GuardedBpy(FakeBpy):
    """A fake bpy that records every access to scene data from a thread other than the main one."""

    GUARDED = frozenset({"context", "data", "ops"})

    def __getattribute__(self, name: str):
        if name in GuardedBpy.GUARDED and threading.current_thread() is not threading.main_thread():
            violations = object.__getattribute__(self, "__dict__").setdefault("violations", [])
            violations.append((name, threading.current_thread().name))
        return super().__getattribute__(name)


REQUESTS = ["adapter.observe", "adapter.get_context", "adapter.get_actions", "poke", "add_mod", "undo"]


@FAST
@given(
    requests=st.lists(st.sampled_from(REQUESTS), min_size=1, max_size=25),
    senders=st.integers(min_value=1, max_value=3),
)
def test_prop_bld_p1_bpy_is_only_touched_on_the_main_thread(adapter_pkg, requests, senders):
    """BLD-P1: whatever the network threads submit, scene data is only read or written on the main thread."""
    adapter_pkg.bpy.__class__ = GuardedBpy
    world = World(adapter_pkg)
    adapter = world.adapter
    answers: list[tuple[str, object, BaseException | None, str]] = []
    tokens: list[str] = []
    lock = threading.Lock()

    def submit(method_or_action: str) -> None:  # runs on a "network" thread: it only enqueues
        if method_or_action in ("poke", "add_mod"):
            method, params = "adapter.execute", {"call": {"action_id": method_or_action, "params": {"i": 1}}}
        elif method_or_action == "undo":
            with lock:
                token = tokens.pop() if tokens else "u-none"
            method, params = "adapter.undo", {"token": token}
        else:
            method, params = method_or_action, {}

        def done(result, exc) -> None:  # runs inside pump(): on the main thread
            with lock:
                answers.append((method, result, exc, threading.current_thread().name))
                if isinstance(result, dict) and result.get("undo_token"):
                    tokens.append(result["undo_token"])

        adapter.dispatcher.submit(lambda: adapter.handle(method, params), done)

    chunks = [requests[i::senders] for i in range(senders)]
    threads = [
        threading.Thread(target=lambda c=c: [submit(r) for r in c], name=f"net-{i}") for i, c in enumerate(chunks)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    while adapter.dispatcher.pending():
        adapter.tick()

    assert len(answers) == len(requests), "every request is answered"
    assert {a[3] for a in answers} == {threading.main_thread().name}, "answers are produced by the pump"
    assert not getattr(adapter_pkg.bpy, "violations", []), adapter_pkg.bpy.violations


def test_prop_bld_p1_the_guard_detects_a_foreign_thread(adapter_pkg):
    """Control for BLD-P1: the recording fake does report an access from another thread."""
    adapter_pkg.bpy.__class__ = GuardedBpy
    t = threading.Thread(target=lambda: adapter_pkg.bpy.context, name="net-x")
    t.start()
    t.join()
    assert adapter_pkg.bpy.violations == [("context", "net-x")]


# ======================================================================== BLD-P3
rna_property = st.fixed_dictionaries(
    {
        "identifier": st.text("abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=12).map(lambda s: "p_" + s),
        "type": st.sampled_from(["BOOLEAN", "INT", "FLOAT", "ENUM", "STRING", "POINTER", "COLLECTION"]),
        "array": st.sampled_from([0, 0, 0, 2, 3, 4, 16]),
        "flag": st.booleans(),
        "float": st.floats(allow_nan=False, allow_infinity=False, width=32),
        "int": st.integers(-(2**31), 2**31 - 1),
        "text": st.text(max_size=20),
        "flags": st.sets(st.sampled_from(["A", "B", "C"])),
    }
)


class _RnaMod:
    """A fake modifier built from random RNA property definitions."""

    def __init__(self, defs: list[dict]) -> None:
        self.name = "Mod"
        self.type = "BEVEL"
        self.show_viewport = self.show_render = True
        props = []
        for d in {d["identifier"]: d for d in defs}.values():
            n = d["array"] if d["type"] in ("BOOLEAN", "INT", "FLOAT") else 0
            props.append(SimpleNamespace(identifier=d["identifier"], type=d["type"], array_length=n,
                                         is_enum_flag=d["flag"] and d["type"] == "ENUM", is_readonly=False))  # fmt: skip
            value = {
                "BOOLEAN": d["flag"], "INT": d["int"], "FLOAT": d["float"], "STRING": d["text"],
                "ENUM": d["flags"] if d["flag"] else "A", "POINTER": None, "COLLECTION": [],
            }[d["type"]]  # fmt: skip
            if n:
                value = [value] * n
            setattr(self, d["identifier"], value)
        self.bl_rna = SimpleNamespace(properties=props)


@FAST
@given(defs=st.lists(rna_property, max_size=60))
def test_prop_bld_p3_any_rna_property_set_projects_to_valid_json(adapter_pkg, defs):
    """BLD-P3: every property layout yields a schema-valid entity with JSON-serialisable props (at most 30)."""
    import jsonschema

    obj = FakeObject("Obj", modifiers=[_RnaMod(defs)])
    adapter_pkg.bpy.set_scene(FakeScene([obj]))
    entities, _links, _truncated = adapter_pkg.observe.build_entities(adapter_pkg.bpy.context.scene)
    mods = [e for e in entities if e["kind"] == "modifier"]
    assert len(mods) == 1
    for e in entities:
        jsonschema.validate(e, ENTITY_SCHEMA)
        json.loads(json.dumps(e, allow_nan=False))  # raises on NaN, sets or other non-JSON values
    props = mods[0]["props"]
    # type, index, show_viewport and show_render are added after the (at most 30) RNA properties
    assert len(props) <= adapter_pkg.rna_props.MAX_PROPS + 4
    assert props["type"] == "BEVEL" and props["index"] == 0


# ======================================================================== BLD-P4
steps = st.lists(
    st.tuples(
        st.sampled_from(["wysp_move", "wysp_add", "user_move", "user_add", "tick"]),
        st.integers(min_value=0, max_value=2),
    ),
    min_size=1,
    max_size=30,
)


@FAST
@given(plan=steps)
def test_prop_bld_p4_every_event_has_a_single_cause(adapter_pkg, monkeypatch, plan):
    """BLD-P4: events from Wysp actions are tagged wysp, direct changes user, and none mixes both."""
    clock = Clock()
    monkeypatch.setattr(adapter_pkg.events, "time", SimpleNamespace(monotonic=clock.monotonic))
    world = World(adapter_pkg)
    sent = world.client.sent
    seen = 0

    def check_new_events() -> None:
        nonlocal seen
        to_pop: list[str] = []  # refs of the flush being read: its user_action events follow its state_changed
        for method, params in sent[seen:]:
            if method == "event.state_changed":
                for ref in to_pop:
                    world.pending[ref].pop(0)  # the previous flush is complete: next run is attributed next
                to_pop = list(params["changed"])
                refs = params["changed"]
            elif method == "event.user_action":
                refs = [params["target"]]
            else:
                continue
            assert params["origin"] in ("user", "wysp"), "with exact attribution nothing is 'unknown'"
            for ref in refs:
                assert world.pending.get(ref, [None])[0] == params["origin"], (method, params, world.pending)
        for ref in to_pop:
            world.pending[ref].pop(0)
        seen = len(sent)

    for kind, i in plan:
        if kind == "wysp_move":
            world.wysp("poke", i)
        elif kind == "wysp_add":
            world.wysp("add_mod", i)
        elif kind == "user_move":
            world.user_move(i)
        elif kind == "user_add":
            world.user_add(i)
        else:
            clock.now += 0.3
            world.adapter.watcher.poll()
        check_new_events()
    clock.now += 1.1  # past the idle interval
    world.adapter.watcher.poll()  # flush the tail
    check_new_events()
    # nothing is left unreported after the tail flush
    before = len(sent)
    world.adapter.watcher.check_now()
    assert len(sent) == before


def test_prop_bld_p4_a_user_change_right_after_a_wysp_action_is_still_the_users(adapter_pkg):
    """BLD-P4: the 0.6 s window after an action must not claim a user change that follows it."""
    world = World(adapter_pkg)
    world.wysp("poke", 0)
    world.user_move(1)  # well inside the 0.6 s window
    world.adapter.watcher.check_now()
    origins = {tuple(p["changed"]): p["origin"] for p in world.client.of("event.state_changed")}
    assert origins[("blender://object/O0",)] == "wysp"
    assert origins[("blender://object/O1",)] == "user"


def test_prop_bld_p4_a_user_change_before_an_action_is_not_credited_to_wysp(adapter_pkg):
    """BLD-P4: a user change not yet reported when an action runs is flushed first, as the user's."""
    world = World(adapter_pkg)
    world.user_move(1)
    world.wysp("poke", 0)
    origins = [(p["changed"], p["origin"]) for p in world.client.of("event.state_changed")]
    assert origins == [(["blender://object/O1"], "user"), (["blender://object/O0"], "wysp")]


# ======================================================================== BLD-P5
@FAST
@given(
    gaps_ms=st.lists(st.integers(min_value=0, max_value=400), min_size=1, max_size=40),
)
def test_prop_bld_p5_bursts_send_at_most_one_state_changed_per_250_ms(adapter_pkg, monkeypatch, gaps_ms):
    """BLD-P5: state_changed events are at least 250 ms apart and the last state is always reported."""
    clock = Clock()
    monkeypatch.setattr(adapter_pkg.events, "time", SimpleNamespace(monotonic=clock.monotonic))
    world = World(adapter_pkg, n=1)
    watcher = world.adapter.watcher
    stamps: list[float] = []
    real_notify = world.client.notify

    def notify(method, params=None):
        if method == "event.state_changed":
            stamps.append(clock.now)
        return real_notify(method, params)

    world.client.notify = notify
    reported: set[str] = set()

    def run_for(seconds: float) -> None:
        end = clock.now + seconds
        while clock.now < end:
            clock.now += 0.01
            watcher.poll()

    for gap in gaps_ms:
        run_for(gap / 1000)
        world.user_move(0)  # a depsgraph update: the data changed ...
        watcher.dirty = True  # ... and the handler marked the watcher dirty
        watcher.poll()
    run_for(1.5)  # quiet time: the idle poll interval is 1 s

    for p in world.client.of("event.state_changed"):
        reported.update(p["changed"])
    assert all(b - a >= 0.249 for a, b in zip(stamps, stamps[1:], strict=False)), stamps
    assert "blender://object/O0" in reported
    before = len(world.client.sent)
    watcher.check_now()
    assert len(world.client.sent) == before, "the last state had already been reported"


@pytest.mark.parametrize("n_updates", [1, 50, 500])
def test_prop_bld_p5_a_same_instant_burst_is_one_event(adapter_pkg, monkeypatch, n_updates):
    """BLD-P5: many updates inside one poll interval become one event."""
    clock = Clock()
    monkeypatch.setattr(adapter_pkg.events, "time", SimpleNamespace(monotonic=clock.monotonic))
    world = World(adapter_pkg, n=1)
    world.adapter.watcher.poll()
    clock.now += 0.3
    for _ in range(n_updates):
        world.user_move(0)
        world.adapter.watcher.dirty = True
        world.adapter.watcher.poll()
        clock.now += 0.001
    clock.now += 0.3
    world.adapter.watcher.poll()
    assert len(world.client.of("event.state_changed")) <= 2
