"""A complete, minimal Wysp adapter in Python: a tiny notes app. The adapter author guide (docs/adapter-guide.md)
walks through this file. Run it against a Core with:

    uv run python sdk/python/examples/notes_adapter.py            # needs `uv run wysp serve` and ~/.wysp/token
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from wysp_adapter_sdk import ActionOutcome, AdapterClient, AdapterRuntime, ErrorCode, WyspError

# 1. The manifest: who you are, what you can do, which kinds of things you show. Declare only what you implement.
MANIFEST: dict[str, Any] = {
    "adapter_id": "notes-demo",
    "app": {"name": "Notes", "version": "1.0"},
    "contract_version": "1.1.0",
    "integration_level": "native",
    "ref_scheme": "notes",  # every ref is notes://...
    "capabilities": ["observe", "context", "actions", "execute", "undo", "highlight", "events.state"],
    "entity_kinds": [{"kind": "notebook", "label": "Notebook"}, {"kind": "note", "label": "Note"}],
    "volatile_props": [],
    "locales": ["en"],
    "profile_id": "notes-demo",  # a folder of YAML (skills, concepts) the Core finds by this id
}


def note_ref(note_id: str) -> str:
    return f"notes://note/{note_id}"  # stable, unique, URI-like


class Notes(AdapterRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.notes: dict[str, str] = {"n1": "Buy milk", "n2": "Call Ada"}
        self.highlighted: str | None = None
        self.register_actions()

    # 2. observe: the entity graph of what the application holds. Keep it under 500 entities / 256 KB and say so
    #    with `truncated` and `counts` when you cut. Mark anything secret with props {"sensitive": true}: the Core
    #    then names it nowhere (not in the tutor's prompt, not in the survey).
    def observe(self, scope: dict[str, Any]) -> dict[str, Any]:
        entities: list[dict[str, Any]] = [
            {"ref": "notes://notebook/main", "kind": "notebook", "label": "Main", "props": {"notes": len(self.notes)}}
        ]
        for nid, text in sorted(self.notes.items()):
            entities.append(
                {
                    "ref": note_ref(nid),
                    "kind": "note",
                    "label": text,
                    "parent": "notes://notebook/main",
                    "props": {"chars": len(text)},
                }
            )
        return {
            "observation_id": f"obs-{time.monotonic_ns()}",
            "state_version": self.state_version(),
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
            "scope": {"level": scope.get("level", "focus")},
            "entities": entities,
            "links": [],
            "focus": [],
            "truncated": False,
            "counts": {"note": len(self.notes), "notebook": 1},
        }

    # 3. get_context: a short summary of where the user is right now (8 KB at most, 500 ms budget).
    def get_context(self) -> dict[str, Any]:
        return {"summary": f"Notes app with {len(self.notes)} notes.", "mode": "browsing", "focus": [], "facts": {}}

    # 4. highlight (contract 1.1): duration_ms 0 means "until cleared". Send report_highlight_dismissed(ref) when
    #    the user interacts with the highlighted thing. One highlight at a time.
    def highlight(self, ref: str, style: str, duration_ms: int) -> dict[str, Any]:
        if not ref.startswith("notes://note/") or ref.rsplit("/", 1)[-1] not in self.notes:
            raise WyspError(ErrorCode.TARGET_NOT_FOUND, f"no such note: {ref}")
        self.highlighted = ref  # a real adapter draws something here (and starts a timer when duration_ms > 0)
        return {"ok": True}

    def clear_highlight(self) -> dict[str, Any]:
        cleared, self.highlighted = self.highlighted is not None, None
        return {"cleared": cleared}

    # 5. actions: a closed catalog. Each has a JSON-schema for its params, a risk, and postconditions (JMESPath
    #    predicates the Core evaluates on a fresh observation to VERIFY the result).
    def register_actions(self) -> None:
        self.registry.register(
            {
                "id": "rename_note",
                "title": {"en": "Rename a note"},
                "description": "Change the text of a note.",
                "params_schema": {
                    "type": "object",
                    "properties": {"note": {"type": "string"}, "text": {"type": "string", "minLength": 1}},
                    "required": ["note", "text"],
                    "additionalProperties": False,
                },
                "risk": "reversible",
                "reversible": True,
                "preconditions": [],
                "postconditions": [{"ref": "${params.note}", "path": "label", "op": "eq", "value": "${params.text}"}],
                "guide": {
                    "ui_path": [{"text": "Double-click the note and type the new text", "target": "${params.note}"}]
                },
            },
            self.rename_note,
        )

    def rename_note(self, params: dict[str, Any], dry_run: bool) -> ActionOutcome:
        nid = str(params["note"]).rsplit("/", 1)[-1]
        if nid not in self.notes:
            raise WyspError(ErrorCode.TARGET_NOT_FOUND, f"no such note: {params['note']}")
        before, after = self.notes[nid], str(params["text"])
        if dry_run:  # validate and preview, change nothing
            return ActionOutcome(preview={"before": before, "after": after})

        def undo() -> None:
            self.notes[nid] = before

        self.notes[nid] = after
        return ActionOutcome(changed=[note_ref(nid)], undo=undo)


def main() -> None:
    token = (Path.home() / ".wysp" / "token").read_text(encoding="utf-8").strip()
    app = Notes()
    client = AdapterClient(
        MANIFEST, "ws://127.0.0.1:8765/ws/adapter", token, app.handle, state_version=app.state_version
    )
    app.client = client
    client.start()
    print("connected; Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        client.stop()


if __name__ == "__main__":
    main()
