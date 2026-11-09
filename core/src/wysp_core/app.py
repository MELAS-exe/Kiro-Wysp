"""FastAPI application factory: wires the gateway, the session and the Panel together."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .contract import CONTRACT_VERSION
from .gateway import AdapterRegistry, serve_adapter
from .llm import LLMProvider
from .session.bus import EventBus
from .session.session import Session
from .store import ensure_home, load_or_create_token, register_env_secrets, register_secret, wysp_home
from .telemetry import TelemetryLogHandler, from_env
from .trust import AuditLog
from .ui_api import UiHub
from .ui_api.server import serve_ui

log = logging.getLogger("wysp.app")


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".kiro").is_dir() and (parent / "core").is_dir():
            return parent
    return Path.cwd()


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 8765
    dev_origins: list[str] = field(default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"])
    panel_dist: Path | None = None
    profile_roots: list[Path] = field(default_factory=list)
    lang: str = "en"
    log_level: str | None = None  # off | basic | full; None means the WYSP_LOG variable (default full)

    def allowed_origins(self) -> set[str]:
        own = {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}
        extra = {o.strip() for o in os.environ.get("WYSP_ALLOWED_ORIGINS", "").split(",") if o.strip()}
        return own | set(self.dev_origins) | extra


def _session_meta(llm: LLMProvider) -> dict:
    import platform
    import sys

    return {
        "wysp_version": __version__,
        "contract_version": CONTRACT_VERSION,
        "llm_provider": getattr(llm, "name", "?"),
        "llm_model": getattr(llm, "model", None),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }


def create_app(config: Config, llm: LLMProvider) -> FastAPI:
    ensure_home()
    token = load_or_create_token()
    register_secret(token)
    register_env_secrets()

    root = find_repo_root()
    if not config.profile_roots:
        config.profile_roots = [root / "apps"]
    if config.panel_dist is None:
        config.panel_dist = root / "panel" / "dist"

    bus = EventBus()
    hub = UiHub()
    tm = from_env(directory=wysp_home() / "logs", meta=_session_meta(llm), level_override=config.log_level)
    logging.getLogger("wysp").addHandler(TelemetryLogHandler(tm))
    logging.getLogger("wysp").setLevel(min(logging.getLogger("wysp").level or logging.INFO, logging.INFO))
    if hasattr(llm, "__dict__"):
        llm.telemetry = tm  # providers time their own requests
    registry = AdapterRegistry(bus, tm)
    audit = AuditLog(wysp_home() / "audit")
    session = Session(registry, bus, hub, audit, llm, config.profile_roots, config.lang, tm)
    allowed = config.allowed_origins()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        session.start()
        yield
        tm.emit("session.end")
        tm.close()

    app = FastAPI(title="Wysp Core", version=__version__, lifespan=lifespan)
    app.state.session = session
    app.state.registry = registry
    app.state.hub = hub
    app.state.token = token
    app.state.config = config
    app.state.telemetry = tm

    @app.get("/api/metrics")
    async def metrics() -> JSONResponse:
        return JSONResponse(tm.metrics())

    @app.get("/api/health")
    async def health() -> JSONResponse:
        return JSONResponse(
            {
                "ok": True,
                "version": __version__,
                "contract_version": CONTRACT_VERSION,
                "llm": getattr(llm, "name", "?"),
                "adapters": registry.describe(),
                "panels": hub.count,
            }
        )

    @app.websocket("/ws/adapter")
    async def adapter_ws(ws: WebSocket) -> None:
        await serve_adapter(ws, registry, token, allowed)

    @app.websocket("/ws/ui")
    async def ui_ws(ws: WebSocket) -> None:
        await serve_ui(ws, session, hub, allowed)

    dist = config.panel_dist
    if dist is not None and dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="panel")
    else:

        @app.get("/")
        async def no_panel() -> JSONResponse:
            return JSONResponse(
                {"message": "Panel not built yet. Run `npm run build -w panel`, or use the dev server on :5173."}
            )

    return app
