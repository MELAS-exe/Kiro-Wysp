"""Mock adapter: a fictional Kanban application. Implements the whole contract, with no real host.

Used by Core tests and the Contract Test Kit. Refs: mock://board/b1, mock://column/<id>, mock://card/<id>.
"""

from __future__ import annotations

import itertools
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from wysp_adapter_sdk import ActionOutcome, AdapterRuntime, ErrorCode, WyspError

BOARD = "mock://board/b1"
COLUMNS = [("todo", "To do"), ("doing", "Doing"), ("done", "Done")]
COLUMN_IDS = [c for c, _ in COLUMNS]


def col_ref(col: str) -> str:
    return f"mock://column/{col}"


def card_ref(card: str) -> str:
    return f"mock://card/{card}"


def manifest() -> dict[str, Any]:
    return {
        "adapter_id": "mock-kanban",
        "app": {"name": "MockKanban", "version": "1.0"},
        "contract_version": "1.1.0",
        "integration_level": "native",
        "ref_scheme": "mock",
        "capabilities": [
            "observe",
            "context",
            "actions",
            "execute",
            "undo",
            "highlight",
            "events.state",
            "events.selection",
            "events.user_action",
        ],  # fmt: skip
        "entity_kinds": [
            {"kind": "board", "label": "Board"},
            {"kind": "column", "label": "Column"},
            {"kind": "card", "label": "Card"},
        ],
        "volatile_props": [],
        "locales": ["en"],
        "profile_id": "mock-kanban",
    }


def _spec(
    id_: str, title: str, description: str, props: dict, required: list[str], risk: str, post: list, ui: list
) -> dict:
    return {
        "id": id_,
        "title": {"en": title},
        "description": description,
        "params_schema": {"type": "object", "properties": props, "required": required, "additionalProperties": False},
        "risk": risk,
        "reversible": risk == "reversible",
        "preconditions": [],
        "postconditions": post,
        "guide": {"ui_path": ui},
    }


class MockKanban(AdapterRuntime):
    def __init__(self, latency_s: float = 0.0, seed_cards: bool = True) -> None:
        super().__init__()
        self.latency_s = latency_s
        self._lock = threading.RLock()
        self._ids = itertools.count(1)
        self.cards: dict[str, dict[str, Any]] = {}
        self.selected: str | None = None
        self.highlight_log: list[tuple[str, int]] = []  # (ref, duration_ms) of every highlight request
        self.highlight_active: str | None = None  # the persistent highlight, if any
        self.highlight_clears = 0
        if seed_cards:
            for title, col in (("Write the spec", "done"), ("Build the core", "doing"), ("Record the demo", "todo")):
                self._add_card(title, col)
        self._register_actions()

    # ----------------------------------------------------------------------- state helpers
    def _add_card(self, title: str, column: str, card_id: str | None = None) -> str:
        cid = card_id or f"c{next(self._ids)}"
        self.cards[cid] = {"id": cid, "title": title, "column": column}
        return cid

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"cards": {k: dict(v) for k, v in self.cards.items()}, "selected": self.selected}

    def restore(self, snap: dict[str, Any]) -> None:
        with self._lock:
            self.cards = {k: dict(v) for k, v in snap["cards"].items()}
            self.selected = snap["selected"]

    # --------------------------------------------------------------------------- observation
    def observe(self, scope: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            entities: list[dict[str, Any]] = [
                {"ref": BOARD, "kind": "board", "label": "Project board", "props": {"columns": len(COLUMNS)}}
            ]
            counts = {c: sum(1 for k in self.cards.values() if k["column"] == c) for c in COLUMN_IDS}
            for cid, title in COLUMNS:
                entities.append(
                    {
                        "ref": col_ref(cid),
                        "kind": "column",
                        "label": title,
                        "parent": BOARD,
                        "props": {"card_count": counts[cid]},
                    }
                )
            for card in sorted(self.cards.values(), key=lambda c: int(c["id"][1:])):
                entities.append(
                    {
                        "ref": card_ref(card["id"]),
                        "kind": "card",
                        "label": card["title"],
                        "parent": col_ref(card["column"]),
                        "props": {"column": card["column"], "selected": card["id"] == self.selected},
                    }
                )
            focus = [card_ref(self.selected)] if self.selected in self.cards else []
            return {
                "observation_id": uuid.uuid4().hex[:8],
                "state_version": self.state_version(),
                "captured_at": datetime.now(UTC).isoformat(),
                "scope": {"level": scope.get("level", "focus")},
                "entities": entities,
                "links": [],
                "focus": focus,
                "truncated": False,
                "counts": {"card": len(self.cards), "column": len(COLUMNS), "board": 1},
            }

    def get_context(self) -> dict[str, Any]:
        with self._lock:
            return {
                "summary": f"A Kanban board with {len(self.cards)} cards in {len(COLUMNS)} columns.",
                "mode": "board",
                "focus": [card_ref(self.selected)] if self.selected in self.cards else [],
                "facts": {"cards": len(self.cards)},
            }

    def highlight(self, ref: str, style: str, duration_ms: int) -> dict[str, Any]:
        self.last_highlight = ref
        self.highlight_log.append((ref, duration_ms))
        self.highlight_active = ref if duration_ms == 0 else None  # 0: persistent (contract 1.1)
        return {"ok": True}

    def clear_highlight(self) -> dict[str, Any]:
        cleared = self.highlight_active is not None
        self.highlight_active = None
        self.highlight_clears += 1
        return {"cleared": cleared}

    def simulate_user_touches_highlight(self) -> None:
        """The user clicked the highlighted element: the adapter takes it down and says so."""
        ref, self.highlight_active = self.highlight_active, None
        if ref is not None:
            self.report_highlight_dismissed(ref)

    # ------------------------------------------------------------------------------ actions
    def _register_actions(self) -> None:
        col_enum = {"type": "string", "enum": COLUMN_IDS}
        ref = {"type": "string", "pattern": "^mock://card/c[0-9]+$"}
        r = self.registry.register
        r(
            _spec(
                "create_card",
                "Create a card",
                "Create a new card in a column.",
                {"title": {"type": "string", "minLength": 1, "maxLength": 80}, "column": col_enum},
                ["title", "column"],
                "reversible",
                [
                    {
                        "path": "entities[?kind=='card' && label=='${params.title}' && props.column=='${params.column}'] | length(@)",
                        "op": "gte",
                        "value": 1,
                    }
                ],
                [
                    {"text": "Click “Add card” in the ${params.column} column"},
                    {"text": "Type “${params.title}” and press Enter"},
                ],
            ),  # fmt: skip
            self._create_card,
        )
        r(
            _spec(
                "move_card",
                "Move a card",
                "Move a card to another column.",
                {"card": ref, "column": col_enum},
                ["card", "column"],
                "reversible",
                [{"ref": "${params.card}", "path": "props.column", "op": "eq", "value": "${params.column}"}],
                [{"text": "Drag “${label:params.card}” to the ${params.column} column", "target": "${params.card}"}],
            ),  # fmt: skip
            self._move_card,
        )
        r(
            _spec(
                "rename_card",
                "Rename a card",
                "Change the title of a card.",
                {"card": ref, "title": {"type": "string", "minLength": 1, "maxLength": 80}},
                ["card", "title"],
                "reversible",
                [{"ref": "${params.card}", "path": "label", "op": "eq", "value": "${params.title}"}],
                [
                    {
                        "text": "Double-click “${label:params.card}” and type “${params.title}”",
                        "target": "${params.card}",
                    }
                ],
            ),  # fmt: skip
            self._rename_card,
        )
        r(
            _spec(
                "select_card",
                "Select a card",
                "Select a card so it is the focus.",
                {"card": ref},
                ["card"],
                "ui_state",
                [{"path": "focus", "op": "contains", "value": "${params.card}"}],
                [{"text": "Click “${label:params.card}”", "target": "${params.card}"}],
            ),  # fmt: skip
            self._select_card,
        )
        r(
            _spec(
                "archive_card",
                "Archive a card",
                "Permanently archive a card. It cannot be restored.",
                {"card": ref},
                ["card"],
                "irreversible",
                [{"ref": "${params.card}", "path": "label", "op": "not_exists"}],
                [{"text": "Right-click “${label:params.card}” and choose Archive", "target": "${params.card}"}],
            ),  # fmt: skip
            self._archive_card,
        )
        r(
            _spec(
                "describe_card",
                "Describe a card",
                "Read a card's title and column. Nothing changes.",
                {"card": ref},
                ["card"],
                "read_only",
                [],
                [],
            ),  # fmt: skip
            self._describe_card,
        )

    def _describe_card(self, p: dict[str, Any], dry: bool) -> ActionOutcome:
        with self._lock:
            card = self._need_card(p["card"])
            return ActionOutcome(message=f"{card['title']} is in {card['column']}")

    def _need_card(self, ref: str) -> dict[str, Any]:
        cid = ref.rsplit("/", 1)[-1]
        card = self.cards.get(cid)
        if card is None:
            raise WyspError(ErrorCode.TARGET_NOT_FOUND, f"no card {ref}")
        return card

    def _create_card(self, p: dict[str, Any], dry: bool) -> ActionOutcome:
        with self._lock:
            if dry:
                return ActionOutcome(preview={"would_create": p["title"]})
            cid = self._add_card(p["title"], p["column"])
        return ActionOutcome(changed=[card_ref(cid)], undo=lambda: self._drop(cid), message=f"Created {cid}")

    def _drop(self, cid: str) -> None:
        with self._lock:
            self.cards.pop(cid, None)
            if self.selected == cid:
                self.selected = None

    def _move_card(self, p: dict[str, Any], dry: bool) -> ActionOutcome:
        with self._lock:
            card = self._need_card(p["card"])
            before = card["column"]
            if dry:
                return ActionOutcome(preview={"from": before, "to": p["column"]})
            card["column"] = p["column"]
        return ActionOutcome(changed=[p["card"]], undo=lambda: card.update(column=before))

    def _rename_card(self, p: dict[str, Any], dry: bool) -> ActionOutcome:
        with self._lock:
            card = self._need_card(p["card"])
            before = card["title"]
            if dry:
                return ActionOutcome(preview={"from": before, "to": p["title"]})
            card["title"] = p["title"]
        return ActionOutcome(changed=[p["card"]], undo=lambda: card.update(title=before))

    def _select_card(self, p: dict[str, Any], dry: bool) -> ActionOutcome:
        with self._lock:
            card = self._need_card(p["card"])
            before = self.selected
            if dry:
                return ActionOutcome()
            self.selected = card["id"]
        return ActionOutcome(changed=[p["card"]], undo=lambda: setattr(self, "selected", before))

    def _archive_card(self, p: dict[str, Any], dry: bool) -> ActionOutcome:
        with self._lock:
            card = self._need_card(p["card"])
            if dry:
                return ActionOutcome(preview={"would_archive": card["title"]})
            self._drop(card["id"])
        return ActionOutcome(changed=[p["card"]])

    # ------------------------------------------------------------------- simulated user
    def simulate_user(self, action_id: str, params: dict[str, Any]) -> None:
        """Apply a change as if the human did it in the app's own UI: emits events with origin 'user'."""
        entry = self.registry._actions[action_id]  # noqa: SLF001 - test helper
        outcome = entry[1](params, False)
        self.report_change(outcome.changed, origin="user")
        if action_id == "select_card":
            self.report_selection(outcome.changed)
        self.report_user_action(action_id, outcome.changed[0] if outcome.changed else None, params)
