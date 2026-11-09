#!/usr/bin/env python3
"""Kiro hook dispatcher for the Wysp repository.

Called by the hooks in ``.kiro/hooks/*.json``. Humans and CI can run it too::

    uv run --no-project python scripts/kiro/hook.py <check> [paths...]

Checks
------
boundaries  Wysp Core must stay application-agnostic (imports and vocabulary).
schemas     Regenerate the JSON Schemas (Pydantic) and the TypeScript types.
contract    Offline contract checks for the tutor(s) whose adapter changed.
profiles    Validate the pedagogical profiles.
format-py   Format and lint the saved Python file(s) with ruff.
format-ts   Format the saved TypeScript file(s) with prettier.
task-tests  Run the tests of the packages changed in the working tree.

Conventions
-----------
* A check whose prerequisites do not exist yet (the spec task that creates them
  is not done) exits 0 without output, so the hooks can stay enabled from day one.
* Success prints nothing, because hook stdout may be added to the agent context.
* Failures are printed on stderr and the script exits with status 1.
* Only the Python standard library is used.
"""

from __future__ import annotations

import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE_SRC = ROOT / "core" / "src" / "wysp_core"
ALLOW_MARK = "wysp: allow-app-term"

# Host APIs and packages that Wysp Core must never import.
FORBIDDEN_IMPORT_ROOTS = {
    "bpy", "bmesh", "mathutils", "gpu", "blf", "bgl",
    "apps", "wysp_adapter_sdk", "wysp_blender", "wysp_web",
}

# Application vocabulary that must not appear in Core identifiers or strings.
FORBIDDEN_WORDS = {
    "bpy", "bmesh", "blender", "chrome", "chromium", "webextension",
    "dom", "bevel", "subsurf", "modifier", "modifiers",
}

PYTHON_PACKAGES = ["core", "contract-tests", "sdk/python", "apps/blender-tutor"]
TS_WORKSPACES = ["panel", "sdk/ts", "apps/web-tutor/extension", "apps/web-tutor/demo-dashboard"]


# --------------------------------------------------------------------------- utils

def fail(message: str) -> int:
    print(message.rstrip(), file=sys.stderr)
    return 1


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def run(cmd: list[str], cwd: Path = ROOT, timeout: int = 600) -> tuple[int, str]:
    """Run a command and return (exit code, combined output)."""
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except FileNotFoundError as exc:
        return 127, f"command not found: {exc}"
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {' '.join(cmd)}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def tail(text: str, lines: int = 60) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def read_stdin_paths(timeout: float = 0.5) -> list[str]:
    """Extract file paths from the hook event JSON sent on STDIN, if any.

    The exact field name is not documented, so every string value whose key
    looks like a path is collected. Reading happens in a thread so that an
    open-but-silent STDIN never blocks the hook.
    """
    if sys.stdin is None or sys.stdin.isatty():
        return []
    box: dict[str, str] = {}

    def reader() -> None:
        try:
            box["raw"] = sys.stdin.read()
        except Exception:  # noqa: BLE001 - best effort only
            box["raw"] = ""

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    thread.join(timeout)
    raw = box.get("raw", "")
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    keys = {"file_path", "filepath", "path", "file", "target_file", "targetfile", "paths", "files"}
    found: list[str] = []

    def walk(obj: object) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.lower() in keys:
                    if isinstance(value, str):
                        found.append(value)
                    elif isinstance(value, list):
                        found.extend(v for v in value if isinstance(v, str))
                else:
                    walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    return found


def resolve_paths(args: list[str]) -> list[Path]:
    raw = args or read_stdin_paths()
    paths = []
    for item in raw:
        path = Path(item)
        if not path.is_absolute():
            path = ROOT / path
        paths.append(path)
    return paths


def changed_files() -> list[Path]:
    """Files modified, added or untracked in the working tree (git)."""
    git = shutil.which("git")
    if not git:
        return []
    code, out = run([git, "status", "--porcelain", "--untracked-files=all"])
    if code != 0:
        return []
    files = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        name = line[3:].strip().strip('"')
        if " -> " in name:
            name = name.split(" -> ", 1)[1]
        files.append(ROOT / name)
    return files


def uv_path() -> str | None:
    return shutil.which("uv")


# ------------------------------------------------------------------ boundaries

def _split_words(text: str) -> set[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    return {w.lower() for w in re.split(r"[^A-Za-z0-9]+", text) if w}


def _docstring_lines(tree: ast.AST) -> set[int]:
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr):
                value = body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    end = getattr(body[0], "end_lineno", body[0].lineno) or body[0].lineno
                    lines.update(range(body[0].lineno, end + 1))
    return lines


def scan_core(core_src: Path) -> list[str]:
    """Return boundary violations found in a Wysp Core source tree."""
    problems: list[str] = []
    if not core_src.exists():
        return problems
    string_types = {tokenize.STRING}
    fstring_middle = getattr(tokenize, "FSTRING_MIDDLE", None)
    if fstring_middle is not None:
        string_types.add(fstring_middle)

    for file in sorted(core_src.rglob("*.py")):
        text = file.read_text(encoding="utf-8-sig", errors="replace")  # tolerate a BOM
        try:
            tree = ast.parse(text, filename=str(file))
        except SyntaxError as exc:
            problems.append(f"{rel(file)}:{exc.lineno}: syntax error: {exc.msg}")
            continue
        lines = text.splitlines()
        allowed = {i + 1 for i, line in enumerate(lines) if ALLOW_MARK in line}
        docstrings = _docstring_lines(tree)

        import_lines: set[int] = set()
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module]
            for module in modules:
                root = module.split(".")[0]
                if root in FORBIDDEN_IMPORT_ROOTS and node.lineno not in allowed:
                    import_lines.add(node.lineno)
                    problems.append(f"{rel(file)}:{node.lineno}: forbidden import '{module}' in Wysp Core")

        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        except (tokenize.TokenError, SyntaxError):
            tokens = []
        for tok in tokens:
            line_no = tok.start[0]
            if line_no in allowed or line_no in import_lines:
                continue
            if tok.type == tokenize.NAME:
                words = _split_words(tok.string)
            elif tok.type in string_types:
                if line_no in docstrings:
                    continue
                words = _split_words(tok.string)
            else:
                continue
            hits = sorted(words & FORBIDDEN_WORDS)
            if hits:
                problems.append(
                    f"{rel(file)}:{line_no}: application vocabulary {hits} in Wysp Core "
                    f"(move it to an adapter or a profile, or justify '# {ALLOW_MARK}')"
                )
    return problems


def check_boundaries(_args: list[str]) -> int:
    problems = scan_core(CORE_SRC)
    if not problems:
        return 0
    return fail("Core boundary violations:\n" + "\n".join(f"  {p}" for p in problems))


# ------------------------------------------------------------------- schemas

def check_schemas(_args: list[str]) -> int:
    if not (CORE_SRC / "contract" / "export.py").exists():
        return 0
    uv = uv_path()
    if not uv:
        return fail("schemas: 'uv' is not installed (see .kiro/steering/tech.md)")
    code, out = run([uv, "run", "--directory", "core", "python", "-m", "wysp_core.contract.export"])
    if code != 0:
        return fail("schemas: JSON Schema export failed\n" + tail(out))
    npm = shutil.which("npm")
    if (ROOT / "sdk" / "ts" / "package.json").exists() and (ROOT / "node_modules").exists() and npm:
        code, out = run([npm, "run", "gen:types", "--workspace", "sdk/ts"])
        if code != 0:
            return fail("schemas: TypeScript type generation failed\n" + tail(out))
    return 0


# ------------------------------------------------------------------ contract

def _tutors_from(paths: list[Path]) -> list[str]:
    tutors = set()
    for path in paths:
        parts = Path(rel(path)).parts
        if len(parts) >= 2 and parts[0] == "apps":
            tutors.add(parts[1])
    return sorted(tutors)


def check_contract(args: list[str]) -> int:
    if not (ROOT / "contract-tests" / "pyproject.toml").exists():
        return 0
    uv = uv_path()
    if not uv:
        return fail("contract: 'uv' is not installed (see .kiro/steering/tech.md)")
    tutors = _tutors_from(resolve_paths(args))
    if not tutors:
        tutors = sorted(p.parent.name for p in (ROOT / "apps").glob("*/contract.fixture.yaml"))
    failures = []
    for tutor in tutors:
        if not (ROOT / "apps" / tutor / "contract.fixture.yaml").exists():
            continue
        code, out = run([uv, "run", "wysp-contract", "--tutor", tutor, "--offline"])
        if code != 0:
            failures.append(f"[{tutor}]\n{tail(out)}")
    return fail("contract checks failed:\n" + "\n".join(failures)) if failures else 0


# ------------------------------------------------------------------ profiles

def check_profiles(_args: list[str]) -> int:
    if not (CORE_SRC / "cli.py").exists():
        return 0
    uv = uv_path()
    if not uv:
        return fail("profiles: 'uv' is not installed (see .kiro/steering/tech.md)")
    failures = []
    for profile in sorted((ROOT / "apps").glob("*/profile")):
        code, out = run([uv, "run", "wysp", "validate-profile", rel(profile)])
        if code != 0:
            failures.append(f"[{rel(profile)}]\n{tail(out)}")
    return fail("profile validation failed:\n" + "\n".join(failures)) if failures else 0


# -------------------------------------------------------------------- format

def _targets(args: list[str], suffixes: tuple[str, ...]) -> list[str]:
    paths = [p for p in resolve_paths(args) if p.suffix in suffixes and p.exists()]
    if not paths:
        paths = [p for p in changed_files() if p.suffix in suffixes and p.exists()]
    return [rel(p) for p in paths if "node_modules" not in p.parts]


def check_format_py(args: list[str]) -> int:
    uv = uv_path()
    if not uv or not (ROOT / "pyproject.toml").exists():
        return 0
    files = _targets(args, (".py",))
    if not files:
        return 0
    run([uv, "run", "ruff", "format", "--quiet", *files])
    code, out = run([uv, "run", "ruff", "check", "--fix", "--quiet", *files])
    return fail("ruff found issues it cannot fix:\n" + tail(out)) if code not in (0, 127) else 0


def check_format_ts(args: list[str]) -> int:
    name = "prettier.cmd" if os.name == "nt" else "prettier"
    prettier = ROOT / "node_modules" / ".bin" / name
    if not prettier.exists():
        return 0
    files = _targets(args, (".ts", ".tsx"))
    if not files:
        return 0
    code, out = run([str(prettier), "--write", "--log-level", "warn", *files])
    return fail("prettier failed:\n" + tail(out)) if code != 0 else 0


# ---------------------------------------------------------------- task-tests

def check_task_tests(_args: list[str]) -> int:
    changed = [rel(p) for p in changed_files()]
    if not changed:
        return 0
    failures = []
    uv = uv_path()
    for pkg in PYTHON_PACKAGES:
        touched = any(c == pkg or c.startswith(pkg + "/") for c in changed)
        has_tests = (ROOT / pkg / "tests").exists() or (ROOT / pkg / "pyproject.toml").exists()
        if touched and has_tests and uv:
            code, out = run([uv, "run", "--directory", pkg, "pytest", "-q", "-m", "not live"], timeout=900)
            if code not in (0, 5):  # 5 = no tests collected
                failures.append(f"[pytest {pkg}]\n{tail(out)}")
    npm = shutil.which("npm")
    for ws in TS_WORKSPACES:
        touched = any(c.startswith(ws + "/") for c in changed)
        if touched and npm and (ROOT / ws / "package.json").exists() and (ROOT / "node_modules").exists():
            code, out = run([npm, "test", "--workspace", ws, "--if-present"], timeout=900)
            if code != 0:
                failures.append(f"[npm test {ws}]\n{tail(out)}")
    return fail("tests failed after the task:\n" + "\n".join(failures)) if failures else 0


# ---------------------------------------------------------------------- main

CHECKS = {
    "boundaries": check_boundaries,
    "schemas": check_schemas,
    "contract": check_contract,
    "profiles": check_profiles,
    "format-py": check_format_py,
    "format-ts": check_format_ts,
    "task-tests": check_task_tests,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in CHECKS:
        names = ", ".join(CHECKS)
        return fail(f"usage: hook.py <check> [paths...]\nchecks: {names}")
    return CHECKS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
