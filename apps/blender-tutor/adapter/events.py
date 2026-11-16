"""Change detection: turns scene changes into contract events, tagged with who caused them.

A depsgraph handler only marks the scene dirty (cheap, it runs on every redraw-worthy change). The
main-thread `poll()` then diffs per-entity hashes at most every 250 ms (1 s when idle), so bursts of
updates become one `event.state_changed`. Changes within a short window after a Wysp action are
tagged origin "wysp"; everything else is "user".
"""

from __future__ import annotations

import hashlib
import json
import logging
import time

import bpy
from bpy.app.handlers import persistent

from . import observe

log = logging.getLogger("wysp.blender")

FAST_INTERVAL_S = 0.25
IDLE_INTERVAL_S = 1.0


def _entity_hash(e: dict) -> str:
    blob = json.dumps([e["kind"], e.get("parent"), e["props"]], sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]  # noqa: S324 - change detection, not security


class SceneWatcher:
    def __init__(self, adapter) -> None:
        self.adapter = adapter
        self.fast_poll = False  # headless: no depsgraph handler fires, so poll at the fast rate
        self.dirty = True
        self._sig: dict[str, tuple[str, str]] | None = None  # ref -> (kind, hash)
        self._focus: list[str] | None = None
        self._next = 0.0
        self._handlers: list[tuple[list, object]] = []

    # --------------------------------------------------------------------- handlers
    def start(self) -> None:
        if self._handlers:
            return
        watcher = self

        @persistent
        def on_depsgraph(*_args) -> None:
            watcher.dirty = True

        @persistent
        def on_undo_redo(*_args) -> None:
            watcher.adapter.registry.clear_undo()  # tokens are stale once Blender itself undoes or redoes
            watcher.dirty = True

        @persistent
        def on_load(*_args) -> None:
            watcher.adapter.registry.clear_undo()
            watcher.reset()

        for lst, fn in (
            (bpy.app.handlers.depsgraph_update_post, on_depsgraph),
            (bpy.app.handlers.undo_post, on_undo_redo),
            (bpy.app.handlers.redo_post, on_undo_redo),
            (bpy.app.handlers.load_post, on_load),
        ):
            lst.append(fn)
            self._handlers.append((lst, fn))

    def stop(self) -> None:
        for lst, fn in self._handlers:
            if fn in lst:
                lst.remove(fn)
        self._handlers.clear()

    def reset(self) -> None:
        self._sig = None
        self._focus = None
        self.dirty = True

    # ------------------------------------------------------------------------- poll
    def poll(self) -> None:
        now = time.monotonic()
        if now < self._next:
            return
        self._next = now + (FAST_INTERVAL_S if (self.dirty or self.fast_poll) else IDLE_INTERVAL_S)
        self.check_now()

    def check_now(self) -> None:
        self.dirty = False
        entities, _links, _trunc = observe.build_entities(bpy.context.scene)
        sig = {e["ref"]: (e["kind"], _entity_hash(e)) for e in entities}
        focus = observe.focus_refs()
        if self._sig is None:  # first look: just remember the baseline
            self._sig, self._focus = sig, focus
            return
        old = self._sig
        changed = sorted(r for r in set(sig) | set(old) if sig.get(r) != old.get(r))
        self._sig = sig
        if changed:
            self.adapter.report_change(changed)
            self._derive_user_actions(old, sig, entities)
        if focus != self._focus:
            old_focus, self._focus = self._focus, focus
            # The focus is part of an observation, so it must move the state version. Without this a
            # pure selection leaves the version unchanged and the Core cannot tell a fresh observation
            # from the one taken when an exercise started (no "select X" exercise could ever pass).
            self.adapter.bump()
            self.adapter.report_selection(focus)
            self.adapter.on_focus_changed(old_focus or [], focus)  # dismisses a persistent highlight

    def _derive_user_actions(self, old: dict, new: dict, entities: list[dict]) -> None:
        """Turn modifier-level diffs into user_action events (modifier_added / removed / moved)."""
        for ref, (kind, h) in new.items():
            if kind == "modifier" and ref not in old:
                self.adapter.report_user_action("modifier_added", ref)
            elif kind == "modifier" and old.get(ref, (None, h))[1] != h:
                self.adapter.report_user_action("modifier_changed", ref)
        for ref, (kind, _h) in old.items():
            if kind == "modifier" and ref not in new:
                self.adapter.report_user_action("modifier_removed", ref)
