"""Interface element refs: parsing and consistency with the profile primer (no Blender needed)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ADAPTER = Path(__file__).resolve().parents[1] / "adapter"
_spec = importlib.util.spec_from_file_location("wysp_ui_targets", ADAPTER / "ui_targets.py")
ui_targets = importlib.util.module_from_spec(_spec)
sys.modules["wysp_ui_targets"] = ui_targets  # dataclasses look the module up while it loads
_spec.loader.exec_module(ui_targets)


def test_every_listed_ref_parses() -> None:
    for ref in ui_targets.all_refs():
        target = ui_targets.parse(ref)
        assert target is not None, ref
        assert target.label


def test_unknown_refs_are_rejected() -> None:
    for ref in (
        "blender://ui/area/NOPE",
        "blender://ui/properties/tab/BOGUS",
        "blender://ui/region/VIEW_3D/NOPE",
        "blender://object/Cube",
        "blender://ui/topbar",
    ):
        assert ui_targets.parse(ref) is None, ref


def test_tab_targets_open_their_tab() -> None:
    t = ui_targets.parse("blender://ui/properties/tab/MODIFIER")
    assert t.tab == "MODIFIER" and t.area == "PROPERTIES" and t.regions == ("NAVIGATION_BAR",)


def test_primer_mentions_every_area_region_and_tab() -> None:
    primer = yaml.safe_load((ADAPTER.parent / "profile" / "profile.yaml").read_text(encoding="utf-8"))["primer"]
    assert "blender://ui/label/" in primer
    for ref in ui_targets.all_refs():
        name = ref.rsplit("/", 1)[1]
        if name == "SIDEBAR":
            assert "never point there" in primer  # the sidebar is Wysp's own chat
            continue
        assert name in primer, ref
