"""`wysp-contract`: Contract Test Kit entry point.

    wysp-contract --tutor blender-tutor --offline     validate the fixture and the latest recording (fast, no launch)
    wysp-contract --tutor blender-tutor               online run: launch the tutor, connect, run every check
    wysp-contract --tutor web-tutor                   same, through Playwright (needs the extension built)
    wysp-contract --tutor intellij-tutor              same, `manual`: prints what to start, waits for the adapter
    wysp-contract --fixture <path>                    a fixture outside apps/ (the mock adapter's, for CI)
    wysp-contract --mock                              quick observation checks on the in-process mock adapter

Options: `--port N`, `--junit out.xml`, `--recording out.json`, `--timeout S`, `--only <check>` (repeatable), `--fault <name>`
(in-process mock only: the kit must then fail; see wysp_mock/faults.py). Exit code: 0 all green, 1 a check failed
or the adapter never connected, 2 usage or fixture error.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .fixture import load_fixture, validate_fixture

REPO = Path(__file__).resolve().parents[2]

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


def default_token() -> str | None:
    """The user's usual pairing token, for `manual` launches (an IDE plugin already has it). Never printed."""
    home = Path(os.environ.get("WYSP_HOME") or Path.home() / ".wysp")
    try:
        return (home / "token").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wysp-contract")
    parser.add_argument("--tutor")
    parser.add_argument("--fixture", type=Path, help="fixture file (default: apps/<tutor>/contract.fixture.yaml)")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--mock", action="store_true", help="run the observation checks on the in-process mock")
    parser.add_argument("--junit", type=Path, help="write a JUnit XML report")
    parser.add_argument("--recording", type=Path, help="write the JSON recording of the exchange")
    parser.add_argument("--timeout", type=float, help="seconds to wait for the adapter (default: the fixture's)")
    parser.add_argument("--only", action="append", default=[], help="report only these checks (they all still run)")
    parser.add_argument("--port", type=int, help="harness port (default: free; 8766 for manual launches)")
    parser.add_argument("--fault", action="append", default=[], help="in-process mock only: inject a fault")
    args = parser.parse_args(argv)
    if args.mock:
        return run_mock()
    if not args.tutor and not args.fixture:
        parser.error("--tutor or --fixture is required unless --mock is given")
    fixture_path = args.fixture or REPO / "apps" / args.tutor / "contract.fixture.yaml"
    if not fixture_path.exists():
        print(f"no fixture at {fixture_path}", file=sys.stderr)
        return 2
    label = args.tutor or fixture_path.parent.name
    problems = validate_fixture(fixture_path)
    for p in problems:
        print(f"ERROR {label}: {p}", file=sys.stderr)
    if problems:
        return 1
    fixture = load_fixture(fixture_path)
    tutor_dir = fixture_path.parent
    recordings = tutor_dir / "contract-recordings" / "latest.json"
    if args.offline:
        from .online import revalidate_recording

        if recordings.exists():
            stale = revalidate_recording(recordings)
            for p in stale:
                print(f"ERROR {label}: recording no longer matches the contract: {p}", file=sys.stderr)
            return 1 if stale else 0
        return 0
    return run_online_command(args, fixture, tutor_dir, recordings)


def run_online_command(args: argparse.Namespace, fixture, tutor_dir: Path, recordings: Path) -> int:
    from .online import Options, run_online, write_junit, write_recording

    if args.fault and fixture.launch.kind != "in_process":
        print("--fault only applies to in_process fixtures", file=sys.stderr)
        return 2
    token = default_token() if fixture.launch.kind == "manual" else None
    report = run_online(
        fixture,
        Options(
            timeout_s=args.timeout,
            token=token,
            faults=args.fault,
            port=args.port or (8766 if fixture.launch.kind == "manual" else 0),
            say=lambda s: print(s, flush=True),
        ),
    )
    for f in report.findings:
        if args.only and f.check not in args.only:
            continue
        print(f, file=sys.stdout if f.ok else sys.stderr)
    if args.junit:
        write_junit(report, args.junit)
    # recordings of the real tutors live next to the fixture (committed); other runs only if asked
    target = args.recording or (recordings if fixture.launch.kind != "in_process" and report.manifest else None)
    if target is not None:
        write_recording(report, target)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
