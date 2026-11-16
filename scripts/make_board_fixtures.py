"""Generate the board golden fixtures read by the Panel's patch parity test (PAN-P1).

Each fixture is built with the Core's own board code (normalize_ops, apply_ops, make_patch), so the
TypeScript twin in panel/src/board/applyOps.ts is checked against the real implementation.

Run: uv run --no-sync python scripts/make_board_fixtures.py
Output: contract-tests/fixtures/board/*.json (committed; regenerate when the board model changes).
Everything is seeded: running it twice gives byte-identical files.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from wysp_core.board import Board, BoardError, apply_ops, make_patch, normalize_ops

OUT = Path(__file__).resolve().parent.parent / "contract-tests" / "fixtures" / "board"
PROVS = ["observed", "inferred", "illustrative"]
LAYOUTS = ["stack", "tree", "graph", "sequence"]
STATUSES = ["pending", "active", "done", "failed"]


def node(nid: str, prov: str = "observed", **kw: Any) -> dict[str, Any]:
    return {"id": nid, "kind": kw.pop("kind", "object"), "label": kw.pop("label", nid), "provenance": prov, **kw}


def run(name: str, batches: list[list[dict[str, Any]]], initial: Board | None = None) -> dict[str, Any]:
    """Apply each batch of ops with the Core and record the patch and the board it produced."""
    board = initial or Board()
    start = board.model_dump(mode="json")
    patches: list[dict[str, Any]] = []
    expected: list[dict[str, Any]] = []
    for batch in batches:
        ops = normalize_ops(batch)
        try:
            after = apply_ops(board, ops)
        except BoardError:
            continue  # the Core refused it: no patch is ever sent, so it is not a fixture
        patches.append(make_patch(board, after, ops).model_dump(mode="json"))
        expected.append(after.model_dump(mode="json"))
        board = after
    return {"name": name, "initial": start, "patches": patches, "expected": expected}


def hand_built() -> list[dict[str, Any]]:
    stack = [
        [
            {"op": "set_layout", "layout": "stack"},
            {"op": "add_node", "node": node("o:cube", "observed", ref="mock://cube", kind="object")},
            {
                "op": "add_node",
                "node": node("m:1", "observed", ref="mock://cube/m1", order=0, props_view=[["levels", "2"]]),
            },
            {"op": "add_node", "node": node("m:2", "inferred", order=1, confidence=0.6, badges=["new"])},
            {"op": "add_edge", "edge": {"id": "e1", "source": "o:cube", "target": "m:1", "kind": "has"}},
            {"op": "set_focus", "ids": ["m:1", "ghost"]},
        ],
        [{"op": "add_annotation", "annotation": {"id": "a1", "target": "m:2", "text": "probably a bevel"}}],
        [{"op": "add_node", "node": node("m:1", "illustrative", label="replaced", order=0)}],
        [{"op": "remove_node", "id": "m:1"}],
        [{"op": "set_stale", "stale": True}],
        [{"op": "clear"}],
    ]
    steps = [
        [
            {"op": "add_node", "node": node("n1", "illustrative")},
            {
                "op": "set_steps",
                "steps": [
                    {"id": "s1", "index": 0, "text": "Select it", "target": "n1"},
                    {"id": "s2", "index": 1, "text": "Apply it"},
                ],
            },
        ],
        [{"op": "update_step", "id": "s1", "status": "active"}],
        [{"op": "update_step", "id": "s2", "text": "Apply the change", "status": "done"}],
        [{"op": "remove_node", "id": "n1"}],
        [{"op": "add_edge", "edge": {"id": "bad", "source": "n1", "target": "n1", "kind": "x"}}],  # refused by Core
        [{"op": "remove_edge", "id": "nothing"}, {"op": "remove_annotation", "id": "nothing"}],
    ]
    return [run("stack_and_cascade", stack), run("steps", steps)]


def random_sequence(seed: int, length: int = 25) -> dict[str, Any]:
    """A seeded random walk over valid ops. The Core is the oracle: refused batches are dropped."""
    rng = random.Random(seed)
    board = Board()
    batches: list[list[dict[str, Any]]] = []
    n_edges = n_ann = n_steps = 0
    for _ in range(length):
        ids = [n.id for n in board.nodes]
        ops: list[dict[str, Any]] = []
        for _ in range(rng.randint(1, 4)):
            kind = rng.choice(
                [
                    "add_node",
                    "add_node",
                    "add_edge",
                    "remove_node",
                    "set_layout",
                    "set_focus",
                    "annotate",
                    "steps",
                    "update_step",
                    "stale",
                    "remove_edge",
                    "clear",
                ]
            )
            if kind == "add_node":
                nid = f"n{rng.randint(0, 9)}"
                extra: dict[str, Any] = {"label": f"L{rng.randint(0, 99)}"}
                if rng.random() < 0.4:
                    extra["order"] = rng.randint(0, 5)
                if rng.random() < 0.3:
                    extra["badges"] = ["b"]
                ops.append({"op": "add_node", "node": node(nid, rng.choice(PROVS), **extra)})
                ids.append(nid)
            elif kind == "add_edge" and len(ids) >= 2:
                n_edges += 1
                ops.append(
                    {
                        "op": "add_edge",
                        "edge": {
                            "id": f"e{rng.randint(0, 6)}",
                            "source": rng.choice(ids),
                            "target": rng.choice(ids),
                            "kind": "link",
                        },
                    }
                )
            elif kind == "remove_node" and ids:
                ops.append({"op": "remove_node", "id": rng.choice(ids)})
            elif kind == "set_layout":
                ops.append({"op": "set_layout", "layout": rng.choice(LAYOUTS)})
            elif kind == "set_focus":
                ops.append({"op": "set_focus", "ids": rng.sample(ids, min(len(ids), rng.randint(0, 2)))})
            elif kind == "annotate" and ids:
                n_ann += 1
                ops.append(
                    {
                        "op": "add_annotation",
                        "annotation": {"id": f"a{rng.randint(0, 4)}", "target": rng.choice(ids), "text": "note"},
                    }
                )
            elif kind == "steps":
                n_steps += 1
                ops.append(
                    {
                        "op": "set_steps",
                        "steps": [
                            {
                                "id": f"s{i}",
                                "index": i,
                                "text": f"step {i}",
                                "target": rng.choice(ids) if ids and rng.random() < 0.5 else None,
                            }
                            for i in range(rng.randint(0, 3))
                        ],
                    }
                )
            elif kind == "update_step":
                ops.append({"op": "update_step", "id": f"s{rng.randint(0, 2)}", "status": rng.choice(STATUSES)})
            elif kind == "stale":
                ops.append({"op": "set_stale", "stale": rng.random() < 0.5})
            elif kind == "remove_edge":
                ops.append({"op": "remove_edge", "id": f"e{rng.randint(0, 6)}"})
            elif kind == "clear" and rng.random() < 0.2:
                ops.append({"op": "clear"})
        if not ops:
            continue
        try:
            board = apply_ops(board, normalize_ops(ops))
            batches.append(ops)
        except BoardError:
            continue
    return run(f"random_{seed}", batches)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fixtures = hand_built() + [random_sequence(seed) for seed in (1, 2, 3, 4, 5, 6)]
    for old in OUT.glob("*.json"):
        old.unlink()
    for fx in fixtures:
        (OUT / f"{fx['name']}.json").write_text(json.dumps(fx, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{fx['name']}: {len(fx['patches'])} patches")


if __name__ == "__main__":
    main()
