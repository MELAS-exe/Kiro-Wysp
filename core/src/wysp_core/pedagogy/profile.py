"""Profiles: application knowledge as data (YAML). Minimal loader for now; lessons come later."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Profile:
    id: str
    app: str = ""
    primer: str = ""
    languages: list[str] = field(default_factory=lambda: ["en"])
    board_props: dict[str, list[str]] = field(default_factory=dict)
    skills: list[dict[str, Any]] = field(default_factory=list)
    concepts: dict[str, dict[str, Any]] = field(default_factory=dict)
    path: Path | None = None

    def lookup(self, query: str) -> dict[str, Any] | None:
        q = query.strip().lower()
        if q in self.concepts:
            return self.concepts[q]
        for c in self.concepts.values():
            if q == str(c.get("term", "")).lower() or q in [str(a).lower() for a in c.get("aliases", [])]:
                return c
        for c in self.concepts.values():
            if q and q in str(c.get("term", "")).lower():
                return c
        return None


def load_profile(directory: Path) -> Profile:
    data = yaml.safe_load((directory / "profile.yaml").read_text(encoding="utf-8")) or {}
    concepts_file = directory / "concepts.yaml"
    raw = yaml.safe_load(concepts_file.read_text(encoding="utf-8")) if concepts_file.exists() else {}
    items = (raw or {}).get("concepts", raw) if isinstance(raw, dict) else (raw or [])
    concepts: dict[str, dict[str, Any]] = {}
    if isinstance(items, dict):
        concepts = {str(k): {"id": str(k), **v} for k, v in items.items()}
    else:
        concepts = {str(c["id"]): c for c in items}
    return Profile(
        id=data["id"],
        app=data.get("app", ""),
        primer=(data.get("primer") or "").strip(),
        languages=data.get("languages", ["en"]),
        board_props=(data.get("board") or {}).get("props", {}),
        skills=data.get("skills", []),
        concepts=concepts,
        path=directory,
    )


def find_profile(profile_id: str | None, search_roots: list[Path]) -> Profile | None:
    """Look for apps/*/profile/profile.yaml whose id matches."""
    if not profile_id:
        return None
    for root in search_roots:
        for candidate in sorted(root.glob("*/profile/profile.yaml")):
            try:
                data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if data.get("id") == profile_id:
                return load_profile(candidate.parent)
    return None


def validate_profile(directory: Path) -> list[str]:
    """Return human-readable problems with a profile directory (empty list means valid)."""
    problems: list[str] = []
    try:
        data = yaml.safe_load((directory / "profile.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        return [f"{directory / 'profile.yaml'}: cannot read ({exc})"]
    for key in ("id", "app", "primer"):
        if not data.get(key):
            problems.append(f"profile.yaml: missing '{key}'")
    skills = data.get("skills", []) or []
    ids = [s.get("id") for s in skills]
    if len(ids) != len(set(ids)):
        problems.append("profile.yaml: duplicate skill ids")
    known = set(ids)
    for s in skills:
        for pre in s.get("prerequisites", []) or []:
            if pre not in known:
                problems.append(f"profile.yaml: skill '{s.get('id')}' has unknown prerequisite '{pre}'")
    graph = {s["id"]: list(s.get("prerequisites", []) or []) for s in skills if "id" in s}

    def has_cycle(node: str, seen: tuple[str, ...]) -> bool:
        if node in seen:
            return True
        return any(has_cycle(n, (*seen, node)) for n in graph.get(node, []) if n in graph)

    if any(has_cycle(n, ()) for n in graph):
        problems.append("profile.yaml: skill prerequisites contain a cycle")
    if (directory / "concepts.yaml").exists():
        try:
            profile = load_profile(directory)
        except (KeyError, TypeError, yaml.YAMLError) as exc:
            problems.append(f"concepts.yaml: invalid ({exc})")
        else:
            for cid, c in profile.concepts.items():
                for key in ("term", "short"):
                    if not c.get(key):
                        problems.append(f"concepts.yaml: concept '{cid}' is missing '{key}'")
    return problems
