"""Text to speech for Panels that cannot speak by themselves (``POST /api/tts``).

Providers are chosen with ``WYSP_TTS_PROVIDER``:

* ``auto`` (default): ``sapi`` on Windows, otherwise none.
* ``sapi``: the voices installed in Windows (offline, no key, nothing leaves the machine), through COM.
* ``none``: disabled; the endpoint answers 503 and Panels fall back to captions only.

``WYSP_TTS_VOICE`` picks a voice by a part of its name (for example ``Zira``); by default the first voice
matching the session language is used. Synthesis runs on one dedicated thread, because COM objects belong
to the thread that created them.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import threading
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


def from_env(env: dict[str, str] | None = None):
    """Return a provider, or None when speech synthesis is not available here."""
    env = dict(os.environ) if env is None else env
    choice = (env.get("WYSP_TTS_PROVIDER") or "auto").lower()
    if choice == "none":
        return None
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
