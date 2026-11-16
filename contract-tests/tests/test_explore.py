"""Project exploration [core-orchestrator 20]: the user is asked first, the map is bounded and honest (CORE-P15),
the study brief never claims an unread file as read (CORE-P16)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from wysp_adapter_sdk import ActionOutcome
from wysp_core.contract import Observation
from wysp_core.orchestrator.context import build_system_prompt
from wysp_core.orchestrator.tools import ToolBox
from wysp_core.session import explore as explore_mod
from wysp_core.session.explore import CodeMap, ExploreConfig, Explorer

CFG = ExploreConfig(
    root_kind="project",
    containers=frozenset({"dir"}),
    files=frozenset({"file"}),
    details=frozenset({"symbol"}),
    entry_symbols=("main",),
    priority_globs=("README*", "*Main*"),
    skip_globs=("*/test/*",),
    read_action="read_code",
    read_params=(("from_line", 1), ("to_line", 90)),
)
ROOT = "mock://project/demo"
SECRET = "TOPSECRETNAME"


def _ref(path: str) -> str:
    return f"mock://{path}"


# A small project: README, src/{Main,Service,Repo,Extra}.java, test/T.java, a sensitive .env.
NODES: dict[str, dict[str, Any]] = {
    ROOT: {"kind": "project", "label": "demo", "parent": None, "props": {}},
    _ref("README.md"): {"kind": "file", "label": "README.md", "parent": ROOT, "props": {"size_bytes": 100}},
    _ref("src"): {"kind": "dir", "label": "src", "parent": ROOT, "props": {}},
    _ref("src/Main.java"): {
        "kind": "file",
        "label": "Main.java",
        "parent": _ref("src"),
        "props": {"size_bytes": 300, "depends_on": [_ref("src/Service.java")]},
    },
    _ref("src/Service.java"): {
        "kind": "file",
        "label": "Service.java",
        "parent": _ref("src"),
        "props": {"size_bytes": 900, "depends_on": [_ref("src/Repo.java")]},
    },
    _ref("src/Repo.java"): {"kind": "file", "label": "Repo.java", "parent": _ref("src"), "props": {"size_bytes": 500}},
    _ref("src/Extra.java"): {"kind": "file", "label": "Extra.java", "parent": _ref("src"), "props": {"size_bytes": 50}},
    _ref("src/.env"): {"kind": "file", "label": SECRET, "parent": _ref("src"), "props": {"sensitive": True}},
    _ref("test"): {"kind": "dir", "label": "test", "parent": ROOT, "props": {}},
    _ref("test/T.java"): {"kind": "file", "label": "T.java", "parent": _ref("test"), "props": {"size_bytes": 80}},
}
SYMBOLS = {
    _ref("src/Main.java"): [("Main", "class", "class Main"), ("main", "function", "void main(String[] args)")],
    _ref("src/Service.java"): [("Service", "class", "class Service"), ("run", "function", "void run()")],
    _ref("src/Repo.java"): [("Repo", "class", "class Repo")],
    _ref("src/Extra.java"): [("Extra", "class", "class Extra")],
    _ref("test/T.java"): [("T", "class", "class T")],
}


class FakeProject:
    """Plays the adapter's `observe {level: full, root}`: a folder lists its children, reading symbols for only
    the first `per_call` files (the rest are `pending`), a file returns its symbols."""

    def __init__(self, per_call: int = 2) -> None:
        self.per_call = per_call
        self.calls: list[str | None] = []

    def children(self, ref: str) -> list[str]:
        return [r for r, n in NODES.items() if n["parent"] == ref]

    def chain(self, ref: str) -> list[str]:
        out = []
        cur: str | None = ref
        while cur is not None:
            out.append(cur)
            cur = NODES[cur]["parent"]
        return list(reversed(out))

    def entity(self, ref: str, symbols: str | None = None) -> dict[str, Any]:
        n = NODES[ref]
        props = dict(n["props"])
        if n["kind"] == "file" and not props.get("sensitive"):
            props["symbols"] = symbols or "pending"
            if symbols != "done":
                props.pop("depends_on", None)
        return {"ref": ref, "kind": n["kind"], "label": n["label"], "parent": n["parent"], "props": props}

    def symbol_entities(self, ref: str) -> list[dict[str, Any]]:
        return [
            {
                "ref": f"{ref}#{name}",
                "kind": "symbol",
                "label": name,
                "parent": ref,
                "props": {"type": t, "line": i + 1, "signature": sig},
            }
            for i, (name, t, sig) in enumerate(SYMBOLS.get(ref, []))
        ]

    async def observe(self, scope: Any = None) -> Observation:
        root = getattr(scope, "root", None)
        self.calls.append(root)
        ents: list[dict[str, Any]] = []
        if root is None:
            ents = [self.entity(ROOT)]
        else:
            ents = [self.entity(r) for r in self.chain(root)[:-1]] if NODES[root]["kind"] != "project" else []
            if NODES[root]["kind"] == "file":
                ents.append(self.entity(root, "done"))
                ents += self.symbol_entities(root)
            else:
                ents.append(self.entity(root))
                files = [r for r in self.children(root) if NODES[r]["kind"] == "file"]
                done = 0
                for r in self.children(root):
                    if NODES[r]["kind"] == "file" and not NODES[r]["props"].get("sensitive") and done < self.per_call:
                        ents.append(self.entity(r, "done"))
                        ents += self.symbol_entities(r)
                        done += 1
                    else:
                        ents.append(self.entity(r))
                _ = files
        return Observation.model_validate(
            {
                "observation_id": f"o{len(self.calls)}",
                "state_version": 1,
                "captured_at": "2026-11-15T00:00:00Z",
                "entities": ents,
            }
        )


async def _until(pred, timeout: float = 6.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached in time")


def _arm(s, project: FakeProject) -> Explorer:
    ex = s.session.explorer
    ex.cfg, ex.phase, ex.root_ref = CFG, "offer", ROOT
    s.session.conn.observe = project.observe
    return ex


async def _add_read_action(s) -> None:
    """The application's read-only read action, as the IDE has one (the Core reads files through it)."""
    spec = {
        "id": "read_code",
        "title": {"en": "Read code"},
        "description": "Numbered lines of a file.",
        "params_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "from_line": {"type": "integer"},
                "to_line": {"type": "integer"},
            },
            "required": ["target"],
            "additionalProperties": False,
        },
        "risk": "read_only",
        "reversible": False,
        "preconditions": [],
        "postconditions": [],
        "guide": {"ui_path": []},
    }
    s.mock.registry.register(
        spec, lambda params, dry: ActionOutcome(message=f"{params['target']}\n   1| " + "x" * 6000)
    )
    await s.session.conn.get_actions(refresh=True)


# ------------------------------------------------------------------------------------------- consent
async def test_nothing_is_read_before_the_user_agrees(make_stack):
    s = await make_stack([])
    project = FakeProject()
    ex = _arm(s, project)
    await ex.publish()
    await s.ui.wait_for(lambda m: m.get("type") == "explore.state" and m["phase"] == "offer")
    await asyncio.sleep(0.3)
    assert project.calls == [] and ex.map is None
    prompt = await build_system_prompt(s.session)
    assert "has not agreed yet" in prompt


async def test_accepting_builds_the_map_and_declining_does_not(make_stack):
    s = await make_stack([])
    project = FakeProject()
    ex = _arm(s, project)
    await s.ui.send(type="explore.start")
    await _until(lambda: ex.phase in ("ready", "studying"))
    cm = ex.map
    assert cm is not None
    st_ = cm.stats()
    assert st_["files"] == 6 and st_["pending"] == 0  # pending files were asked for one by one
    assert st_["symbols"] == 7
    assert _ref("src/.env") not in cm.entries
    # The sensitive file's name appears nowhere the tutor can read.
    for text in (cm.overview(), cm.describe(), cm.describe(_ref("src")), ex.render()):
        assert SECRET not in text
    state = await s.ui.wait_for(lambda m: m.get("type") == "explore.state" and m["phase"] in ("ready", "studying"))
    assert state["files"] == 6

    # A second session where the user says no: nothing is ever read.
    s2_project = FakeProject()
    ex.reset(None)
    ex.cfg, ex.phase = CFG, "offer"
    await s.ui.send(type="explore.stop")
    await _until(lambda: ex.phase == "declined")
    assert s2_project.calls == []


async def test_an_unreachable_application_is_reported_not_studied(make_stack):
    from wysp_core.contract import WyspError

    s = await make_stack([])
    ex = _arm(s, FakeProject())

    async def broken(scope=None):
        raise WyspError(-32016, "timeout")

    s.session.conn.observe = broken
    await ex.start()
    await _until(lambda: ex.phase == "failed", timeout=15)
    assert "nothing was mapped" in ex.note and ex.map is None
    # And with no application at all, it says so at once.
    s.session.registry.remove(s.session.conn)
    ex.phase = "offer"
    await ex.start()
    assert ex.phase == "failed" and "not connected" in ex.note


async def test_map_budget_is_reported(make_stack, monkeypatch):
    monkeypatch.setattr(explore_mod, "MAX_CALLS", 2)
    s = await make_stack([])
    ex = _arm(s, FakeProject())
    await ex.start()
    await _until(lambda: ex.phase in ("ready", "studying", "failed"))
    assert "Stopped early" in ex.note


# ----------------------------------------------------------------------------------------- study phase
async def test_study_task_reaches_the_agent_and_reads_are_tracked(make_stack, tmp_path):
    s = await make_stack([], external=True)
    s.session.agent_seen_at = time.monotonic()  # an agent is connected
    ex = _arm(s, FakeProject())
    await ex.start()
    await _until(lambda: ex.phase == "studying")
    events = s.session.inbox.drain()
    study = next(e for e in events if e["kind"] == "study")
    assert "study_read" in study["instructions"]

    box = ToolBox(s.session)
    plan = (await box.call("get_study_plan", {}))["plan"]
    paths = [p["path"] for p in plan]
    assert "README.md" in paths and "src/Main.java" in paths
    assert "test/T.java" not in paths  # skipped by the profile's globs
    assert plan[0]["path"] in ("README.md", "src/Main.java")

    # A read-only action ran on README and on Service: only those count as read.
    ex.note_inspected({"target": _ref("README.md"), "from_line": 1}, "mock")
    ex.note_inspected({"target": _ref("src/Service.java")}, "mock")
    out = await box.call(
        "record_understanding",
        {
            "topic": "Request flow",
            "summary": "Main calls Service which uses Repo.",
            "files": [_ref("src/Service.java"), _ref("src/Repo.java")],
        },
    )
    assert out["ok"] and out["files_read"] == [_ref("src/Service.java")] and out["not_read"] == [_ref("src/Repo.java")]
    assert "(unread)" in ex.render() and "Request flow" in ex.render()

    for item in plan:  # the rest of the plan was read too (finishing early is refused: see the test below)
        ex.note_inspected({"target": item["ref"]}, "mock")
    done = await box.call("finish_study", {"overview": "A small layered app."})
    assert done["ok"] and ex.phase == "ready" and ex.studied_at

    # The brief is kept per project, and offered again next time.
    again = Explorer(s.session)
    again.cfg, again.root_ref = CFG, ROOT
    assert again._load_brief() and [b.topic for b in again.brief] == ["Request flow", "Overview"]


async def test_the_whole_plan_is_read_in_one_call_and_finishing_early_is_refused(make_stack):
    s = await make_stack([], external=True)
    s.session.agent_seen_at = time.monotonic()
    await _add_read_action(s)
    ex = _arm(s, FakeProject())
    await ex.start()
    await _until(lambda: ex.phase == "studying")
    box = ToolBox(s.session)

    # Not read yet: the agent cannot end the study with nothing read.
    early = await box.call("finish_study", {"overview": "x"})
    assert not early["ok"] and "study_read" in early["error"]

    out = await box.call("study_read", {})
    assert out["ok"] and out["next_offset"] is None
    plan_paths = {p["path"] for p in (await box.call("get_study_plan", {}))["plan"]}
    assert {f["path"] for f in out["files"]} == plan_paths and len(plan_paths) == 5
    assert sum(len(f["text"]) for f in out["files"]) <= explore_mod.STUDY_TOTAL_CHARS
    assert all(len(f["text"]) <= explore_mod.STUDY_PER_FILE_CHARS and f["cut"] for f in out["files"])
    # Reads went through the audited pipeline, so they count as read.
    assert set(ex.files_read()) == {f["ref"] for f in out["files"]}
    assert (
        await box.call(
            "record_understanding", {"topic": "All", "summary": "s", "files": [f["ref"] for f in out["files"]]}
        )
    )["not_read"] == []
    assert (await box.call("finish_study", {}))["ok"] and ex.phase == "ready"


async def test_study_read_pages_through_the_plan(make_stack):
    s = await make_stack([], external=True)
    s.session.agent_seen_at = time.monotonic()
    await _add_read_action(s)
    ex = _arm(s, FakeProject())
    await ex.start()
    await _until(lambda: ex.phase == "studying")
    first = await ToolBox(s.session).call("study_read", {"limit": 2})
    assert len(first["files"]) == 2 and first["next_offset"] == 2
    rest = await ToolBox(s.session).call("study_read", {"offset": 2})
    assert len(rest["files"]) == 3 and rest["next_offset"] is None


async def test_the_agent_cannot_stall_the_study_forever(make_stack):
    s = await make_stack([], external=True)
    s.session.agent_seen_at = time.monotonic()
    ex = _arm(s, FakeProject())
    await ex.start()
    await _until(lambda: ex.phase == "studying")
    box = ToolBox(s.session)
    for _ in range(explore_mod.MAX_FINISH_REFUSALS):
        assert not (await box.call("finish_study", {}))["ok"]
    assert (await box.call("finish_study", {}))["ok"]  # enough: it is not forced to loop


async def test_study_tools_refuse_without_a_study(make_stack):
    s = await make_stack([])
    box = ToolBox(s.session)
    assert not (await box.call("code_map", {}))["ok"]
    assert not (await box.call("get_study_plan", {}))["ok"]
    assert not (await box.call("study_read", {}))["ok"]
    assert not (await box.call("record_understanding", {"topic": "x", "summary": "y"}))["ok"]
    assert not (await box.call("finish_study", {}))["ok"]


async def test_code_map_tool_shows_structure_not_code(make_stack):
    s = await make_stack([])
    ex = _arm(s, FakeProject())
    await ex.start()
    await _until(lambda: ex.phase in ("ready", "studying"))
    box = ToolBox(s.session)
    top = (await box.call("code_map", {}))["map"]
    assert "src" in top and "README.md" in top
    one = (await box.call("code_map", {"ref": _ref("src/Service.java")}))["map"]
    assert "void run()" in one and "imports (project files): src/Repo.java" in one
    assert "imported by 1 files: src/Main.java" in one


# ------------------------------------------------------------------------------------ properties
def _obs(entities: list[dict[str, Any]]) -> Observation:
    return Observation.model_validate(
        {"observation_id": "o", "state_version": 1, "captured_at": "2026-11-15T00:00:00Z", "entities": entities}
    )


@st.composite
def projects(draw):
    n_dirs = draw(st.integers(0, 12))
    n_files = draw(st.integers(0, 60))
    ents = [{"ref": ROOT, "kind": "project", "label": "demo", "props": {}}]
    dirs = [ROOT]
    for i in range(n_dirs):
        parent = draw(st.sampled_from(dirs))
        label = draw(st.text(max_size=120))
        ref = f"mock://d{i}"
        ents.append({"ref": ref, "kind": "dir", "label": label, "parent": parent, "props": {}})
        dirs.append(ref)
    refs = []
    for i in range(n_files):
        parent = draw(st.sampled_from(dirs))
        sensitive = draw(st.booleans())
        ref = f"mock://f{i}"
        refs.append(ref)
        label = (SECRET if sensitive else "") + draw(st.text(max_size=80))
        deps = draw(st.lists(st.sampled_from([*refs, "mock://nowhere"]), max_size=50))
        props: dict[str, Any] = {"size_bytes": draw(st.integers(0, 500_000)), "depends_on": deps}
        if sensitive:
            props["sensitive"] = True
        ents.append({"ref": ref, "kind": "file", "label": label, "parent": parent, "props": props})
        for j in range(draw(st.integers(0, 4))):
            ents.append(
                {
                    "ref": f"{ref}#s{j}",
                    "kind": "symbol",
                    "label": SECRET if sensitive else f"s{j}",
                    "parent": ref,
                    "props": {"type": "function", "line": j, "signature": draw(st.text(max_size=400))},
                }
            )
    return ents


@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(projects())
def test_prop_core_p15_the_map_is_bounded_and_honest(ents):
    """CORE-P15: renderings stay within their bounds, never name a sensitive entity, and show only mapped dependencies."""
    cm = CodeMap(CFG, ROOT)
    cm.ingest(_obs(ents))
    assert len(cm.overview()) <= explore_mod.OVERVIEW_CHARS
    texts = [cm.overview(), cm.describe(), *(cm.describe(e.ref) for e in list(cm.entries.values())[:25])]
    for t in texts:
        assert len(t) <= explore_mod.CODE_MAP_CHARS
        assert SECRET not in t
    for item in cm.study_plan():
        assert item["ref"] in cm.entries and SECRET not in item["path"]
    plan = cm.study_plan()
    assert len(plan) <= explore_mod.PLAN_LIMIT


@settings(max_examples=60, deadline=None)
@given(
    st.sets(st.sampled_from([_ref(f"src/{n}.java") for n in ("Main", "Service", "Repo", "Extra")])),
    st.sets(st.integers(0, 3)),
)
def test_prop_core_p16_a_study_entry_never_claims_an_unread_file(inspected, listed_idx):
    """CORE-P16: a file is `read` only if a read-only action targeted it in this session."""
    names = [_ref(f"src/{n}.java") for n in ("Main", "Service", "Repo", "Extra")]

    class _S:
        tm = None

        async def broadcast(self, _m):
            return None

    ex = Explorer(_S())  # type: ignore[arg-type]
    ex.phase = "studying"
    for r in inspected:
        ex.inspected[r] += 1
    listed = [names[i] for i in sorted(listed_idx)]

    async def run():
        return ex.record("topic", "summary", listed)

    out = asyncio.run(run())
    assert out["ok"]
    assert set(out["files_read"]) == set(listed) & set(inspected)
    assert set(out["not_read"]) == set(listed) - set(inspected)
