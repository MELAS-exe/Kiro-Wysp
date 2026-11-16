"""Adapter logic that needs `bpy` objects, tested against a small fake `bpy` (no Blender, no GUI).

The fake only models what observe.py, highlight.py and runtime.py read. Real-Blender behaviour is covered by
the `live` tests (headless Blender) and the manual checklist in the spec.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ADAPTER = Path(__file__).resolve().parents[1] / "adapter"
PKG = "wysp_bl_fake"


# ------------------------------------------------------------------------------------------ fake bpy
class FakeObject:
    def __init__(self, name: str, type_: str = "MESH", modifiers=None, parent=None, material=None) -> None:
        self.name = name
        self.type = type_
        self.modifiers = modifiers or []
        self.parent = parent
        self.location = (0.0, 0.0, 0.0)
        self.rotation_euler = (0.0, 0.0, 0.0)
        self.scale = (1.0, 1.0, 1.0)
        self.dimensions = (2.0, 2.0, 2.0)
        self.hide_viewport = False
        self.data = SimpleNamespace(vertices=[0] * 8)
        self.material_slots = [SimpleNamespace(material=material)] if material else []
        self.selected = False

    def select_get(self) -> bool:
        return self.selected


class FakeModifier:
    type = "BEVEL"
    show_viewport = True
    show_render = True

    def __init__(self, name: str) -> None:
        self.name = name
        self.bl_rna = SimpleNamespace(properties=[])


class FakeCollection:
    def __init__(self, name: str, objects=(), children=()) -> None:
        self.name = name
        self.objects = list(objects)
        self.children = list(children)


class FakeScene:
    def __init__(self, objects: list[FakeObject], collections: list[FakeCollection] | None = None) -> None:
        self.name = "Scene"
        self.objects = objects
        self.collection = FakeCollection("Master", children=collections or [])
        self.frame_current, self.frame_start, self.frame_end = 1, 1, 250
        self.render = SimpleNamespace(engine="BLENDER_EEVEE", fps=24)
        self.unit_settings = SimpleNamespace(system="METRIC")
        self.camera = None


class FakeTimers:
    def __init__(self) -> None:
        self.registered: list = []

    def register(self, fn, first_interval=0.0, persistent=False) -> None:
        self.registered.append(fn)

    def is_registered(self, fn) -> bool:
        return fn in self.registered


class FakeBpy(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("bpy")
        self.timers = FakeTimers()
        self.app = types.ModuleType("bpy.app")
        self.app.version_string = "5.2.0"
        self.app.background = False
        self.app.timers = self.timers
        self.app.handlers = types.ModuleType("bpy.app.handlers")
        self.app.handlers.persistent = lambda fn: fn
        self.removed_handles: list = []
        self.added_handles = 0

        class Space3D:
            @staticmethod
            def draw_handler_add(fn, args, region, kind):
                outer.added_handles += 1
                return object()

            @staticmethod
            def draw_handler_remove(handle, region):
                outer.removed_handles.append(handle)

        outer = self
        self.types = SimpleNamespace(Object=FakeObject, SpaceView3D=Space3D)
        self.data = SimpleNamespace(objects={}, collections=[], materials=[])
        self.context = SimpleNamespace(
            scene=None,
            mode="OBJECT",
            view_layer=None,
            window_manager=SimpleNamespace(windows=[]),
            preferences=SimpleNamespace(system=SimpleNamespace(ui_scale=1.5)),
        )

    def set_scene(self, scene: FakeScene) -> None:
        self.context.scene = scene
        self.data.objects = {o.name: o for o in scene.objects}
        self.context.view_layer = SimpleNamespace(objects=_Objects(scene.objects))


class _Objects(list):
    active = None


@pytest.fixture
def adapter_pkg(monkeypatch):
    """The add-on's modules, loaded as a package against the fake bpy (no __init__.py, no register())."""
    fake = FakeBpy()
    monkeypatch.setitem(sys.modules, "bpy", fake)
    monkeypatch.setitem(sys.modules, "bpy.app", fake.app)
    monkeypatch.setitem(sys.modules, "bpy.app.handlers", fake.app.handlers)
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [str(ADAPTER)]
    monkeypatch.setitem(sys.modules, PKG, pkg)
    actions = types.ModuleType(f"{PKG}.actions")
    actions.register_all = lambda registry: None
    actions.__path__ = []
    tab = types.ModuleType(f"{PKG}.actions.show_properties_tab")
    tab.switch_tab = lambda name: True
    monkeypatch.setitem(sys.modules, tab.__name__, tab)
    monkeypatch.setitem(sys.modules, f"{PKG}.actions", actions)
    loaded = {}
    for name in ("refs", "rna_props", "observe", "telemetry", "ui_targets", "label_match", "nav_detect",
                 "highlight", "events", "runtime"):  # fmt: skip
        spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", ADAPTER / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        loaded[name] = module
    return SimpleNamespace(bpy=fake, **loaded)


def many_objects(n: int, with_modifiers: bool = True) -> list[FakeObject]:
    mats = [SimpleNamespace(name=f"Mat{i}", users=1) for i in range(5)]
    out = []
    for i in range(n):
        mods = [FakeModifier("Bevel"), FakeModifier("Solidify")] if with_modifiers and i % 3 == 0 else []
        out.append(FakeObject(f"Obj{i:04d}", modifiers=mods, material=mats[i % 5]))
    out[1].parent = out[0]
    out[-1].parent = out[0]  # a link whose child may be cut off by the cap
    return out


# ------------------------------------------------------------------------------- 500-entity cap
@pytest.mark.parametrize("n", [100, 600, 2000])
def test_entity_cap_keeps_graph_consistent(adapter_pkg, n):
    scene = FakeScene(many_objects(n), [FakeCollection("Col", objects=[])])
    scene.collection.children[0].objects = scene.objects[:10]
    adapter_pkg.bpy.set_scene(scene)
    obs = adapter_pkg.observe.build_observation(1, {"level": "full"})
    entities, refs = obs["entities"], {e["ref"] for e in obs["entities"]}
    assert len(entities) <= adapter_pkg.observe.MAX_ENTITIES
    assert len(refs) == len(entities), "refs are unique"
    assert obs["truncated"] is (n >= 600)
    assert obs["counts"]["object"] == n, "counts report the real total"
    for e in entities:
        assert e.get("parent") is None or e["parent"] in refs, e
    for link in obs["links"]:
        assert link["from"] in refs and link["to"] in refs, link
    json.dumps(obs)  # JSON-serialisable


def test_small_scene_is_not_truncated(adapter_pkg):
    adapter_pkg.bpy.set_scene(FakeScene(many_objects(5)))
    obs = adapter_pkg.observe.build_observation(1)
    assert obs["truncated"] is False
    assert obs["counts"]["object"] == 5


# ----------------------------------------------------------------------------- context and facts
def test_context_includes_scene_facts_and_fits_8kb(adapter_pkg):
    objects = many_objects(3000)
    scene = FakeScene(objects)
    adapter_pkg.bpy.set_scene(scene)
    for o in objects:
        o.selected = True  # worst case: everything selected
    adapter_pkg.bpy.context.view_layer.active = objects[0]
    ctx = adapter_pkg.observe.build_context(1)
    facts = ctx["facts"]
    assert facts["object_types"] == {"MESH": 3000}
    assert facts["render_engine"] == "BLENDER_EEVEE" and facts["frame_range"] == [1, 250]
    assert facts["camera"] is None and facts["fps"] == 24 and facts["unit_system"] == "METRIC"
    assert len(facts["selected"]) <= 10 and len(ctx["focus"]) <= adapter_pkg.observe.MAX_CONTEXT_FOCUS
    assert len(json.dumps(ctx).encode("utf-8")) <= 8 * 1024


def test_manifest_declares_contract_1_1(adapter_pkg):
    m = adapter_pkg.observe.manifest()
    assert m["contract_version"] == "1.1.0" and "highlight" in m["capabilities"]


# ---------------------------------------------------------------------------------- highlights
class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def hl(adapter_pkg, monkeypatch):
    clock = Clock()
    mod = adapter_pkg.highlight
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=clock.monotonic))
    objects = [FakeObject("Pumpkin"), FakeObject("Candle"), FakeObject("Lid")]
    adapter_pkg.bpy.set_scene(FakeScene(objects))
    mod.clear_highlight()
    yield SimpleNamespace(mod=mod, clock=clock, pkg=adapter_pkg)
    mod.clear_highlight()


PUMPKIN = "blender://object/Pumpkin"
CANDLE = "blender://object/Candle"


def test_persistent_highlight_survives_past_a_timeout(hl):
    hl.mod.highlight(PUMPKIN, "pulse", 0)
    hl.clock.now += 3600
    assert hl.mod._tick() == 0.04, "still drawn after an hour"
    assert hl.mod.is_active()
    hl.mod.highlight(CANDLE, "pulse", 2000)  # a timed one for contrast
    hl.clock.now += 2.5
    assert hl.mod._tick() is None and not hl.mod.is_active()


def test_clear_returns_cleared_true_then_false(hl):
    assert hl.mod.clear_active() == {"cleared": False}  # nothing shown: not an error
    hl.mod.highlight(PUMPKIN, "pulse", 0)
    assert hl.mod.clear_active() == {"cleared": True}
    assert hl.mod.clear_active() == {"cleared": False}
    assert hl.pkg.bpy.removed_handles, "the draw handler is removed"
    assert hl.mod._tick() is None, "the timer stops once cleared"


def test_new_highlight_replaces_the_previous_one(hl):
    hl.mod.highlight(PUMPKIN, "pulse", 0)
    hl.mod.highlight(CANDLE, "pulse", 0)
    assert hl.mod._state["object"] == "Candle" and hl.mod._state["ref"] == CANDLE
    assert hl.pkg.bpy.timers.registered.count(hl.mod._tick) == 1, "one timer only"


def test_failed_highlight_keeps_the_previous_one(hl):
    from wysp_adapter_sdk import WyspError

    hl.mod.highlight(PUMPKIN, "pulse", 0)
    with pytest.raises(WyspError):
        hl.mod.highlight("blender://object/Nope", "pulse", 0)
    assert hl.mod._state["ref"] == PUMPKIN and hl.mod.is_active()


def test_dismissed_when_the_user_selects_the_highlighted_object(hl):
    hl.mod.highlight(PUMPKIN, "pulse", 0)
    hl.clock.now += 2.0
    assert hl.mod.dismissed_by_selection([CANDLE], [PUMPKIN, CANDLE], "user") == PUMPKIN
    assert not hl.mod.is_active()


def test_not_dismissed_by_wysp_origin_selection(hl):
    hl.mod.highlight(PUMPKIN, "pulse", 0)
    hl.clock.now += 2.0
    assert hl.mod.dismissed_by_selection([], [PUMPKIN], "wysp") is None
    assert hl.mod.is_active()


def test_not_dismissed_inside_the_grace_period(hl):
    hl.mod.highlight(PUMPKIN, "pulse", 0)
    hl.clock.now += 1.0
    assert hl.mod.dismissed_by_selection([], [PUMPKIN], "user") is None
    hl.clock.now += 0.6  # 1.6 s after showing
    assert hl.mod.dismissed_by_selection([], [PUMPKIN], "user") == PUMPKIN


def test_not_dismissed_by_other_objects_or_unchanged_focus(hl):
    hl.mod.highlight(PUMPKIN, "pulse", 0)
    hl.clock.now += 2.0
    assert hl.mod.dismissed_by_selection([], [CANDLE], "user") is None
    assert hl.mod.dismissed_by_selection([PUMPKIN], [PUMPKIN], "user") is None
    assert hl.mod.is_active()


def test_modifier_ref_highlight_is_dismissed_by_its_object_and_reports_the_original_ref(hl):
    ref = PUMPKIN + "/modifier/Bevel"
    hl.pkg.bpy.data.objects["Pumpkin"].modifiers.append(FakeModifier("Bevel"))
    hl.mod.highlight(ref, "pulse", 0)
    hl.clock.now += 2.0
    assert hl.mod.dismissed_by_selection([], [PUMPKIN], "user") == ref


# ---------------------------------------------------------------------------- runtime wiring
class FakeClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.connected = True

    def notify(self, method, params=None) -> bool:
        self.sent.append((method, params or {}))
        return True


def test_runtime_clear_highlight_and_dismissal_event(hl):
    adapter = hl.pkg.runtime.BlenderAdapter()
    adapter.client = FakeClient()
    assert adapter.handle("adapter.clear_highlight", {}) == {"cleared": False}
    adapter.handle("adapter.highlight", {"ref": PUMPKIN, "duration_ms": 0})
    hl.clock.now += 2.0
    adapter.on_focus_changed([], [PUMPKIN])
    assert adapter.client.sent == [("event.highlight_dismissed", {"ref": PUMPKIN, "reason": "user"})]
    assert adapter.handle("adapter.clear_highlight", {}) == {"cleared": False}  # already gone


def test_runtime_wysp_origin_selection_does_not_dismiss(hl):
    adapter = hl.pkg.runtime.BlenderAdapter()
    adapter.client = FakeClient()
    adapter.handle("adapter.highlight", {"ref": PUMPKIN, "duration_ms": 0})
    hl.clock.now += 2.0
    with adapter.origin.wysp():
        pass  # opens the "caused by Wysp" window (real clock; it is still open now)
    adapter.on_focus_changed([], [PUMPKIN])
    assert adapter.client.sent == [] and hl.mod.is_active()


def test_highlight_is_cleared_when_the_connection_drops(hl):
    adapter = hl.pkg.runtime.BlenderAdapter()
    adapter.client = FakeClient()
    adapter._clear_if_disconnected()  # connected: remembered
    adapter.handle("adapter.highlight", {"ref": PUMPKIN, "duration_ms": 0})
    adapter.client.connected = False
    adapter._clear_if_disconnected()
    assert not hl.mod.is_active()


def test_shutdown_clears_the_highlight(hl):
    adapter = hl.pkg.runtime.BlenderAdapter()
    adapter.handle("adapter.highlight", {"ref": PUMPKIN, "duration_ms": 0})
    adapter.shutdown()
    assert not hl.mod.is_active()
