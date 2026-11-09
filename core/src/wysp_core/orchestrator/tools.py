"""Tools offered to the LLM. There is deliberately no tool that executes an adapter action directly."""

from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING, Any

from ..board import node_id, project
from ..contract import Observation, Scope, WyspError
from ..llm import ToolCall, ToolSpec
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
            "Add a non-observed node: a general concept, an example or a step. Provenance must be 'inferred' or 'illustrative'.",
            _obj(
                {
                    "label": {"type": "string", "maxLength": 80},
                    "kind": {"type": "string", "enum": ["concept", "example", "step"]},
                    "provenance": {"type": "string", "enum": ["inferred", "illustrative"]},
                    "attach_to": {"type": "string", "description": "Ref or node id to connect to"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                ["label", "provenance"],
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
            "Speak and caption short segments (at most 300 characters each). Cues synchronise the board with the speech.",
            _obj(
                {
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
                    }
                },
                ["segments"],
            ),
        ),
    ),
    "highlight": (
        "highlight",
        ToolSpec(
            "highlight",
            "Point at something inside the application itself: an entity ref from the observation, or an "
            "interface element ref listed in the application description.",
            _obj({"ref": {"type": "string"}}, ["ref"]),
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
    def __init__(self, session: Session) -> None:
        self.s = session
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
        return summarize_observation(obs)

    async def _t_show_entities(self, a: dict[str, Any]) -> dict[str, Any]:
        refs = [str(r) for r in a["refs"]]
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
        provenance = a.get("provenance")
        if provenance not in ("inferred", "illustrative"):
            provenance = "inferred"  # the LLM can never create observed facts
        nid = f"c:{uuid.uuid4().hex[:6]}"
        node = {
            "id": nid,
            "ref": None,
            "kind": a.get("kind", "concept"),
            "label": str(a["label"])[:80],
            "provenance": provenance,
            "confidence": float(a.get("confidence", 0.8 if provenance == "inferred" else 1.0)),
        }
        ops: list[dict[str, Any]] = [{"op": "add_node", "node": node}]
        attach = a.get("attach_to")
        if attach:
            target = attach if attach.startswith(("n:", "c:")) else node_id(attach)
            if self.s.board.node(target):
                ops.append(
                    {
                        "op": "add_edge",
                        "edge": {
                            "id": f"x:{nid}>{target}",
                            "source": target,
                            "target": nid,
                            "kind": "explains",
                            "provenance": provenance,
                        },
                    }
                )
        result = await self.s.apply_board(ops)
        return {**result, "node_id": nid} if result["ok"] else result

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
        count = 0
        for seg in a["segments"]:
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
        return {"ok": True, "segments": count}

    async def _t_highlight(self, a: dict[str, Any]) -> dict[str, Any]:
        ok = await self.s.highlight_ref(str(a["ref"]))
        if ok:
            return {"ok": True}
        return {"ok": False, "error": self.s.last_highlight_error or "could not highlight that element"}

    async def _t_propose_action(self, a: dict[str, Any]) -> dict[str, Any]:
        await self.s.activity("Preparing an action…")
        return await pipeline.propose_action(self.s, a)

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
