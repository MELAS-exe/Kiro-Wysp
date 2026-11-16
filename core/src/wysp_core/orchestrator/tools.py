"""Tools offered to the LLM. There is deliberately no tool that executes an adapter action directly."""

from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING, Any

from ..board import node_id, project
from ..contract import Observation, Scope, WyspError
from ..llm import CancelToken, ToolCall, ToolSpec
from . import pipeline

if TYPE_CHECKING:
    from ..session.session import Session

MAX_OBSERVE_ENTITIES = 80
LAYOUTS = ["stack", "tree", "graph", "sequence"]


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


TOOLS: dict[str, tuple[str | None, ToolSpec]] = {
    # name: (required capability or None, spec)
    "observe": (
        "observe",
        ToolSpec(
            "observe",
            "Look at the application's current state. Returns a compact list of entities (ref, kind, label, key properties).",
            _obj(
                {
                    "level": {
                        "type": "string",
                        "enum": ["summary", "focus", "full"],
                        "description": "How much to return",
                    },
                    "root": {"type": "string", "description": "Optional ref to start from"},
                }
            ),
        ),
    ),
    "show_entities": (
        "observe",
        ToolSpec(
            "show_entities",
            "Put REAL entities of the application on the board. Use refs returned by observe. Replaces the board unless replace=false.",
            _obj(
                {
                    "refs": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 40},
                    "layout": {"type": "string", "enum": LAYOUTS},
                    "focus": {"type": "array", "items": {"type": "string"}, "description": "Refs to emphasise"},
                    "include_children": {"type": "boolean", "description": "Also show the children of each ref"},
                    "replace": {"type": "boolean", "description": "Clear the board first (default true)"},
                },
                ["refs", "layout"],
            ),
        ),
    ),
    "add_concept": (
        None,
        ToolSpec(
            "add_concept",
            "Add non-observed nodes (concepts, examples or steps; provenance 'inferred' or 'illustrative'). "
            "Put ALL of them in `items` in one call; steps are chained in order.",
            _obj(
                {
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 12,
                        "items": _obj(
                            {
                                "label": {"type": "string", "maxLength": 80},
                                "kind": {"type": "string", "enum": ["concept", "example", "step"]},
                                "provenance": {"type": "string", "enum": ["inferred", "illustrative"]},
                                "attach_to": {"type": "string", "description": "Ref or node id"},
                                "key": {"type": "string", "description": "Short id; cues can target c:<key>"},
                            },
                            ["label"],
                        ),
                    },
                    "label": {"type": "string", "maxLength": 80, "description": "Single node (old form)"},
                    "kind": {"type": "string", "enum": ["concept", "example", "step"]},
                    "provenance": {"type": "string", "enum": ["inferred", "illustrative"]},
                    "attach_to": {"type": "string", "description": "Ref or node id to connect to"},
                },
            ),
        ),
    ),
    "annotate": (
        None,
        ToolSpec(
            "annotate",
            "Attach a short note to a node on the board.",
            _obj(
                {
                    "target": {"type": "string", "description": "Ref or node id"},
                    "text": {"type": "string", "maxLength": 160},
                    "provenance": {"type": "string", "enum": ["inferred", "illustrative"]},
                },
                ["target", "text"],
            ),
        ),
    ),
    "narrate": (
        None,
        ToolSpec(
            "narrate",
            "Speak and caption short segments (at most 300 characters each); cues synchronise the board with the "
            "speech. `board` updates the board in the same call: usually this one call is your whole answer.",
            _obj(
                {
                    "board": _obj(
                        {
                            "show": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 40,
                                "description": "Refs of REAL entities to show (as show_entities)",
                            },
                            "layout": {"type": "string", "enum": LAYOUTS},
                            "focus": {"type": "array", "items": {"type": "string"}},
                            "include_children": {"type": "boolean"},
                            "concepts": {
                                "type": "array",
                                "maxItems": 12,
                                "description": "As add_concept items",
                                "items": {"type": "object"},
                            },
                        }
                    ),  # fmt: skip
                    "segments": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "items": _obj(
                            {
                                "text": {"type": "string", "maxLength": 300},
                                "provenance": {"type": "string", "enum": ["observed", "inferred", "illustrative"]},
                                "cues": {
                                    "type": "array",
                                    "items": _obj(
                                        {
                                            "at_word": {"type": "integer", "minimum": 0},
                                            "op": {"type": "string", "enum": ["focus", "highlight"]},
                                            "target": {"type": "string", "description": "Ref or node id"},
                                        },
                                        ["op", "target"],
                                    ),
                                },
                            },
                            ["text"],
                        ),
                    },
                },
                ["segments"],
            ),
        ),
    ),
    "code_map": (
        None,
        ToolSpec(
            "code_map",
            "Read the project map the Core built (only after the user agreed to explore): folders, files, their classes "
            "and signatures, what imports what. No ref: the project root. Give a folder or file ref to look inside it. "
            "Names and signatures only, not code: read code with the application's read action.",
            _obj({"ref": {"type": "string", "description": "Folder, file or project ref from the map"}}),
        ),
    ),
    "get_study_plan": (
        None,
        ToolSpec(
            "get_study_plan",
            "The files to read first when studying the project, in order, with why. Only while a study is in progress.",
            _obj({}),
        ),
    ),
    "study_read": (
        None,
        ToolSpec(
            "study_read",
            "Study phase: read the files the Core picked (see get_study_plan), about 12 per call. Returns each file's "
            "text (numbered lines, the start of the file) and `next_offset` when more of the plan remains: call again "
            "with that offset until it is null, and never repeat a call. Use this instead of reading files one by one.",
            _obj(
                {
                    "offset": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Where in the plan to start (default 0)",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 30,
                        "description": "How many files (default 12)",
                    },
                }
            ),
        ),
    ),
    "record_understanding": (
        None,
        ToolSpec(
            "record_understanding",
            "Write down what you learned from files you read (study phase). Only things you read; list the refs. "
            "Files you did not read with a read action are marked unread.",
            _obj(
                {
                    "topic": {"type": "string", "maxLength": 80},
                    "summary": {"type": "string", "maxLength": 700},
                    "files": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
                },
                ["topic", "summary"],
            ),
        ),
    ),
    "finish_study": (
        None,
        ToolSpec(
            "finish_study",
            "End the study phase. `overview`: a short summary of how the project is organised, from what you read.",
            _obj({"overview": {"type": "string", "maxLength": 700}}),
        ),
    ),
    "highlight": (
        "highlight",
        ToolSpec(
            "highlight",
            "Point at something inside the application itself: an entity ref from the observation, or an "
            "interface element ref listed in the application description. It STAYS highlighted until the user "
            "interacts with it, you highlight something else, or you call clear_highlight.",
            _obj({"ref": {"type": "string"}}, ["ref"]),
        ),
    ),
    "clear_highlight": (
        "highlight",
        ToolSpec(
            "clear_highlight",
            "Take down the highlight you left in the application: the user found it, the step is done, or the "
            "conversation moved on. Does nothing when nothing is highlighted.",
            _obj({}, []),
        ),
    ),
    "propose_action": (
        "actions",
        ToolSpec(
            "propose_action",
            "Propose an action from the application's action catalog. mode 'guide': the user does it and Wysp verifies. "
            "mode 'do': Wysp does it after the user approves and then verifies. This never runs anything by itself.",
            _obj(
                {
                    "action_id": {"type": "string"},
                    "params": {"type": "object"},
                    "rationale": {"type": "string", "maxLength": 300},
                    "mode": {"type": "string", "enum": ["guide", "do"]},
                },
                ["action_id", "params", "mode"],
            ),
        ),
    ),
    "learner_status": (
        None,
        ToolSpec(
            "learner_status",
            "The learner's mastery per skill (with how deep to teach), the lessons of this application, the "
            "recommended next lesson and the exercise in progress.",
            _obj({}),
        ),
    ),
    "lesson": (
        None,
        ToolSpec(
            "lesson",
            "Run an authored lesson. action=start (with lesson_id) returns step 1; next/skip/repeat/stop move "
            "through it. Each step says what to explain, show, guide or check: perform it with your other tools, "
            "then call next. Prefer the recommended lesson from learner_status.",
            _obj(
                {
                    "action": {"type": "string", "enum": ["start", "next", "skip", "repeat", "stop"]},
                    "lesson_id": {"type": "string"},
                },
                ["action"],
            ),
        ),
    ),
    "start_exercise": (
        "observe",
        ToolSpec(
            "start_exercise",
            "Offer one authored exercise (by id, from learner_status). Wysp then verifies it in the application when "
            "the learner changes something: you never judge success yourself. It refuses exercises that are already "
            "satisfied or whose target is not selected.",
            _obj({"exercise_id": {"type": "string"}}, ["exercise_id"]),
        ),
    ),
    "exercise_hint": (
        None,
        ToolSpec(
            "exercise_hint",
            "Give the next authored hint of the exercise in progress (hints cost a little mastery).",
            _obj({}),
        ),
    ),
    "check_exercise": (
        "observe",
        ToolSpec(
            "check_exercise",
            "The learner says they are done: verify the exercise now on a fresh observation.",
            _obj({}),
        ),
    ),
    "declare_done": (
        None,
        ToolSpec(
            "declare_done",
            "Only for an exercise the application cannot verify: record that the learner says it is done "
            "(weak evidence, labelled declared). Refused for verifiable exercises.",
            _obj({}),
        ),
    ),
    "lookup_concept": (
        None,
        ToolSpec(
            "lookup_concept",
            "Look up a term in the application's glossary (from its profile).",
            _obj({"term": {"type": "string"}}, ["term"]),
        ),
    ),
    "ask_clarification": (
        None,
        ToolSpec(
            "ask_clarification",
            "Ask the user one short question, with up to four suggested answers. Ends your turn.",
            _obj(
                {
                    "question": {"type": "string", "maxLength": 200},
                    "options": {"type": "array", "items": {"type": "string", "maxLength": 60}, "maxItems": 4},
                },
                ["question"],
            ),
        ),
    ),
}


def tool_specs(capabilities: set[str]) -> list[ToolSpec]:
    """Only offer tools whose required adapter capability is declared (property CORE-P10)."""
    return [spec for cap, spec in TOOLS.values() if cap is None or cap in capabilities]


def summarize_observation(obs: Observation, limit: int = MAX_OBSERVE_ENTITIES) -> dict[str, Any]:
    entities = []
    for e in obs.entities[:limit]:
        props = {k: v for k, v in e.props.items() if not isinstance(v, (dict, list)) and v is not None}
        entities.append(
            {"ref": e.ref, "kind": e.kind, "label": e.label, "parent": e.parent, "props": dict(list(props.items())[:6])}
        )
    counts: dict[str, int] = {}
    for e in obs.entities:
        counts[e.kind] = counts.get(e.kind, 0) + 1
    return {
        "ok": True,
        "focus": obs.focus,
        "counts": counts,
        "entities": entities,
        "truncated": len(obs.entities) > limit or obs.truncated,
    }


class ToolBox:
    def __init__(self, session: Session, cancel: CancelToken | None = None) -> None:
        self.s = session
        self.cancel = cancel  # the running turn's token: once set, nothing more is published for that turn (CORE-P7)
        self.turn_ended = False  # set by ask_clarification
        self.narrated = False

    def specs(self) -> list[ToolSpec]:
        conn = self.s.conn
        caps = set(conn.manifest.capabilities) if conn else set()
        return tool_specs(caps)

    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        name = normalize_tool_name(name)
        entry = TOOLS.get(name)
        if entry is None:
            return {"ok": False, "error": f"unknown tool '{name}'"}
        cap, _ = entry
        conn = self.s.conn
        if cap and (conn is None or not conn.manifest.has(cap)):
            return {
                "ok": False,
                "error": "this application does not support that" if conn else "no application is connected",
            }
        handler = getattr(self, f"_t_{name}")
        with self.s.tm.span("tool.call", full={"args": args}, tool=name) as extra:
            try:
                out = await handler(args)
            except WyspError as exc:
                out = {"ok": False, "error": exc.message}
            except (KeyError, TypeError, ValueError) as exc:
                out = {"ok": False, "error": f"bad arguments: {exc}"}
            extra["ok"] = bool(out.get("ok", True))
            if not extra["ok"]:
                extra["error"] = str(out.get("error"))[:200]
            extra["_full"] = {"result": out}
        return out

    # ---------------------------------------------------------------------- handlers
    async def _t_observe(self, a: dict[str, Any]) -> dict[str, Any]:
        await self.s.activity("Looking at the application…")
        level = a.get("level", "focus")
        root = a.get("root")
        obs = await self.s.observe(Scope(level=level, root=root) if root else Scope(level=level))
        if root and root not in {e.ref for e in obs.entities}:
            return {"ok": False, "error": f"no entity has the ref {root!r}; use a ref listed in <app_data>"}
        return summarize_observation(obs)

    async def _t_show_entities(self, a: dict[str, Any]) -> dict[str, Any]:
        refs = [str(r) for r in a["refs"]]
        if refs and all(r.startswith(("c:", "n:")) for r in refs):
            return {"ok": False, "error": "these are board node ids, already on the board; show_entities takes refs"}
        layout = a.get("layout", "graph")
        if layout not in LAYOUTS:
            layout = "graph"
        include_children = bool(a.get("include_children", False))
        obs = await self.s.observe(Scope(level="full"))
        ops, missing = project(obs, refs, include_children, self.s.board_props())
        if not ops:
            return {"ok": False, "error": "none of those refs exist in the application", "missing": missing}
        node_ids = [op["node"]["id"] for op in ops if op["op"] == "add_node"]
        focus_refs = [str(r) for r in a.get("focus", [])]
        focus_ids = [node_id(r) for r in focus_refs if node_id(r) in node_ids]
        prefix: list[dict[str, Any]] = [{"op": "clear"}] if a.get("replace", True) else []
        result = await self.s.apply_board(
            prefix + ops + [{"op": "set_layout", "layout": layout}, {"op": "set_focus", "ids": focus_ids}]
        )
        if not result["ok"]:
            return result
        self.s.board_spec = {"refs": refs, "include_children": include_children, "node_ids": node_ids}
        out: dict[str, Any] = {"ok": True, "shown": len(node_ids), "layout": layout}
        if missing:
            out["missing"] = missing
        return out

    async def _t_add_concept(self, a: dict[str, Any]) -> dict[str, Any]:
        items = a.get("items") or ([a] if a.get("label") else [])
        if not items:
            return {"ok": False, "error": "give the nodes in `items`"}
        ops: list[dict[str, Any]] = []
        ids: list[str] = []
        previous_step: str | None = None
        for item in items[:12]:
            provenance = item.get("provenance", a.get("provenance"))
            if provenance not in ("inferred", "illustrative"):
                provenance = "inferred"  # the LLM can never create observed facts
            kind = item.get("kind", a.get("kind", "concept"))
            key = str(item.get("key", ""))
            nid = (
                f"c:{key}"
                if _KEY_RE.fullmatch(key) and not self.s.board.node(f"c:{key}")
                else f"c:{uuid.uuid4().hex[:6]}"
            )
            ops.append(
                {
                    "op": "add_node",
                    "node": {
                        "id": nid,
                        "ref": None,
                        "kind": kind,
                        "label": str(item["label"])[:80],
                        "provenance": provenance,
                        "confidence": 0.8 if provenance == "inferred" else 1.0,
                        "order": len(ids) if kind == "step" else None,
                    },
                }
            )
            # Steps follow each other; anything else (and the first step) hangs off what it explains.
            attach = item.get("attach_to", a.get("attach_to"))
            source = previous_step if kind == "step" and previous_step else None
            if source is None and attach:
                target = attach if str(attach).startswith(("n:", "c:")) else node_id(str(attach))
                source = target if (self.s.board.node(target) or target in ids) else None
            if source is not None:
                ops.append(
                    {
                        "op": "add_edge",
                        "edge": {
                            "id": f"x:{source}>{nid}",
                            "source": source,
                            "target": nid,
                            "kind": "next" if kind == "step" and source == previous_step else "explains",
                            "provenance": provenance,
                        },
                    }
                )
            if kind == "step":
                previous_step = nid
            ids.append(nid)
        result = await self.s.apply_board(ops)
        return {**result, "node_ids": ids} if result["ok"] else result

    async def _t_annotate(self, a: dict[str, Any]) -> dict[str, Any]:
        target = str(a["target"])
        target = target if target.startswith(("n:", "c:")) else node_id(target)
        provenance = a.get("provenance") if a.get("provenance") in ("inferred", "illustrative") else "inferred"
        ann = {
            "id": f"a:{uuid.uuid4().hex[:6]}",
            "target": target,
            "text": str(a["text"])[:160],
            "provenance": provenance,
        }
        return await self.s.apply_board([{"op": "add_annotation", "annotation": ann}])

    async def _t_narrate(self, a: dict[str, Any]) -> dict[str, Any]:
        board_result: dict[str, Any] = {}
        b = a.get("board") if isinstance(a.get("board"), dict) else {}
        if b.get("show"):
            board_result["show"] = await self._t_show_entities(
                {
                    "refs": b["show"],
                    "layout": b.get("layout", "graph"),
                    "focus": b.get("focus", []),
                    "include_children": b.get("include_children", False),
                }
            )
        if b.get("concepts"):
            board_result["concepts"] = await self._t_add_concept({"items": b["concepts"]})
        count = 0
        for seg in a["segments"]:
            if self.cancel is not None and self.cancel.cancelled:
                break  # interrupted mid-call: no segment may follow `narration.cancel`
            cues = [
                {"at_word": int(c.get("at_word", 0)), "op": c["op"], "target": str(c["target"])}
                for c in seg.get("cues", [])
                if c.get("op") in ("focus", "highlight") and c.get("target")
            ]
            prov = seg.get("provenance", "observed")
            count += await self.s.narrate(
                str(seg["text"]), prov if prov in ("observed", "inferred", "illustrative") else "observed", cues
            )
        self.narrated = True
        out: dict[str, Any] = {"ok": True, "segments": count}
        if board_result:
            out["board"] = board_result
        return out

    async def _t_highlight(self, a: dict[str, Any]) -> dict[str, Any]:
        ok = await self.s.highlight_ref(str(a["ref"]), persistent=True)
        if ok:
            # Only plain, short facts from the adapter (what was found, warnings), never arbitrary payloads.
            extra = {
                k: v
                for k, v in self.s.last_highlight_result.items()
                if k in ("seen", "confidence", "located", "warning", "note") and isinstance(v, (str, int, float, bool))
            }
            return {"ok": True, **{k: (v[:200] if isinstance(v, str) else v) for k, v in extra.items()}}
        return {"ok": False, "error": self.s.last_highlight_error or "could not highlight that element"}

    async def _t_clear_highlight(self, a: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "cleared": await self.s.clear_highlight("tutor")}

    # ------------------------------------------------------------------------------------- exploration
    async def _t_code_map(self, a: dict[str, Any]) -> dict[str, Any]:
        ex = self.s.explorer
        if ex.map is None:
            return {
                "ok": False,
                "error": "the project has not been mapped: the user has to agree to the exploration first"
                if ex.cfg
                else "this application cannot be explored",
            }
        ref = str(a["ref"]) if a.get("ref") else None
        return {"ok": True, "map": ex.map.describe(ref), "stats": ex.map.stats()}

    async def _t_get_study_plan(self, a: dict[str, Any]) -> dict[str, Any]:
        ex = self.s.explorer
        if ex.map is None or ex.phase not in ("studying", "ready"):
            return {"ok": False, "error": "no study in progress"}
        return {"ok": True, "plan": ex.map.study_plan(), "already_read": ex.files_read()}

    async def _t_study_read(self, a: dict[str, Any]) -> dict[str, Any]:
        return await self.s.explorer.study_read(a.get("offset", 0) or 0, a.get("limit", 12) or 12)

    async def _t_record_understanding(self, a: dict[str, Any]) -> dict[str, Any]:
        files = [str(f) for f in (a.get("files") or []) if isinstance(f, str)]
        return self.s.explorer.record(str(a.get("topic", "")), str(a.get("summary", "")), files)

    async def _t_finish_study(self, a: dict[str, Any]) -> dict[str, Any]:
        return await self.s.explorer.finish(str(a.get("overview", "")))

    async def _t_propose_action(self, a: dict[str, Any]) -> dict[str, Any]:
        await self.s.activity("Preparing an action…")
        return await pipeline.propose_action(self.s, a)

    async def _t_learner_status(self, a: dict[str, Any]) -> dict[str, Any]:
        return self.s.tutoring.status()

    async def _t_lesson(self, a: dict[str, Any]) -> dict[str, Any]:
        return await self.s.tutoring.lesson(str(a["action"]), a.get("lesson_id"))

    async def _t_start_exercise(self, a: dict[str, Any]) -> dict[str, Any]:
        return await self.s.tutoring.start_exercise(str(a["exercise_id"]))

    async def _t_exercise_hint(self, a: dict[str, Any]) -> dict[str, Any]:
        return await self.s.tutoring.hint()

    async def _t_check_exercise(self, a: dict[str, Any]) -> dict[str, Any]:
        return await self.s.tutoring.check(claim=True)

    async def _t_declare_done(self, a: dict[str, Any]) -> dict[str, Any]:
        return await self.s.tutoring.declare()

    async def _t_lookup_concept(self, a: dict[str, Any]) -> dict[str, Any]:
        profile = self.s.profile
        if profile is None:
            return {"ok": False, "error": "this application has no glossary"}
        found = profile.lookup(str(a["term"]))
        if found is None:
            return {"ok": False, "error": "term not found in the glossary"}
        return {
            "ok": True,
            "concept": {k: v for k, v in found.items() if k in ("id", "term", "short", "detail", "links")},
        }

    async def _t_ask_clarification(self, a: dict[str, Any]) -> dict[str, Any]:
        options = [str(o) for o in a.get("options", [])][:4]
        await self.s.broadcast({"type": "clarification", "question": str(a["question"]), "options": options})
        self.turn_ended = True
        return {"ok": True, "status": "waiting_for_answer"}


_KEY_RE = re.compile(r"[a-z0-9_-]{1,24}")


def normalize_tool_name(name: str) -> str:
    """Models sometimes write `Narrate`, `functions.narrate` or `narrate ` for `narrate`."""
    return name.strip().split(".")[-1].lower()


def recover_tool_call(text: str, known_tools: set[str]) -> ToolCall | None:
    """Some models (notably gpt-oss) write a tool call as text instead of a real tool call.

    Recognised shapes, with or without a wrapper such as ``<narrate{...}>``, ``<function=narrate>{...}</function>``
    or a code fence: the arguments of `narrate` ({"segments": [...]}), `{"name": ..., "arguments": {...}}`,
    or a known tool name followed by its JSON arguments. Returns None for ordinary prose.
    """
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s).strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return None
    prefix, suffix = s[:start].strip(), s[end + 1 :].strip()
    # Only a tag-like wrapper may surround the JSON; real prose around it means this is not a tool call.
    if prefix and not re.fullmatch(r"<[^<>{}]*", prefix):
        return None
    if suffix and not re.fullmatch(r"(?:</[^<>{}]*>|>)+", suffix):
        return None
    try:
        data = json.loads(s[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    named = [normalize_tool_name(w) for w in re.findall(r"[A-Za-z_][\w.]*", prefix)]
    from_tag = next((n for n in reversed(named) if n in known_tools), None)
    if isinstance(data.get("segments"), list) and "narrate" in known_tools:
        return ToolCall(id=uuid.uuid4().hex[:8], name="narrate", arguments=data)
    name, args = data.get("name"), data.get("arguments")
    if isinstance(name, str) and normalize_tool_name(name) in known_tools and isinstance(args, dict):
        return ToolCall(id=uuid.uuid4().hex[:8], name=normalize_tool_name(name), arguments=args)
    if from_tag is not None:
        return ToolCall(id=uuid.uuid4().hex[:8], name=from_tag, arguments=data)
    return None
