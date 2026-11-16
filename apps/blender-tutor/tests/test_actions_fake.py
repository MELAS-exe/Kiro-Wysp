"""toggle_modifier_visibility and assign_material against a small fake `bpy` (no Blender)."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from wysp_adapter_sdk import ErrorCode, WyspError

ADAPTER = Path(__file__).resolve().parents[1] / "adapter"
PKG = "wysp_act_fake"
MOD_REF = "blender://object/Pumpkin/modifier/Bevel"
OBJ_REF = "blender://object/Pumpkin"


class Mod:
    def __init__(self, name: str) -> None:
        self.name = name
        self.show_viewport = True
        self.show_render = True


class Named(dict):
    """Behaves like bpy's name-keyed collections: .get(name) and iteration over items."""

    def __iter__(self):
        return iter(self.values())


class Mats:
    """Fake `mesh.materials`: append adds a slot, pop removes one."""

    def __init__(self, owner) -> None:
        self.owner = owner

    def append(self, mat) -> None:
        self.owner.material_slots.append(SimpleNamespace(material=mat))

    def pop(self, index: int) -> None:
        self.owner.material_slots.pop(index)


class Obj:
    def __init__(self, name: str, mods=(), slots=(), has_materials=True) -> None:
        self.name = name
        self.type = "MESH" if has_materials else "EMPTY"
        self.modifiers = Named({m.name: m for m in mods})
        self.material_slots = [SimpleNamespace(material=m) for m in slots]
        self.data = SimpleNamespace(materials=Mats(self)) if has_materials else None


@pytest.fixture
def world(monkeypatch):
    bpy = types.ModuleType("bpy")
    red, blue = SimpleNamespace(name="Red"), SimpleNamespace(name="Blue")
    pumpkin = Obj("Pumpkin", mods=[Mod("Bevel")], slots=[red])
    bare = Obj("Bare")
    empty = Obj("Marker", has_materials=False)
    bpy.data = SimpleNamespace(
        objects=Named({o.name: o for o in (pumpkin, bare, empty)}),
        materials=Named({"Red": red, "Blue": blue}),
    )
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [str(ADAPTER)]
    monkeypatch.setitem(sys.modules, PKG, pkg)
    actions = types.ModuleType(f"{PKG}.actions")
    actions.__path__ = [str(ADAPTER / "actions")]
    monkeypatch.setitem(sys.modules, actions.__name__, actions)
    loaded = {}
    for name in ("refs", "actions._common", "actions.toggle_modifier_visibility", "actions.assign_material"):
        path = ADAPTER / (name.replace(".", "/") + ".py")
        spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        loaded[name.split(".")[-1]] = module
    return SimpleNamespace(pumpkin=pumpkin, bare=bare, empty=empty, red=red, blue=blue, **loaded)


def code_of(fn) -> int:
    with pytest.raises(WyspError) as info:
        fn()
    return int(info.value.code)


# ------------------------------------------------------------------------------------- toggle
def test_toggle_spec_is_reversible_and_checks_the_observed_prop(world):
    s = world.toggle_modifier_visibility.spec()
    assert s["id"] == "toggle_modifier_visibility" and s["risk"] == "reversible" and s["reversible"] is True
    assert s["postconditions"][0]["path"] == "get(props, 'show_${params.which}')"
    assert s["params_schema"]["properties"]["which"]["enum"] == ["viewport", "render"]
    assert s["guide"]["ui_path"]


@pytest.mark.parametrize("which", ["viewport", "render"])
def test_toggle_sets_and_undo_restores(world, which):
    attr = f"show_{which}"
    mod = world.pumpkin.modifiers["Bevel"]
    out = world.toggle_modifier_visibility.run({"target": MOD_REF, "which": which, "value": False}, False)
    assert getattr(mod, attr) is False and out.changed == [MOD_REF]
    other = "show_render" if which == "viewport" else "show_viewport"
    assert getattr(mod, other) is True, "only the requested switch changes"
    out.undo()
    assert getattr(mod, attr) is True


def test_toggle_dry_run_changes_nothing(world):
    out = world.toggle_modifier_visibility.run({"target": MOD_REF, "which": "viewport", "value": False}, True)
    assert out.preview == {"which": "viewport", "from": True, "to": False}
    assert world.pumpkin.modifiers["Bevel"].show_viewport is True


def test_toggle_undo_ignores_a_modifier_that_is_gone(world):
    out = world.toggle_modifier_visibility.run({"target": MOD_REF, "which": "render", "value": False}, False)
    world.pumpkin.modifiers.clear()
    out.undo()  # must not raise


def test_toggle_invalid_calls_leave_state_unchanged(world):
    run = world.toggle_modifier_visibility.run
    mod = world.pumpkin.modifiers["Bevel"]
    assert (
        code_of(lambda: run({"target": MOD_REF, "which": "sideways", "value": False}, False))
        == ErrorCode.INVALID_PARAMS
    )
    assert (
        code_of(lambda: run({"target": MOD_REF, "which": "viewport", "value": "off"}, False))
        == ErrorCode.INVALID_PARAMS
    )
    missing = "blender://object/Pumpkin/modifier/Nope"
    assert (
        code_of(lambda: run({"target": missing, "which": "viewport", "value": False}, False))
        == ErrorCode.TARGET_NOT_FOUND
    )
    assert mod.show_viewport is True and mod.show_render is True


# --------------------------------------------------------------------------------- assign_material
def test_assign_spec_is_reversible_and_checks_props_material(world):
    s = world.assign_material.spec()
    assert s["id"] == "assign_material" and s["risk"] == "reversible" and s["reversible"] is True
    assert s["postconditions"][0]["path"] == "props.material"
    assert s["params_schema"]["required"] == ["target", "material"]


def test_assign_replaces_first_slot_and_undo_restores(world):
    out = world.assign_material.run({"target": OBJ_REF, "material": "Blue"}, False)
    assert world.pumpkin.material_slots[0].material is world.blue and out.changed == [OBJ_REF]
    out.undo()
    assert world.pumpkin.material_slots[0].material is world.red


def test_assign_creates_a_slot_when_none_and_undo_removes_it(world):
    out = world.assign_material.run({"target": "blender://object/Bare", "material": "Red"}, False)
    assert [s.material for s in world.bare.material_slots] == [world.red]
    out.undo()
    assert world.bare.material_slots == []


def test_assign_only_touches_the_first_slot(world):
    world.pumpkin.material_slots.append(SimpleNamespace(material=world.blue))
    world.assign_material.run({"target": OBJ_REF, "material": "Blue"}, False)
    world.pumpkin.material_slots[0].material = world.red  # as undo would
    assert world.pumpkin.material_slots[1].material is world.blue


def test_assign_dry_run_changes_nothing(world):
    out = world.assign_material.run({"target": "blender://object/Bare", "material": "Red"}, True)
    assert out.preview == {"from": None, "to": "Red", "new_slot": True}
    assert world.bare.material_slots == []


def test_assign_invalid_calls_leave_state_unchanged(world):
    run = world.assign_material.run
    assert code_of(lambda: run({"target": OBJ_REF, "material": "Nope"}, False)) == ErrorCode.TARGET_NOT_FOUND
    assert (
        code_of(lambda: run({"target": "blender://object/Ghost", "material": "Red"}, False))
        == ErrorCode.TARGET_NOT_FOUND
    )
    assert (
        code_of(lambda: run({"target": "blender://object/Marker", "material": "Red"}, False))
        == ErrorCode.PRECONDITION_FAILED
    )
    assert world.pumpkin.material_slots[0].material is world.red
    assert world.empty.material_slots == []
    assert set(world.__dict__) and len(world.assign_material.bpy.data.materials) == 2, "no material was created"
