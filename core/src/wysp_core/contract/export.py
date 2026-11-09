"""Export the contract as JSON Schema files in `schemas/`.

Run: `uv run python -m wysp_core.contract.export`
CI fails when `git diff --exit-code schemas` is not empty afterwards.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from . import actions, events, manifest, observation, rpc

SCHEMA_ID_BASE = "https://wysp.dev/schemas/1"


def _models() -> dict[str, object]:
    return {
        "rpc-request": rpc.RpcRequest,
        "rpc-response": rpc.RpcResponse,
        "manifest": manifest.Manifest,
        "hello-params": manifest.HelloParams,
        "hello-result": manifest.HelloResult,
        "scope": observation.Scope,
        "entity": observation.Entity,
        "observation": observation.Observation,
        "context": observation.Context,
        "predicate": TypeAdapter(actions.Predicate),
        "predicate-outcome": actions.PredicateOutcome,
        "action-spec": actions.ActionSpec,
        "action-call": actions.ActionCall,
        "action-result": actions.ActionResult,
        "evidence": actions.Evidence,
        "event-state-changed": events.StateChanged,
        "event-selection-changed": events.SelectionChanged,
        "event-user-action": events.UserAction,
        "event-navigation": events.Navigation,
        "params-observe": events.ObserveParams,
        "params-execute": events.ExecuteParams,
        "params-undo": events.UndoParams,
        "params-highlight": events.HighlightParams,
        "params-verify": events.VerifyParams,
    }


def build_schemas() -> dict[str, dict]:
    schemas: dict[str, dict] = {}
    for name, model in _models().items():
        if isinstance(model, TypeAdapter):
            schema = model.json_schema(by_alias=True)
        else:
            assert issubclass(model, BaseModel)
            schema = model.model_json_schema(by_alias=True)
        schema["$id"] = f"{SCHEMA_ID_BASE}/{name}.schema.json"
        schemas[name] = schema
    return schemas


def write_schemas(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    schemas = build_schemas()
    for name, schema in schemas.items():
        path = out_dir / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        written.append(path)
    index = {
        "contract_version": rpc.CONTRACT_VERSION,
        "schemas": {name: f"{SCHEMA_ID_BASE}/{name}.schema.json" for name in schemas},
    }
    idx = out_dir / "index.json"
    idx.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    written.append(idx)
    # remove stale schema files
    keep = {p.name for p in written}
    for stale in out_dir.glob("*.json"):
        if stale.name not in keep:
            stale.unlink()
    return written


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".kiro").is_dir() and (parent / "core").is_dir():
            return parent
    return Path.cwd()


def main() -> int:
    out = find_repo_root() / "schemas"
    written = write_schemas(out)
    print(f"wrote {len(written)} files to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
