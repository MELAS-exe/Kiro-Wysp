"""Text to speech for Panels that cannot speak by themselves (``POST /api/tts``).

Providers are chosen with ``WYSP_TTS_PROVIDER``:

* ``auto`` (default): ``sapi`` on Windows, otherwise none.
* `kokoro`: a natural female neural voice (Kokoro-82M, Apache-2.0), offline, nothing leaves the machine. Needs
  the `voice` extra (`uv sync --extra voice`) and the model files (`wysp install-voice`). `auto` prefers it when ready.
* `sapi`: the voices installed in Windows (offline, no key, nothing leaves the machine), through COM.
* ``none``: disabled; the endpoint answers 503 and Panels fall back to captions only.

``WYSP_TTS_VOICE`` picks a voice by a part of its name (for example ``Zira``); by default the first voice
matching the session language is used. Synthesis runs on one dedicated thread, because COM objects belong
to the thread that created them.
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
import threading
import wave
from array import array
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MAX_TTS_CHARS = 600
LANG_NAMES = {"en": "English", "fr": "French", "de": "German", "es": "Spanish", "it": "Italian"}


class TTSUnavailable(RuntimeError):
    pass


class SapiTTS:
    name = "sapi"
    mime = "audio/wav"

    def __init__(self, voice_hint: str | None = None) -> None:
        self.voice_hint = (voice_hint or "").lower() or None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wysp-tts")
        self._local = threading.local()

    def _voice(self):
        if getattr(self._local, "voice", None) is None:
            import comtypes
            import comtypes.client

            comtypes.CoInitialize()
            self._local.voice = comtypes.client.CreateObject("SAPI.SpVoice")
        return self._local.voice

    def voices(self) -> list[str]:
        voices = self._voice().GetVoices()
        return [voices.Item(i).GetDescription() for i in range(voices.Count)]

    def _pick(self, lang: str):
        voice = self._voice()
        tokens = voice.GetVoices()
        items = [tokens.Item(i) for i in range(tokens.Count)]
        names = [t.GetDescription().lower() for t in items]
        wanted = LANG_NAMES.get(lang[:2].lower(), "English").lower()
        for i, name in enumerate(names):
            if self.voice_hint and self.voice_hint in name:
                return items[i]
        for i, name in enumerate(names):
            if wanted in name:
                return items[i]
        return items[0] if items else None

    def _synth_blocking(self, text: str, lang: str) -> bytes:
        import comtypes.client

        voice = self._voice()
        token = self._pick(lang)
        if token is not None:
            voice.Voice = token
        fmt = comtypes.client.CreateObject("SAPI.SpAudioFormat")
        fmt.Type = 22  # SAFT22kHz16BitMono
        stream = comtypes.client.CreateObject("SAPI.SpFileStream")
        stream.Format = fmt
        fd, name = tempfile.mkstemp(prefix="wysp-tts-", suffix=".wav")
        os.close(fd)
        try:
            stream.Open(name, 3)  # SSFMCreateForWrite
            voice.AudioOutputStream = stream
            voice.Speak(text, 0)  # SVSFDefault: synchronous, plain text (no XML interpretation flag)
            stream.Close()
            return Path(name).read_bytes()
        finally:
            try:
                os.remove(name)
            except OSError:
                pass

    async def synth(self, text: str, lang: str = "en") -> bytes:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, self._synth_blocking, text, lang)


KOKORO_DIR = Path.home() / ".wysp" / "models" / "kokoro"
_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO_FILES = {
    "kokoro-v1.0.int8.onnx": _RELEASE + "kokoro-v1.0.int8.onnx",
    "voices-v1.0.bin": _RELEASE + "voices-v1.0.bin",
}
# Female voices by session language. WYSP_TTS_VOICE overrides the name.
KOKORO_VOICES = {
    "en": ("bf_alice", "en-gb"),
    "fr": ("ff_siwis", "fr-fr"),
    "es": ("ef_dora", "es"),
    "it": ("if_sara", "it"),
}


def kokoro_ready(model_dir: Path = KOKORO_DIR) -> bool:
    if not all((model_dir / name).is_file() for name in KOKORO_FILES):
        return False
    try:
        import kokoro_onnx  # noqa: F401
    except ImportError:
        return False
    return True


class KokoroTTS:
    """Offline neural voice. The model loads on first use and synthesis runs on one worker thread."""

    name = "kokoro"
    mime = "audio/wav"

    def __init__(self, voice: str | None = None, model_dir: Path = KOKORO_DIR, engine=None) -> None:
        self.voice = voice or None
        self.model_dir = model_dir
        self._engine = engine
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wysp-kokoro")

    def _load(self):
        if self._engine is None:
            from kokoro_onnx import Kokoro

            self._engine = Kokoro(
                str(self.model_dir / "kokoro-v1.0.int8.onnx"), str(self.model_dir / "voices-v1.0.bin")
            )
        return self._engine

    def _synth_blocking(self, text: str, lang: str) -> bytes:
        voice, code = KOKORO_VOICES.get(lang[:2].lower(), KOKORO_VOICES["en"])
        samples, rate = self._load().create(text, voice=self.voice or voice, speed=1.0, lang=code)
        pcm = array("h", (int(max(-1.0, min(1.0, float(s))) * 32767) for s in samples))
        if sys.byteorder == "big":
            pcm.byteswap()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(int(rate))
            w.writeframes(pcm.tobytes())
        return buf.getvalue()

    async def synth(self, text: str, lang: str = "en") -> bytes:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, self._synth_blocking, text, lang)


def install_kokoro(model_dir: Path = KOKORO_DIR) -> None:
    """Download the model files (about 115 MB, once) from the kokoro-onnx GitHub release."""
    import httpx

    model_dir.mkdir(parents=True, exist_ok=True)
    for name, url in KOKORO_FILES.items():
        target = model_dir / name
        if target.is_file():
            continue
        tmp = target.with_suffix(target.suffix + ".part")
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        tmp.replace(target)


def from_env(env: dict[str, str] | None = None):
    """Return a provider, or None when speech synthesis is not available here."""
    env = dict(os.environ) if env is None else env
    choice = (env.get("WYSP_TTS_PROVIDER") or "auto").lower()
    if choice == "none":
        return None
    if choice == "kokoro" or (choice == "auto" and kokoro_ready()):
        return KokoroTTS(env.get("WYSP_TTS_VOICE")) if kokoro_ready() else None
    if choice in ("auto", "sapi") and sys.platform == "win32":
        try:
            import comtypes  # noqa: F401
        except ImportError:
            return None
        return SapiTTS(env.get("WYSP_TTS_VOICE"))
    return None


def clean_for_speech(text: str) -> str:
    """Plain, bounded text: control characters out, length capped."""
    text = "".join(ch if ch.isprintable() else " " for ch in text)
    return " ".join(text.split())[:MAX_TTS_CHARS]
