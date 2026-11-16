"""Mascot icons: loading through a fake `bpy.utils.previews`, fallbacks and packaging (no Blender needed)."""

from __future__ import annotations

import fnmatch
import importlib.util
import sys
import tomllib
import types
from pathlib import Path

import pytest

ADAPTER = Path(__file__).resolve().parents[1] / "adapter"


class FakePreview:
    def __init__(self, icon_id: int) -> None:
        self.icon_id = icon_id


class FakeCollection(dict):
    def __init__(self, fail: set[str] = frozenset()) -> None:
        super().__init__()
        self.fail = fail
        self.next_id = 100
        self.loaded: list[tuple[str, str, str]] = []

    def load(self, name: str, path: str, kind: str) -> FakePreview:
        if name in self.fail:
            raise RuntimeError("cannot read image")
        self.loaded.append((name, path, kind))
        self[name] = FakePreview(self.next_id)
        self.next_id += 1
        return self[name]


@pytest.fixture
def icons(monkeypatch):
    """ui_icons loaded against a fake bpy.utils.previews; `fake.created` / `fake.removed` record the calls."""
    fake = types.SimpleNamespace(created=[], removed=[], fail=set())

    def new():
        coll = FakeCollection(fake.fail)
        fake.created.append(coll)
        return coll

    previews = types.ModuleType("bpy.utils.previews")
    previews.new = new
    previews.remove = fake.removed.append
    utils = types.ModuleType("bpy.utils")
    utils.previews = previews
    bpy = types.ModuleType("bpy")
    bpy.utils = utils
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    monkeypatch.setitem(sys.modules, "bpy.utils", utils)
    monkeypatch.setitem(sys.modules, "bpy.utils.previews", previews)
    spec = importlib.util.spec_from_file_location("wysp_test_ui_icons", ADAPTER / "ui_icons.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    fake.module = module
    yield fake
    module._collection = None


def test_icons_are_loaded_once_and_released(icons) -> None:
    m = icons.module
    assert m.icon_id("mark") == 0, "nothing before register()"
    m.register()
    m.register()  # a second call must not create a second collection
    assert len(icons.created) == 1
    coll = icons.created[0]
    assert {n for n, _p, _k in coll.loaded} == set(m.ICON_FILES)
    assert all(Path(p).is_file() for _n, p, _k in coll.loaded), "the files ship with the add-on"
    assert m.icon_id("mark") == coll["mark"].icon_id > 0
    assert m.icon_args("mark") == {"icon_value": coll["mark"].icon_id}
    m.unregister()
    m.unregister()  # safe twice
    assert icons.removed == [coll]
    assert m.icon_id("mark") == 0


def test_register_again_after_unregister(icons) -> None:
    m = icons.module
    m.register()
    m.unregister()
    m.register()
    assert len(icons.created) == 2 and m.icon_id("mark_big") > 0


def test_a_failing_picture_falls_back_to_a_builtin_icon(icons) -> None:
    icons.fail = {"mark_big"}
    m = icons.module
    m.register()
    assert m.icon_id("mark") > 0
    assert m.icon_id("mark_big") == 0
    assert m.icon_args("mark_big") == {"icon": m.ICON_FILES["mark_big"][1]}


def test_missing_previews_module_does_not_break_the_addon(icons, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "bpy.utils.previews", None)  # `import` raises ImportError
    m = icons.module
    m.register()
    assert m.icon_args("mark") == {"icon": "LIGHT_SUN"}


def test_icon_files_are_the_brand_mascot_and_are_packaged() -> None:
    brand = ADAPTER.parents[2] / "docs" / "brand"
    for filename, _fallback in _files():
        shipped = ADAPTER / "icons" / filename
        assert shipped.is_file(), filename
        assert shipped.read_bytes() == (brand / filename).read_bytes(), "copy of docs/brand, not a variant"
        assert shipped.read_bytes().startswith(b"\x89PNG")
    # The extension builder zips everything except these patterns: the icons must not match any.
    manifest = tomllib.loads((ADAPTER / "blender_manifest.toml").read_text(encoding="utf-8"))
    for pattern in manifest["build"]["paths_exclude_pattern"]:
        for filename, _fallback in _files():
            rel = f"/icons/{filename}"
            assert not fnmatch.fnmatch(rel, pattern.rstrip("/") + "*") or pattern.startswith("/tests"), pattern


def _files():
    spec = importlib.util.spec_from_file_location("wysp_icons_names", ADAPTER / "ui_icons.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.ICON_FILES.values())
