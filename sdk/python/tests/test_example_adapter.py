"""The adapter in the author guide really satisfies the contract (it is the guide's example)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from wysp_core.contract import ActionResult, ActionSpec, Context, Manifest, Observation, check_observation

_PATH = Path(__file__).parent.parent / "examples" / "notes_adapter.py"
_spec = importlib.util.spec_from_file_location("notes_adapter", _PATH)
assert _spec and _spec.loader
notes_adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(notes_adapter)


def test_manifest_observation_context_and_actions_validate():
    app = notes_adapter.Notes()
    manifest = Manifest.model_validate(notes_adapter.MANIFEST)
    obs = Observation.model_validate(app.handle("adapter.observe", {"scope": {"level": "full"}}))
    assert check_observation(obs, {k.kind for k in manifest.entity_kinds}) == []
    Context.model_validate(app.handle("adapter.get_context", {}))
    specs = [ActionSpec.model_validate(s) for s in app.handle("adapter.get_actions", {})]
    assert [s.id for s in specs] == ["rename_note"]


def test_action_executes_verifies_and_undoes():
    app = notes_adapter.Notes()
    ref = notes_adapter.note_ref("n1")
    call = {"action_id": "rename_note", "params": {"note": ref, "text": "Buy oat milk"}}
    result = ActionResult.model_validate(app.handle("adapter.execute", {"call": call}))
    assert result.status == "ok" and result.undo_token
    assert app.notes["n1"] == "Buy oat milk"
    app.handle("adapter.undo", {"token": result.undo_token})
    assert app.notes["n1"] == "Buy milk"


def test_highlight_persists_until_cleared():
    app = notes_adapter.Notes()
    app.handle("adapter.highlight", {"ref": notes_adapter.note_ref("n2"), "duration_ms": 0})
    assert app.handle("adapter.clear_highlight", {}) == {"cleared": True}
    assert app.handle("adapter.clear_highlight", {}) == {"cleared": False}
