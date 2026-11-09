"""Local persistence under ~/.wysp/ (override with WYSP_HOME): token, config, audit, learners."""

from __future__ import annotations

import os
import secrets
from pathlib import Path


def wysp_home() -> Path:
    return Path(os.environ.get("WYSP_HOME") or Path.home() / ".wysp")


def ensure_home() -> Path:
    home = wysp_home()
    for sub in ("sessions", "learners", "audit"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    return home


def load_or_create_token() -> str:
    """Pairing token shared with adapters. Created once, readable only by the user where possible."""
    home = ensure_home()
    path = home / "token"
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass  # Windows: ACLs of the user profile already restrict access
    return token
