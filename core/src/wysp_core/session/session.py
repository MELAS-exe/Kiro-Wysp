"""The tutoring session: ties adapters, board, narration, permissions and the LLM turn loop together."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..board import Board, BoardError, apply_ops, make_patch, node_id, project, validate_ops
from ..contract import ActionCall, Observation, Scope, WyspError
from ..gateway import AdapterConnection, AdapterRegistry
from ..llm import CancelToken, LLMProvider
from ..narration import NarrationState
from ..pedagogy import Profile, find_profile
from ..trust import AuditLog, PermissionGate, UndoStack
from ..ui_api import UiHub
from .bus import EventBus

log = logging.getLogger("wysp.session")

REFRESH_DEBOUNCE_S = 0.4
HISTORY_LIMIT = 12


@dataclass
class Watch:
    """A guided step the user is performing; verified when the application reports a user change."""

    adapter_id: str
    action_id: str
    title: str
    params: dict[str, Any]
    postconditions: list[Any]
    step_ids: list[str] = field(default_factory=list)


class Session:
    def __init__(
        self,
        registry: AdapterRegistry,
        bus: EventBus,
        hub: UiHub,
        audit: AuditLog,
        llm: LLMProvider,
        profile_roots: list[Path] | None = None,
        lang: str = "en",
    ) -> None:
        self.id = uuid.uuid4().hex[:10]
        self.registry = registry
        self.bus = bus
        self.hub = hub
        self.audit = audit
        self.llm = llm
        self.lang = lang
        self.profile_roots = profile_roots or []
        self.profile: Profile | None = None
        self.gate = PermissionGate(audit, hub.broadcast)
        self.undo = UndoStack()
        self.board = Board()
        self.observed_refs: set[str] = set()
        self.board_spec: dict[str, Any] | None = None  # last show_entities request, replayed on refresh
        self.watch: Watch | None = None
        self.narration = NarrationState()
        self.history: list[dict[str, Any]] = []
        self.status = "idle"
        self.active_adapter_id: str | None = None
        self._turn_task: asyncio.Task | None = None
        self._cancel: CancelToken | None = None
        self._refresh_task: asyncio.Task | None = None

    # ------------------------------------------------------------------------ wiring
    def start(self) -> None:
        self.bus.subscribe(self._on_bus_event)

    @property
    def conn(self) -> AdapterConnection | None:
        active = self.registry.get(self.active_adapter_id)
        if active is not None:
            return active
        conns = self.registry.all()
        return conns[0] if len(conns) == 1 else None

    async def activate(self, adapter_id: str) -> None:
        conn = self.registry.get(adapter_id)
        if conn is None:
            await self.broadcast(
                {"type": "error", "code": "no_such_adapter", "message": f"{adapter_id} is not connected"}
            )
            return
        if self.active_adapter_id != adapter_id:
            self.active_adapter_id = adapter_id
            self._on_new_active(conn)
        await self.send_state()

    def _on_new_active(self, conn: AdapterConnection) -> None:
        self.profile = find_profile(conn.manifest.profile_id, self.profile_roots)
        self.observed_refs.clear()
        self.board_spec = None
        self.watch = None

    # --------------------------------------------------------------------- broadcasting
    async def broadcast(self, message: dict[str, Any]) -> None:
        await self.hub.broadcast(message)

    async def send_state(self) -> None:
        conn = self.conn
        await self.broadcast(
            {
                "type": "session.state",
                "session_id": self.id,
                "lang": self.lang,
                "active_adapter": conn.adapter_id if conn else None,
                "llm": getattr(self.llm, "name", "?"),
                "profile": self.profile.id if self.profile else None,
            }
        )
        await self.broadcast({"type": "adapters.list", "adapters": self.registry.describe()})
        await self.broadcast({"type": "status", "state": self.status})

    def snapshot_messages(self) -> list[dict[str, Any]]:
        conn = self.conn
        return [
            {
                "type": "session.state",
                "session_id": self.id,
                "lang": self.lang,
                "active_adapter": conn.adapter_id if conn else None,
                "llm": getattr(self.llm, "name", "?"),
                "profile": self.profile.id if self.profile else None,
            },
            {"type": "adapters.list", "adapters": self.registry.describe()},
            {"type": "status", "state": self.status},
            {"type": "board.snapshot", "board": self.board.model_dump(mode="json")},
        ]

    async def set_status(self, state: str) -> None:
        if state != self.status:
            self.status = state
            await self.broadcast({"type": "status", "state": state})

    async def activity(self, text: str) -> None:
        await self.broadcast({"type": "activity", "text": text})

    # ----------------------------------------------------------------------------- board
    async def apply_board(self, ops: list[dict[str, Any]], validate: bool = True) -> dict[str, Any]:
        warnings: list[str] = []
        if validate:
            ops, warnings = validate_ops(ops, self.observed_refs)
        try:
            after = apply_ops(self.board, ops)
        except (BoardError, ValueError, KeyError) as exc:
            return {"ok": False, "error": str(exc)}
        patch = make_patch(self.board, after, ops)
        self.board = after
        await self.broadcast({"type": "board.patch", "patch": patch.model_dump(mode="json")})
        return {"ok": True, "warnings": warnings}

    async def observe(self, scope: Scope | None = None) -> Observation:
        conn = self.conn
        if conn is None:
            raise WyspError(-32016, "no application is connected")
        obs = await conn.observe(scope or Scope(level="full"))
        self.observed_refs.update(e.ref for e in obs.entities)
        return obs

    def board_props(self) -> dict[str, list[str]]:
        return self.profile.board_props if self.profile else {}

    async def refresh_board(self) -> None:
        """Re-project the last show_entities request so observed nodes follow the real application."""
        conn = self.conn
        spec = self.board_spec
        if conn is None or spec is None:
            return
        try:
            obs = await self.observe(Scope(level="full"))
        except WyspError as exc:
            log.warning("refresh failed: %s", exc.message)
            return
        ops, _missing = project(obs, spec["refs"], spec["include_children"], self.board_props())
        new_ids = {op["node"]["id"] for op in ops if op["op"] == "add_node"}
        previous = set(spec.get("node_ids", []))
        remove = [{"op": "remove_node", "id": nid} for nid in previous - new_ids if self.board.node(nid)]
        spec["node_ids"] = sorted(new_ids)
        if not ops and not remove:
            return
        result = await self.apply_board(remove + ops + [{"op": "set_stale", "stale": False}], validate=False)
        if not result["ok"]:
            log.warning("board refresh rejected: %s", result["error"])

    # ----------------------------------------------------------------------- narration
    async def narrate(self, text: str, provenance: str = "observed", cues: list[dict[str, Any]] | None = None) -> int:
        if self.narration.turn_id is None:
            self.narration.new_turn()
        segments = self.narration.add(text, provenance, cues)
        for seg in segments:
            await self.broadcast(seg.to_message())
        if segments:
            await self.set_status("speaking")
        return len(segments)

    async def on_narration_progress(self, segment_id: str, played: bool) -> None:
        if played:
            self.narration.mark_played(segment_id)
        if all(s.id in self.narration.played for s in self.narration.segments) and self._turn_task_done():
            await self.set_status("idle")

    def _turn_task_done(self) -> bool:
        return self._turn_task is None or self._turn_task.done()

    async def on_narration_cue(self, segment_id: str, index: int) -> None:
        seg = self.narration.find(segment_id)
        if seg is None or not (0 <= index < len(seg.cues)):
            return
        cue = seg.cues[index]
        target = str(cue.get("target", ""))
        node = target if target.startswith(("n:", "c:")) else node_id(target)
        if cue.get("op") in ("focus", "highlight") and self.board.node(node):
            await self.apply_board([{"op": "set_focus", "ids": [node]}], validate=False)
        if cue.get("op") == "highlight":
            await self.highlight_ref(target[2:] if target.startswith("n:") else target)

    async def highlight_ref(self, ref: str, style: str = "pulse", duration_ms: int = 2500) -> bool:
        conn = self.conn
        if conn is None or not conn.manifest.has("highlight"):
            return False
        try:
            await conn.highlight(ref, style, duration_ms)
            return True
        except WyspError as exc:
            log.debug("highlight failed: %s", exc.message)
            return False

    # ---------------------------------------------------------------------------- turns
    async def user_message(self, text: str, source: str = "typed") -> None:
        await self.interrupt(quiet=True)
        from ..orchestrator import TurnRunner  # local import: orchestrator depends on Session

        self._cancel = CancelToken()
        runner = TurnRunner(self, self._cancel)
        self._turn_task = asyncio.create_task(runner.run(text), name="wysp-turn")

    async def wait_for_turn(self) -> None:
        """Await the running turn (tests)."""
        if self._turn_task:
            await asyncio.shield(self._turn_task)

    async def interrupt(self, quiet: bool = False) -> None:
        if self._cancel is not None:
            self._cancel.cancel()
        self.gate.cancel_all()
        had_turn = self.narration.turn_id is not None
        if had_turn:
            index = self.narration.interrupt()
            if not quiet:
                await self.broadcast(
                    {"type": "narration.cancel", "turn_id": self.narration.turn_id, "from_index": index}
                )
        if not quiet:
            await self.set_status("idle")

    async def resume(self) -> None:
        for seg in self.narration.resume():
            await self.broadcast(seg.to_message())

    # ------------------------------------------------------------------------ undo
    async def undo_last(self) -> str:
        conn = self.conn
        if conn is None:
            return "No application is connected."
        record = self.undo.peek(conn.adapter_id)
        if record is None:
            return "There is nothing of mine to undo."
        try:
            await conn.undo(record.token)
        except WyspError as exc:
            return f"I could not undo that: {exc.message}"
        self.undo.pop(conn.adapter_id)
        self.audit.append("undo", request_id=record.request_id, action_id=record.action_id, by="user")
        await self.refresh_board()
        return f"Undone: {record.title}."

    async def run_action(self, conn: AdapterConnection, call: ActionCall) -> Any:
        return await conn.execute(call)

    # --------------------------------------------------------------------- bus events
    async def _on_bus_event(self, event: dict[str, Any]) -> None:
        topic = event["topic"]
        if topic == "adapter.connected":
            conn = self.registry.get(event["adapter_id"])
            if conn is not None and (self.active_adapter_id in (None, conn.adapter_id) or self.conn is conn):
                self.active_adapter_id = conn.adapter_id
                self._on_new_active(conn)
                if self.board.stale:
                    await self.apply_board([{"op": "set_stale", "stale": False}], validate=False)
            await self.send_state()
        elif topic == "adapter.disconnected":
            await self.send_state()
            if event["adapter_id"] == self.active_adapter_id:
                await self.apply_board([{"op": "set_stale", "stale": True}], validate=False)
                await self.activity(f"{event['adapter_id']} disconnected. The board may be out of date.")
        elif topic == "adapter.event":
            await self._on_adapter_event(event)

    async def _on_adapter_event(self, event: dict[str, Any]) -> None:
        conn = self.conn
        if conn is None or event["adapter_id"] != conn.adapter_id:
            return
        if event["name"] != "state_changed":
            return
        origin = event["data"].get("origin", "unknown")
        self._schedule_after_change(origin)

    def _schedule_after_change(self, origin: str) -> None:
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
        self._refresh_task = asyncio.create_task(self._after_change(origin))

    async def _after_change(self, origin: str) -> None:
        try:
            await asyncio.sleep(REFRESH_DEBOUNCE_S)
            await self.refresh_board()
            # Changes made by Wysp itself never count as the user's achievement.
            if origin != "wysp" and self.watch is not None:
                from ..orchestrator.pipeline import check_watch

                await check_watch(self)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("after-change handling failed")
