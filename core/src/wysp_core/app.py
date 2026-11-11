"""FastAPI application factory: wires the gateway, the session and the Panel together."""

from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .contract import CONTRACT_VERSION
from .gateway import AdapterRegistry, serve_adapter
from .gateway.server import origin_allowed
from .listen import MAX_SECONDS as MAX_LISTEN_SECONDS
from .listen import ListenError
from .listen import from_env as listen_from_env
from .llm import LLMProvider
from .ocr import MAX_IMAGE_BYTES, is_png
from .ocr import from_env as ocr_from_env
from .session.bus import EventBus
from .session.session import Session
from .store import ensure_home, load_or_create_token, register_env_secrets, register_secret, wysp_home
from .telemetry import TelemetryLogHandler, from_env
from .trust import AuditLog
from .tts import clean_for_speech
from .tts import from_env as tts_from_env
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

    app.state.tts = tts_from_env()  # replaceable (tests use a fake; they never call a real voice)
    app.state.ocr = ocr_from_env()  # replaceable, like tts
    app.state.listener = listen_from_env()  # push-to-talk (records the microphone only between start and stop)

    def _may_listen(request: Request) -> JSONResponse | None:
        """Turning the microphone on needs the pairing token, not just a local connection."""
        if not origin_allowed(request.headers.get("origin"), allowed):
            return JSONResponse({"error": "origin not allowed"}, status_code=403)
        if not hmac.compare_digest(request.headers.get("x-wysp-token", ""), token):
            return JSONResponse({"error": "pairing token required"}, status_code=401)
        if request.app.state.listener is None:
            return JSONResponse({"error": "no speech recognition configured"}, status_code=503)
        return None

    @app.post("/api/listen/start")
    async def listen_start(request: Request) -> JSONResponse:
        if (refused := _may_listen(request)) is not None:
            return refused
        try:
            request.app.state.listener.start()
        except ListenError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        except Exception as exc:  # noqa: BLE001 - no microphone, device busy...
            tm.emit("listen.start", ok=False, error=f"{type(exc).__name__}: {exc}"[:200])
            return JSONResponse({"error": "cannot open the microphone"}, status_code=500)
        tm.emit("listen.start", ok=True, provider=request.app.state.listener.name)
        return JSONResponse({"ok": True, "max_s": MAX_LISTEN_SECONDS})

    @app.post("/api/listen/stop")
    async def listen_stop(request: Request) -> JSONResponse:
        if (refused := _may_listen(request)) is not None:
            return refused
        listener = request.app.state.listener
        try:
            result = await listener.stop(session.lang, session.speech_vocabulary())
        except ListenError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        except Exception as exc:  # noqa: BLE001
            tm.emit("listen.stop", ok=False, error=f"{type(exc).__name__}: {exc}"[:200])
            return JSONResponse({"error": "speech recognition failed"}, status_code=502)
        tm.emit(
            "listen.stop",
            full={"text": result.get("text")},
            ok=True,
            seconds=result.get("seconds"),
            duration_ms=result.get("ms"),
            silent=bool(result.get("silent")),
            chars=len(result.get("text", "")),
        )
        return JSONResponse(result)

    @app.post("/api/listen/cancel")
    async def listen_cancel(request: Request) -> JSONResponse:
        if (refused := _may_listen(request)) is not None:
            return refused
        request.app.state.listener.cancel()
        tm.emit("listen.cancel")
        return JSONResponse({"ok": True})

    @app.post("/api/ocr")
    async def recognize(request: Request) -> Response:
        """Where is text on an interface screenshot? Local recognition only; the image is not kept."""
        if not origin_allowed(request.headers.get("origin"), allowed):
            return JSONResponse({"error": "origin not allowed"}, status_code=403)
        engine = request.app.state.ocr
        if engine is None:
            return JSONResponse({"error": "no text recognition on this machine"}, status_code=503)
        image = await request.body()
        if len(image) > MAX_IMAGE_BYTES:
            return JSONResponse({"error": "image too large"}, status_code=413)
        if not is_png(image):
            return JSONResponse({"error": "expected a PNG image"}, status_code=415)
        with tm.span("ocr.recognize", provider=engine.name, bytes=len(image)) as extra:
            try:
                result = await engine.recognize(image)
            except Exception as exc:  # noqa: BLE001 - report, never crash the server
                extra["ok"] = False
                extra["error"] = f"{type(exc).__name__}: {exc}"[:200]
                return JSONResponse({"error": "text recognition failed"}, status_code=500)
            extra["lines"] = len(result.get("lines", []))
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.post("/api/tts")
    async def speak(request: Request) -> Response:
        """Speech for Panels that cannot synthesise it themselves. Local voices only, no proxying."""
        if not origin_allowed(request.headers.get("origin"), allowed):
            return JSONResponse({"error": "origin not allowed"}, status_code=403)
        tts = request.app.state.tts
        if tts is None:
            return JSONResponse({"error": "no text-to-speech provider on this machine"}, status_code=503)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "expected a JSON body"}, status_code=400)
        text = clean_for_speech(str(body.get("text", ""))) if isinstance(body, dict) else ""
        if not text:
            return JSONResponse({"error": "empty text"}, status_code=400)
        lang = str(body.get("lang") or session.lang)[:8]
        with tm.span("tts.synth", provider=tts.name, chars=len(text)) as extra:
            try:
                audio = await tts.synth(text, lang)
            except Exception as exc:  # noqa: BLE001 - report, never crash the server
                extra["ok"] = False
                extra["error"] = f"{type(exc).__name__}: {exc}"[:200]
                return JSONResponse({"error": "speech synthesis failed"}, status_code=500)
            extra["bytes"] = len(audio)
        return Response(content=audio, media_type=tts.mime, headers={"Cache-Control": "no-store"})

    @app.get("/api/health")
    async def health() -> JSONResponse:
        return JSONResponse(
            {
                "ok": True,
                "version": __version__,
                "contract_version": CONTRACT_VERSION,
                "llm": getattr(llm, "name", "?"),
                "tts": getattr(app.state.tts, "name", None),
                "ocr": getattr(app.state.ocr, "name", None),
                "stt": getattr(app.state.listener, "name", None),
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
