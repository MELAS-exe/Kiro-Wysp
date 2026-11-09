"""Live tests: run the adapter inside a real headless Blender 5.2 and check what it reports.

    uv run pytest -m live -o addopts="" apps/blender-tutor/tests

Needs Blender (set WYSP_BLENDER to blender.exe, or install it in the default location).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DEFAULT_BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")

pytestmark = pytest.mark.live


def blender_exe() -> Path:
    exe = Path(os.environ.get("WYSP_BLENDER", DEFAULT_BLENDER))
    if not exe.exists():
        pytest.skip("Blender not found; set WYSP_BLENDER")
    return exe


@pytest.fixture(scope="module")
def probe_output() -> list[str]:
    scene = REPO / "apps" / "blender-tutor" / "demo" / "pumpkin.blend"
    env = {**os.environ, "PYTHONPATH": str(REPO / ".venv" / "Lib" / "site-packages")}
    if not scene.exists():
        subprocess.run(
            [str(blender_exe()), "-b", "--python", str(REPO / "apps/blender-tutor/demo/build_scene.py"), "--", "--out", str(scene)],
            check=True, capture_output=True, env=env, timeout=180,
        )  # fmt: skip
    proc = subprocess.run(
        [str(blender_exe()), "-b", "--python-use-system-env", str(scene), "--python", str(REPO / "apps/blender-tutor/tests/probe_adapter.py")],
        capture_output=True, text=True, env=env, timeout=240, encoding="utf-8", errors="replace",
    )  # fmt: skip
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("PROBE")]
    assert "PROBE-DONE" in lines, proc.stdout[-1500:] + proc.stderr[-800:]
    return lines


def line(lines: list[str], prefix: str) -> str:
    return next(ln for ln in lines if ln.startswith(prefix))


def test_observation_has_the_scene_and_the_modifier_stack(probe_output):
    assert "kinds: ['collection', 'material', 'modifier', 'object', 'scene']" in line(probe_output, "PROBE entities")
    assert "('Subdivision', 'SUBSURF', 0), ('Solidify', 'SOLIDIFY', 1)" in line(probe_output, "PROBE modifiers")


def test_catalog_lists_every_action(probe_output):
    actions = line(probe_output, "PROBE actions")
    for name in (
        "select_object",
        "add_modifier",
        "set_modifier_property",
        "move_modifier",
        "remove_modifier",
        "apply_modifier",
    ):
        assert name in actions


def test_bld_p2_reversible_actions_are_undone_exactly(probe_output):
    """BLD-P2: undoing a reversible action restores the exact state digest."""
    assert "PROBE undo restores digest: True" in probe_output
    for name in ("set_modifier_property", "move_modifier", "remove_modifier"):
        assert f"PROBE {name}: changed=True undo_restores=True" in probe_output


def test_error_codes_follow_the_contract(probe_output):
    assert "[('add_modifier', -32012), ('bogus', -32011)]" in line(probe_output, "PROBE errors")
