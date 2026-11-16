"""`wysp-contract`: Contract Test Kit entry point.

    wysp-contract --tutor blender-tutor --offline     validate the fixture (fast, no application launched)
    wysp-contract --tutor blender-tutor               full run against the real adapter (not implemented yet)
    wysp-contract --mock                              observation property checks on the in-process mock adapter

The online harness is adapter-contract task 9. Until then the live checks of the Blender adapter are
run by apps/blender-tutor/tests/test_blender_live.py (headless Blender).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
REQUIRED = ("tutor", "launch", "expect", "safe_calls", "invalid_calls")


def validate_fixture(path: Path) -> list[str]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        return [f"{path}: cannot read ({exc})"]
    problems = [f"missing '{key}'" for key in REQUIRED if key not in data]
    expected = set((data.get("expect") or {}).get("actions", []))
    for section in ("safe_calls", "dry_run_calls"):
        for call in data.get(section, []) or []:
            if "action_id" not in call or "params" not in call:
                problems.append(f"{section}: every call needs action_id and params")
            elif expected and call["action_id"] not in expected:
                problems.append(f"{section}: '{call['action_id']}' is not in expect.actions")
    for call in data.get("invalid_calls", []) or []:
        if "expect_error" not in call:
            problems.append(f"invalid_calls: '{call.get('action_id')}' needs expect_error")
    return problems


MOCK_SAFE_CALLS = [
    {"action_id": "create_card", "params": {"title": "Kit card", "column": "todo"}},
    {"action_id": "select_card", "params": {"card": "mock://card/c1"}},
]


def run_mock() -> int:
    """Run the observation property checks (CON-P2, P3, P7, P10) on the in-process mock adapter."""
    from wysp_core.contract import Manifest
    from wysp_mock.kanban import MockKanban, manifest

    from .checks import run_observation_checks

    mock = MockKanban()
    findings = run_observation_checks(mock.handle, Manifest.model_validate(manifest()), MOCK_SAFE_CALLS)
    for f in findings:
        print(f, file=sys.stderr if not f.ok else sys.stdout)
    return 0 if all(f.ok for f in findings) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wysp-contract")
    parser.add_argument("--tutor")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--mock", action="store_true", help="run the observation checks on the in-process mock")
    args = parser.parse_args(argv)
    if args.mock:
        return run_mock()
    if not args.tutor:
        parser.error("--tutor is required unless --mock is given")
    fixture = REPO / "apps" / args.tutor / "contract.fixture.yaml"
    if not fixture.exists():
        print(f"no fixture at {fixture}", file=sys.stderr)
        return 2
    problems = validate_fixture(fixture)
    for p in problems:
        print(f"ERROR {args.tutor}: {p}", file=sys.stderr)
    if problems:
        return 1
    if not args.offline:
        print("The online harness is not implemented yet; use --offline.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
