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
