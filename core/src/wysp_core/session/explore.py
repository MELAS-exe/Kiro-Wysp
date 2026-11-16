"""Project exploration: a code map built from the adapter's own structure, then a study phase for the tutor.

The user is asked first (`explore.start`); nothing is crawled before. The map is built without any language model,
by walking the adapter's containers with `observe {level: full, root: <ref>}`. It holds names, signatures, sizes and
dependencies, never code bodies. The study phase then hands the agent a reading plan; the Core records which files
it really read (targets of read-only actions) so that what the tutor says about the code can be told apart from what
it guessed. Which kinds, properties and globs matter comes from the profile's `explore` section (data), not from here.
"""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import logging
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..contract import Observation, Scope, WyspError
from ..store import wysp_home

if TYPE_CHECKING:
    from ..pedagogy import Profile
    from .session import Session

log = logging.getLogger("wysp.explore")

MAX_CALLS = 4000
MAX_SECONDS = 300.0
MAX_ENTRIES = 60_000
OVERVIEW_CHARS = 3000
CODE_MAP_CHARS = 6000
PROMPT_CHARS = 5500
PLAN_LIMIT = 30
BRIEF_MAX_ITEMS = 40
TOPIC_CHARS = 80
SUMMARY_CHARS = 700
MAX_FILES_PER_ENTRY = 12
BUSY_WAIT_S = 5.0
BUSY_MAX_WAITS = 24
MAX_FAILURES = 25
PROGRESS_EVERY_S = 1.5
STUDY_TOTAL_CHARS = 24_000  # what one `study_read` call returns, in total: small enough to reach the agent intact
STUDY_PER_FILE_CHARS = 2000
STUDY_DEFAULT_FILES = 12  # files per call: three calls read a 30-file plan
STUDY_CONCURRENCY = 4
MIN_PLAN_COVERAGE = 0.8  # `finish_study` is refused until this share of the plan was read
MAX_FINISH_REFUSALS = 2

STUDY_TASK = (
    "Study this project now, once, then tell the user what you learned. "
    "1) Call study_read: it returns the text of about 12 of the files the Core picked per call. Call it again with "
    "`offset` = next_offset until next_offset is null (about three calls in all) and do not repeat a call. Do not read "
    "files one by one with the read action. "
    "2) Group what you read by theme and call record_understanding for each theme {topic, summary (at most 600 "
    "characters: what the code does and how it connects, only things you read), files: [refs you read]}. "
    "3) Call finish_study {overview}. It is refused until most of the plan has been read. "
    "4) Then one short narrate: what you learned, and what you did NOT read."
)


# ----------------------------------------------------------------------------------------------------- config
@dataclass
class ExploreConfig:
    root_kind: str
    containers: frozenset[str]
    files: frozenset[str]
    details: frozenset[str]
    depends_prop: str = "depends_on"
    pending_prop: str = "symbols"
    busy_prop: str = ""
    entry_symbols: tuple[str, ...] = ()
    priority_globs: tuple[str, ...] = ()
    skip_globs: tuple[str, ...] = ()
    read_action: str = ""  # the adapter's read-only action that returns a file's text (for study_read)
    read_target_param: str = "target"
    read_params: tuple[tuple[str, Any], ...] = ()

    @classmethod
    def from_profile(cls, profile: Profile | None) -> ExploreConfig | None:
        raw = getattr(profile, "explore", None)
        if not raw or not raw.get("root_kind"):
            return None
        return cls(
            root_kind=str(raw["root_kind"]),
            containers=frozenset(str(k) for k in raw.get("containers", [])),
            files=frozenset(str(k) for k in raw.get("files", [])),
            details=frozenset(str(k) for k in raw.get("details", [])),
            depends_prop=str(raw.get("depends_prop", "depends_on")),
            pending_prop=str(raw.get("pending_prop", "symbols")),
            busy_prop=str(raw.get("busy_prop", "")),
            entry_symbols=tuple(str(s) for s in raw.get("entry_symbols", [])),
            priority_globs=tuple(str(g) for g in raw.get("priority_globs", [])),
            skip_globs=tuple(str(g) for g in raw.get("skip_globs", [])),
            read_action=str(raw.get("read_action", "")),
            read_target_param=str(raw.get("read_target_param", "target")),
            read_params=tuple((str(k), v) for k, v in (raw.get("read_params") or {}).items()),
        )


def _clip(text: str, limit: int, note: str = "\n(cut to fit)") -> str:
    return text if len(text) <= limit else text[: max(0, limit - len(note))].rstrip() + note


def _one_line(text: Any, limit: int = 120) -> str:
    one = " ".join(str(text).split())
    return one if len(one) <= limit else one[: limit - 1] + "..."


def _match(path: str, label: str, globs: tuple[str, ...]) -> bool:
    """Does the file match one of the globs, by its name or by its path (rooted, so `*/test/*` also fits `test/x`)?"""
    candidates = (path.lower(), "/" + path.lower(), label.lower())
    return any(fnmatch.fnmatch(c, g.lower()) for g in globs for c in candidates)


# -------------------------------------------------------------------------------------------------- code map
@dataclass
class Entry:
    ref: str
    kind: str
    label: str
    parent: str | None
    props: dict[str, Any] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)


class CodeMap:
    """What the adapter reported about the project's structure. Sensitive entities never get in."""

    def __init__(self, cfg: ExploreConfig, root: str) -> None:
        self.cfg = cfg
        self.root = root
        self.entries: dict[str, Entry] = {}
        self._sensitive: set[str] = set()
        self._in_degree: Counter[str] | None = None

    # ---- building
    def ingest(self, obs: Observation) -> None:
        for e in obs.entities:
            if e.props.get("sensitive") is True or (e.parent in self._sensitive):
                self._sensitive.add(e.ref)
                continue
            if len(self.entries) >= MAX_ENTRIES and e.ref not in self.entries:
                continue
            entry = self.entries.get(e.ref)
            if entry is None:
                entry = Entry(e.ref, e.kind, _one_line(e.label, 200), e.parent)
                self.entries[e.ref] = entry
                parent = self.entries.get(e.parent) if e.parent else None
                if parent is not None and e.ref not in parent.children:
                    parent.children.append(e.ref)
            entry.props.update(self._keep(e))
        self._in_degree = None

    def _keep(self, e: Any) -> dict[str, Any]:
        cfg, p = self.cfg, e.props
        if e.kind in cfg.files:
            out: dict[str, Any] = {k: p[k] for k in ("language", "size_bytes", cfg.pending_prop) if k in p}
            deps = p.get(cfg.depends_prop)
            if isinstance(deps, list):
                out[cfg.depends_prop] = [str(d) for d in deps[:40]]
            return out
        if e.kind in cfg.details:
            out = {k: p[k] for k in ("type", "line") if k in p}
            if "signature" in p:
                out["signature"] = _one_line(p["signature"], 120)
            return out
        return {}

    # ---- reading
    def of_kind(self, kinds: frozenset[str]) -> list[Entry]:
        return [e for e in self.entries.values() if e.kind in kinds]

    def path_of(self, ref: str) -> str:
        parts: list[str] = []
        cur = self.entries.get(ref)
        while cur is not None and cur.kind != self.cfg.root_kind:
            parts.append(cur.label)
            cur = self.entries.get(cur.parent) if cur.parent else None
        return "/".join(reversed(parts))

    def descendants(self, ref: str, kinds: frozenset[str] | None = None) -> list[Entry]:
        out: list[Entry] = []
        stack = list(self.entries[ref].children) if ref in self.entries else []
        while stack:
            e = self.entries.get(stack.pop())
            if e is None:
                continue
            if kinds is None or e.kind in kinds:
                out.append(e)
            stack.extend(e.children)
        return out

    def in_degree(self) -> Counter[str]:
        if self._in_degree is None:
            deg: Counter[str] = Counter()
            for f in self.of_kind(self.cfg.files):
                for d in f.props.get(self.cfg.depends_prop, []):
                    if d in self.entries and d != f.ref:
                        deg[d] += 1
            self._in_degree = deg
        return self._in_degree

    def imported_by(self, ref: str) -> list[str]:
        return [
            f.ref
            for f in self.of_kind(self.cfg.files)
            if ref in f.props.get(self.cfg.depends_prop, []) and f.ref != ref
        ]

    def stats(self) -> dict[str, int]:
        files = self.of_kind(self.cfg.files)
        return {
            "files": len(files),
            "folders": len(self.of_kind(self.cfg.containers)),
            "symbols": len(self.of_kind(self.cfg.details)),
            "pending": sum(1 for f in files if f.props.get(self.cfg.pending_prop) == "pending"),
        }

    def class_like(self, file_ref: str) -> list[Entry]:
        """Top-level details of a file (its classes, usually): details whose parent is the file."""
        return [
            e
            for e in (self.entries.get(c) for c in self.entries[file_ref].children)
            if e and e.kind in self.cfg.details
        ]

    # ---- renderings (always bounded)
    def overview(self, max_chars: int = OVERVIEW_CHARS) -> str:
        st = self.stats()
        lines = [
            f"Project map: {st['files']} files in {st['folders']} folders, {st['symbols']} symbols "
            "(names and signatures from the IDE's code structure; code not read)."
        ]
        areas = []
        for c in self.of_kind(self.cfg.containers):
            direct = [x for x in c.children if (self.entries.get(x) and self.entries[x].kind in self.cfg.files)]
            if direct:
                n_sym = sum(len(self.descendants(x, self.cfg.details)) for x in direct)
                areas.append((len(direct), n_sym, self.path_of(c.ref)))
        areas.sort(key=lambda a: (-a[0], a[2]))
        if areas:
            lines.append("Folders with the most files (files, symbols):")
            lines += [f"- {path}: {nf} files, {ns} symbols" for nf, ns, path in areas[:20]]
        deg = self.in_degree().most_common(8)
        if deg:
            lines.append(
                "Most depended-on files (imported by N files): " + "; ".join(f"{self.path_of(r)} ({n})" for r, n in deg)
            )
        entries = self._entry_points()
        if entries:
            lines.append("Entry points: " + "; ".join(entries[:6]))
        return _clip("\n".join(lines), max_chars)

    def _entry_points(self) -> list[str]:
        names = set(self.cfg.entry_symbols)
        out = []
        for d in self.of_kind(self.cfg.details):
            if d.label in names and d.parent in self.entries:
                owner = d.parent
                while owner in self.entries and self.entries[owner].kind not in self.cfg.files:
                    owner = self.entries[owner].parent or ""
                if owner in self.entries:
                    out.append(self.path_of(owner))
        return sorted(set(out))

    def describe(self, ref: str | None = None, max_chars: int = CODE_MAP_CHARS) -> str:
        ref = ref or self.root
        entry = self.entries.get(ref)
        if entry is None:
            return f"{ref} is not in the map (not mapped, or hidden because it is sensitive)."
        if entry.kind in self.cfg.files:
            return _clip(self._describe_file(entry), max_chars)
        lines = [f"{self.path_of(ref) or entry.label} ({entry.kind})"]
        folders = [
            self.entries[c]
            for c in entry.children
            if self.entries.get(c) and self.entries[c].kind in self.cfg.containers
        ]
        files = [
            self.entries[c] for c in entry.children if self.entries.get(c) and self.entries[c].kind in self.cfg.files
        ]
        for f in sorted(folders, key=lambda x: x.label):
            n = len(self.descendants(f.ref, self.cfg.files))
            lines.append(f"folder {f.label}/ ({n} files)  ref: {f.ref}")
        for f in sorted(files, key=lambda x: x.label):
            classes = self.class_like(f.ref)
            names = ", ".join(
                f"{c.label}" + (f" [{c.props.get('type')}]" if c.props.get("type") else "") for c in classes[:4]
            )
            n_dep = len(f.props.get(self.cfg.depends_prop, []))
            n_in = self.in_degree().get(f.ref, 0)
            lines.append(
                f"file {f.label} ({f.props.get('size_bytes', '?')} bytes): {names or 'no symbols'}; imports {n_dep}, imported by {n_in}  ref: {f.ref}"
            )
        return _clip("\n".join(lines), max_chars)

    def _describe_file(self, f: Entry) -> str:
        lines = [f"{self.path_of(f.ref)} ({f.props.get('language', '?')}, {f.props.get('size_bytes', '?')} bytes)"]
        if f.props.get(self.cfg.pending_prop) == "pending":
            lines.append("(symbols not read yet)")
        for s in self.descendants(f.ref, self.cfg.details)[:120]:
            lines.append(
                f"  line {s.props.get('line', '?')}: [{s.props.get('type', '?')}] {s.props.get('signature') or s.label}"
            )
        deps = [self.path_of(d) for d in f.props.get(self.cfg.depends_prop, []) if d in self.entries]
        if deps:
            lines.append("imports (project files): " + ", ".join(deps[:25]))
        users = [self.path_of(r) for r in self.imported_by(f.ref)]
        if users:
            lines.append(f"imported by {len(users)} files: " + ", ".join(users[:15]))
        return "\n".join(lines)

    def study_plan(self, limit: int = PLAN_LIMIT) -> list[dict[str, Any]]:
        cfg = self.cfg
        scored: list[tuple[float, Entry, list[str]]] = []
        entry_files = set(self._entry_points())
        deg = self.in_degree()
        for f in self.of_kind(cfg.files):
            path = self.path_of(f.ref)
            if _match(path, f.label, cfg.skip_globs):
                continue
            why, score = [], 0.0
            if _match(path, f.label, cfg.priority_globs):
                why.append("matches the profile's priority names")
                score += 10
            if path in entry_files:
                why.append("has an entry point")
                score += 8
            if deg.get(f.ref):
                why.append(f"imported by {deg[f.ref]} files")
                score += min(deg[f.ref], 20)
            if self.descendants(f.ref, cfg.details):
                score += 1
            if int(f.props.get("size_bytes", 0) or 0) > 200_000:
                score -= 5
            if score > 0:
                scored.append((score, f, why))
        scored.sort(key=lambda t: (-t[0], self.path_of(t[1].ref)))
        # One per folder first, so the plan covers the project instead of one corner of it.
        plan, seen_parents, rest = [], set(), []
        for score, f, why in scored:
            (rest if f.parent in seen_parents else plan).append((score, f, why))
            seen_parents.add(f.parent)
        plan = (plan + rest)[:limit]
        return [
            {
                "ref": f.ref,
                "path": self.path_of(f.ref),
                "why": why or ["central to the structure"],
                "size_bytes": f.props.get("size_bytes"),
            }
            for _s, f, why in plan
        ]


# ------------------------------------------------------------------------------------------------ explorer
@dataclass
class BriefItem:
    topic: str
    summary: str
    files: list[dict[str, Any]]  # {"ref", "read": bool}
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


class Explorer:
    def __init__(self, session: Session) -> None:
        self.s = session
        self.cfg: ExploreConfig | None = None
        self.phase = "none"
        self.note = ""
        self.map: CodeMap | None = None
        self.root_ref: str | None = None
        self.brief: list[BriefItem] = []
        self.inspected: Counter[str] = Counter()
        self.studied_at: str | None = None
        self.plan: list[dict[str, Any]] = []
        self._refusals = 0
        self._task: asyncio.Task | None = None
        self._discover_task: asyncio.Task | None = None
        self._last_publish = 0.0

    # ---------------------------------------------------------------------------------------- lifecycle
    def reset(self, profile: Profile | None) -> None:
        for t in (self._task, self._discover_task):
            if t is not None and not t.done():
                t.cancel()
        self.cfg = ExploreConfig.from_profile(profile)
        self.phase = "offer" if self.cfg else "none"
        self.note = ""
        self.map = None
        self.root_ref = None
        self.brief = []
        self.inspected = Counter()
        self.studied_at = None
        if self.cfg:
            self._discover_task = asyncio.create_task(self._discover())
        asyncio.create_task(self.publish())

    async def _discover(self) -> None:
        """Find the project entity (to key the stored brief) and reuse an earlier study if there is one."""
        cfg = self.cfg
        for _ in range(6):
            try:
                obs = await self.s.observe(Scope(level="summary"))
                root = (
                    next((e for e in obs.entities if e.kind == cfg.root_kind and e.parent is None), None)
                    if cfg
                    else None
                )
                if root is not None:
                    self.root_ref = root.ref
                    break
            except WyspError:
                pass
            await asyncio.sleep(5)
        if self.root_ref and self.phase == "offer" and self._load_brief():
            self.phase = "ready"
            self.note = f"Studied before ({self.studied_at}). The code may have changed since."
            await self.publish()

    async def start(self) -> None:
        if self.cfg is None or self.phase in ("mapping", "studying"):
            return
        if self.s.conn is None:
            self.phase, self.note = (
                "failed",
                "The application is not connected: open it with the Wysp plugin, then try again.",
            )
            await self.publish()
            return
        self.phase, self.note = "mapping", ""
        self.brief, self.inspected, self.studied_at = [], Counter(), None
        self.plan, self._refusals = [], 0
        await self.publish()
        self._task = asyncio.create_task(self._run(), name="wysp-explore")

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        if self.phase in ("mapping", "studying"):
            self.phase = "ready" if self.map is not None and self.brief else "stopped"
            self.note = "Stopped by the user."
            self._save_brief()
        elif self.phase == "offer":
            self.phase = "declined"
        await self.publish()

    async def decline(self) -> None:
        if self.phase == "offer":
            self.phase = "declined"
            await self.publish()

    async def _run(self) -> None:
        try:
            if not await self._map():
                return
            await self._begin_study()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("exploration failed")
            self.phase, self.note = "failed", f"Exploration failed: {type(exc).__name__}"
            await self.publish()

    # --------------------------------------------------------------------------------------------- map
    async def _map(self) -> bool:
        cfg, s = self.cfg, self.s
        assert cfg is not None
        if self.root_ref is None:
            await self._discover()
        if self.root_ref is None:
            self.phase, self.note = "failed", "Could not find the project in the application."
            await self.publish()
            return False
        cmap = CodeMap(cfg, self.root_ref)
        self.map = cmap
        queue: deque[str] = deque([self.root_ref])
        asked: Counter[str] = Counter()
        calls = failures = waits = 0
        t0 = time.monotonic()
        stopped_early = ""
        while queue:
            if calls >= MAX_CALLS or time.monotonic() - t0 > MAX_SECONDS or len(cmap.entries) >= MAX_ENTRIES:
                stopped_early = "budget reached"
                break
            ref = queue.popleft()
            asked[ref] += 1
            try:
                obs = await s.observe(Scope(level="full", root=ref))
            except WyspError as exc:
                failures += 1
                if failures > MAX_FAILURES:
                    self.phase, self.note = "failed", f"The application kept failing to answer ({exc.message[:80]})."
                    await self.publish()
                    return False
                if asked[ref] < 3:
                    queue.append(ref)
                await asyncio.sleep(2)
                continue
            calls += 1
            busy = self._busy(obs)
            cmap.ingest(obs)
            for e in obs.entities:
                if e.props.get("sensitive") is True:
                    continue
                if e.kind in cfg.containers and e.parent == ref and e.ref not in asked:
                    queue.append(e.ref)
                elif (
                    e.kind in cfg.files
                    and e.props.get(cfg.pending_prop) == "pending"
                    and e.ref != ref
                    and e.ref not in asked
                ):
                    queue.append(e.ref)
            if (
                busy
                and ref in cmap.entries
                and cmap.entries[ref].kind in cfg.files
                and cmap.entries[ref].props.get(cfg.pending_prop) == "pending"
            ):
                waits += 1  # the application is still indexing: wait and ask for this file again
                if waits <= BUSY_MAX_WAITS:
                    await asyncio.sleep(BUSY_WAIT_S)
                    asked[ref] = 0
                    queue.append(ref)
            if time.monotonic() - self._last_publish > PROGRESS_EVERY_S:
                await self.publish()
        if calls == 0:  # nothing was ever read: say so instead of studying an empty project
            self.map = None
            self.phase, self.note = (
                "failed",
                "The application did not answer, so nothing was mapped. Is it still open and connected?",
            )
            await self.publish()
            return False
        st = cmap.stats()
        s.tm.emit(
            "explore.map",
            calls=calls,
            failures=failures,
            ms=round((time.monotonic() - t0) * 1000, 1),
            stopped_early=bool(stopped_early),
            **st,
        )
        self.note = f"Mapped {st['files']} files, {st['symbols']} symbols." + (
            f" Stopped early: {stopped_early}." if stopped_early else ""
        )
        return True

    def _busy(self, obs: Observation) -> bool:
        cfg = self.cfg
        if cfg is None or not cfg.busy_prop:
            return False
        return any(e.kind == cfg.root_kind and e.props.get(cfg.busy_prop) is True for e in obs.entities)

    # ------------------------------------------------------------------------------------------ study
    async def _begin_study(self) -> None:
        s = self.s
        plan = self.map.study_plan() if self.map else []
        self.plan = plan
        if s.external and s.agent_seen_at is not None:
            self.phase = "studying"
            s.inbox.put("study", plan_size=len(plan), instructions=STUDY_TASK)
            s.tm.emit("explore.study_requested", plan=len(plan))
            self.note += " Studying the main files now."
        else:
            self.phase = "ready"
            self.note += " Ask me about the code: I can read any part of the map."
            self._save_brief()
        await self.publish()

    def note_inspected(self, params: dict[str, Any], scheme: str) -> None:
        """A read-only action targeted these refs: they count as read."""
        changed = False
        for v in params.values():
            if isinstance(v, str) and v.startswith(f"{scheme}://"):
                self.inspected[v.split("#", 1)[0]] += 1
                changed = True
        if changed and self.phase == "studying" and time.monotonic() - self._last_publish > PROGRESS_EVERY_S:
            asyncio.create_task(self.publish())

    async def _read_one(self, ref: str) -> str:
        """The text of one file through the adapter's read-only action (audited like any other read)."""
        from ..orchestrator.pipeline import _do_action, validate_params

        cfg, s = self.cfg, self.s
        conn = s.conn
        if cfg is None or conn is None:
            return "(not connected)"
        specs = {a.id: a for a in await conn.get_actions()}
        spec = specs.get(cfg.read_action)
        if spec is None or spec.risk != "read_only":
            return f"(the application has no read-only action '{cfg.read_action}')"
        params = {**dict(cfg.read_params), cfg.read_target_param: ref}
        if validate_params(spec, params):
            return "(the read action refused these parameters)"
        empty = Observation(observation_id="study", state_version=0, captured_at=datetime.now(UTC))
        out = await _do_action(s, conn, spec, params, "study", empty)
        return (
            str(out.get("output", ""))
            if out.get("ok")
            else f"(could not read: {out.get('error') or out.get('message')})"
        )

    async def study_read(self, offset: int = 0, limit: int = STUDY_DEFAULT_FILES) -> dict[str, Any]:
        """Read the planned files in one call, so the study does not cost one model round trip per file."""
        if self.map is None or self.cfg is None or self.phase not in ("studying", "ready") or not self.cfg.read_action:
            return {"ok": False, "error": "no study in progress"}
        plan = self.plan or self.map.study_plan()
        self.plan = plan
        try:
            offset, limit = max(0, int(offset)), max(1, min(int(limit), PLAN_LIMIT))
        except (TypeError, ValueError):
            return {"ok": False, "error": "offset and limit must be numbers"}
        batch = plan[offset : offset + limit]
        per_file = max(800, min(STUDY_PER_FILE_CHARS, STUDY_TOTAL_CHARS // max(1, len(batch))))
        sem = asyncio.Semaphore(STUDY_CONCURRENCY)

        async def one(item: dict[str, Any]) -> dict[str, Any]:
            async with sem:
                try:
                    text = await self._read_one(item["ref"])
                except WyspError as exc:
                    text = f"(could not read: {exc.message})"
            return {"ref": item["ref"], "path": item["path"], "text": text[:per_file], "cut": len(text) > per_file}

        files = await asyncio.gather(*(one(i) for i in batch))
        nxt = offset + len(batch)
        self.s.tm.emit("explore.study_read", files=len(files), offset=offset, chars=sum(len(f["text"]) for f in files))
        await self.publish()
        return {
            "ok": True,
            "files": files,
            "offset": offset,
            "next_offset": nxt if nxt < len(plan) else None,
            "plan_size": len(plan),
            "note": "Each text is the start of the file (numbered lines). `cut` means more exists: read it with the read action if it matters.",
        }

    def plan_coverage(self) -> tuple[int, int]:
        read = {r for r in self.files_read()}
        return sum(1 for i in self.plan if i["ref"] in read), len(self.plan)

    def files_read(self) -> list[str]:
        if self.map is None:
            return []
        return [r for r in self.inspected if r in self.map.entries and self.map.entries[r].kind in self.map.cfg.files]

    def record(self, topic: str, summary: str, files: list[str]) -> dict[str, Any]:
        if self.phase not in ("studying", "ready"):
            return {"ok": False, "error": "no study in progress: the user has not started one"}
        topic, summary = _one_line(topic, TOPIC_CHARS), " ".join(str(summary).split())[:SUMMARY_CHARS]
        if not topic or not summary:
            return {"ok": False, "error": "topic and summary are required"}
        items = [
            {"ref": str(f).split("#", 1)[0], "read": str(f).split("#", 1)[0] in self.inspected}
            for f in files[:MAX_FILES_PER_ENTRY]
        ]
        self.brief.append(BriefItem(topic, summary, items))
        del self.brief[: max(0, len(self.brief) - BRIEF_MAX_ITEMS)]
        unread = [i["ref"] for i in items if not i["read"]]
        asyncio.create_task(self.publish())
        return {
            "ok": True,
            "recorded": topic,
            "files_read": [i["ref"] for i in items if i["read"]],
            "not_read": unread,
            "note": "Files you did not read with a read action are marked as not read in your notes." if unread else "",
        }

    async def finish(self, overview: str = "") -> dict[str, Any]:
        if self.phase != "studying":
            return {"ok": False, "error": "no study in progress"}
        done, total = self.plan_coverage()
        if total and done < MIN_PLAN_COVERAGE * total and self._refusals < MAX_FINISH_REFUSALS:
            self._refusals += 1
            return {
                "ok": False,
                "error": f"you read {done} of the {total} planned files. Call study_read (offset {done}) to read the rest, "
                "then record_understanding, then finish_study.",
            }
        if overview.strip():
            self.record("Overview", overview, [])
        self.phase = "ready"
        self.studied_at = datetime.now(UTC).isoformat(timespec="seconds")
        self.note = f"Studied {len(self.files_read())} files."
        self._save_brief()
        self.s.tm.emit("explore.study_done", briefs=len(self.brief), files_read=len(self.files_read()))
        await self.publish()
        return {"ok": True, "briefs": len(self.brief), "files_read": len(self.files_read())}

    # --------------------------------------------------------------------------------------- storage
    def _path(self):
        key = hashlib.sha1(f"{self.s.active_adapter_id or ''}|{self.root_ref}".encode()).hexdigest()[:16]
        return wysp_home() / "projects" / f"{key}.json"

    def _save_brief(self) -> None:
        if not self.root_ref or not self.brief:
            return
        try:
            p = self._path()
            p.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "project": self.root_ref,
                "saved_at": self.studied_at or datetime.now(UTC).isoformat(timespec="seconds"),
                "brief": [{"topic": b.topic, "summary": b.summary, "files": b.files, "at": b.at} for b in self.brief],
            }
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.warning("could not save the study brief: %s", exc)

    def _load_brief(self) -> bool:
        try:
            data = json.loads(self._path().read_text(encoding="utf-8"))
            self.brief = [
                BriefItem(b["topic"], b["summary"], list(b.get("files", [])), b.get("at", "")) for b in data["brief"]
            ]
            self.studied_at = data.get("saved_at")
            return bool(self.brief)
        except (OSError, ValueError, KeyError, TypeError):
            return False

    # --------------------------------------------------------------------------------------- publishing
    def state_message(self) -> dict[str, Any]:
        st = self.map.stats() if self.map else {"files": 0, "folders": 0, "symbols": 0, "pending": 0}
        return {
            "type": "explore.state",
            "phase": self.phase,
            "note": self.note,
            "files": st["files"],
            "folders": st["folders"],
            "symbols": st["symbols"],
            "read": len(self.files_read()),
            "briefs": len(self.brief),
            "studied_at": self.studied_at,
        }

    async def publish(self) -> None:
        self._last_publish = time.monotonic()
        await self.s.broadcast(self.state_message())

    # ---------------------------------------------------------------------------------------- prompt
    def has_content(self) -> bool:
        return self.phase in ("mapping", "studying", "ready", "stopped") and (self.map is not None or bool(self.brief))

    def render(self, max_chars: int = PROMPT_CHARS) -> str:
        parts = ["# What you know about the project (from the IDE's code structure and from what you read)"]
        if self.map is not None:
            parts.append(self.map.overview())
        read = self.files_read()
        if self.map is not None:
            parts.append(
                f"Files you have actually read in this session: {len(read)} of {self.map.stats()['files']}."
                + (" " + "; ".join(self.map.path_of(r) for r in read[:25]) if read else "")
            )
        if self.brief:
            lines = ["Your study notes (inferred from the files listed; 'unread' means you did not read it):"]
            for b in self.brief[-12:]:
                files = ", ".join(
                    (self.map.path_of(f["ref"]) if self.map and f["ref"] in self.map.entries else f["ref"])
                    + ("" if f.get("read") else " (unread)")
                    for f in b.files[:6]
                )
                lines.append(f"- {b.topic}: {b.summary}" + (f" [{files}]" if files else ""))
            parts.append("\n".join(lines))
        parts.append(
            "Speak with certainty about what is in the map, your notes or what you read. For anything else say plainly "
            "that you have not read it, and offer to read it."
        )
        return _clip("\n".join(parts), max_chars)
