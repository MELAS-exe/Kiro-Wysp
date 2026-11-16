"""Live property tests: BLD-P2 and BLD-P3 run inside a real headless Blender 5.2.

    uv run pytest -m live -o addopts="" apps/blender-tutor/tests/test_prop_bld_live.py

The properties are checked by `probe_properties.py` (Hypothesis inside Blender); this module reads its output.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DEFAULT_BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def prop_output(tmp_path_factory) -> list[str]:
    exe = Path(os.environ.get("WYSP_BLENDER", DEFAULT_BLENDER))
    if not exe.exists():
        pytest.skip("Blender not found; set WYSP_BLENDER")
    env = {**os.environ, "PYTHONPATH": str(REPO / ".venv" / "Lib" / "site-packages")}
    scene = tmp_path_factory.mktemp("props") / "pumpkin.blend"  # a private copy: the probe edits the scene
    subprocess.run(
        [str(exe), "-b", "--python", str(REPO / "apps/blender-tutor/demo/build_scene.py"), "--", "--out", str(scene)],
        check=True, capture_output=True, env=env, timeout=180,
    )  # fmt: skip
    proc = subprocess.run(
        [str(exe), "-b", "--python-use-system-env", str(scene), "--python", str(REPO / "apps/blender-tutor/tests/probe_properties.py")],
        capture_output=True, text=True, env=env, timeout=600, encoding="utf-8", errors="replace",
    )  # fmt: skip
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("PROP")]
    assert "PROP-DONE" in lines, proc.stdout[-1500:] + proc.stderr[-800:]
    return lines


def test_prop_bld_p3_every_modifier_type_projects_to_valid_json(prop_output):
    """BLD-P3: each modifier type Blender 5.2 can add to a mesh yields a schema-valid entity."""
    bad = [ln for ln in prop_output if ln.startswith("PROP p3 BAD")]
    assert not bad, bad
    ok = [ln for ln in prop_output if ln.startswith("PROP p3 ok")]
    assert len(ok) >= 20, prop_output
    assert any(" BEVEL " in ln for ln in ok) and any(" SUBSURF " in ln for ln in ok)


def test_prop_bld_p2_undo_in_reverse_order_restores_the_digest(prop_output):
    """BLD-P2: random sequences of reversible actions are undone back to the initial state digest."""
    assert not [ln for ln in prop_output if ln.startswith("PROP p2 BAD")], prop_output
    assert any(ln.startswith("PROP p2 ok") for ln in prop_output), prop_output
