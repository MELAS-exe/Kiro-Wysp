"""Push-to-talk for Panels that cannot listen by themselves (``POST /api/listen/{start,stop,cancel}``).

The Core records the default microphone only between ``start`` and ``stop`` (at most ``MAX_SECONDS``),
then transcribes the clip. Audio stays in memory: it is never written to disk and never logged.

``WYSP_STT_PROVIDER``:
* ``auto`` (default): ``groq`` when a Groq key is configured, otherwise none.
* ``groq``: Whisper on Groq (``WYSP_STT_MODEL``, default ``whisper-large-v3-turbo``). The audio clip is sent to
  Groq, like the conversation text already is when Groq is the LLM.
* ``none``: disabled; the endpoints answer 503.
"""

from __future__ import annotations

import array
import io
import math
import os
import threading
import time
import wave
from typing import Any

import httpx

MAX_SECONDS = 30.0
SAMPLE_RATE = 16_000
SILENCE_RMS = 0.004  # below this the clip is treated as silence and never sent (Whisper invents text on silence)


class ListenError(RuntimeError):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def rms(pcm16: bytes) -> float:
    samples = array.array("h", pcm16[: len(pcm16) // 2 * 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768.0


def to_wav(pcm16: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm16)
    return buf.getvalue()


class MicRecorder:
    """The default input device, 16-bit mono. One recording at a time."""

    def __init__(self) -> None:
        import sounddevice  # noqa: F401 - fail early when the library or PortAudio is missing

        self._lock = threading.Lock()
        self._chunks: list[bytes] = []
        self._stream = None
        self._started = 0.0
        self.rate = SAMPLE_RATE

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        import sounddevice as sd

        with self._lock:
            if self._stream is not None:
                raise ListenError("already listening")
            self._chunks = []

            def callback(data, _frames, _time, _status) -> None:
                if time.monotonic() - self._started <= MAX_SECONDS:
                    self._chunks.append(bytes(data))

            try:
                stream = sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", callback=callback)
                self.rate = SAMPLE_RATE
            except Exception:  # noqa: BLE001 - some devices refuse 16 kHz: use their own rate
                rate = int(sd.query_devices(kind="input")["default_samplerate"])
                stream = sd.RawInputStream(samplerate=rate, channels=1, dtype="int16", callback=callback)
                self.rate = rate
            self._started = time.monotonic()
            stream.start()
            self._stream = stream

    def stop(self) -> tuple[bytes, float]:
        """Stop and return (16-bit PCM, seconds)."""
        with self._lock:
            stream, self._stream = self._stream, None
            if stream is None:
                raise ListenError("not listening")
            stream.stop()
            stream.close()
            pcm = b"".join(self._chunks)
            self._chunks = []
        return pcm, len(pcm) / 2 / float(self.rate)

    def cancel(self) -> None:
        try:
            self.stop()
        except ListenError:
            pass


class GroqWhisper:
    name = "groq"
    url = "https://api.groq.com/openai/v1/audio/transcriptions"

    def __init__(self, api_key: str, model: str = "whisper-large-v3-turbo") -> None:
        self._key = api_key
        self.model = model

    async def transcribe(self, wav: bytes, lang: str = "en") -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                self.url,
                headers={"Authorization": f"Bearer {self._key}"},
                files={"file": ("speech.wav", wav, "audio/wav")},
                data={"model": self.model, "response_format": "json", "language": lang[:2] or "en"},
            )
        if r.status_code != 200:
            raise RuntimeError(f"speech service answered {r.status_code}")
        return str(r.json().get("text", "")).strip()


class Listener:
    """Recorder + transcriber, as used by the HTTP endpoints."""

    def __init__(self, recorder, transcriber) -> None:
        self.recorder = recorder
        self.transcriber = transcriber
        self.name = transcriber.name

    def start(self) -> None:
        self.recorder.start()

    def cancel(self) -> None:
        self.recorder.cancel()

    async def stop(self, lang: str = "en") -> dict[str, Any]:
        pcm, seconds = self.recorder.stop()
        level = rms(pcm)
        if seconds < 0.3 or level < SILENCE_RMS:
            return {"text": "", "seconds": round(seconds, 2), "silent": True}
        started = time.monotonic()
        text = await self.transcriber.transcribe(to_wav(pcm, self.recorder.rate), lang)
        return {"text": text, "seconds": round(seconds, 2), "ms": round((time.monotonic() - started) * 1000, 1)}


def from_env(env: dict[str, str] | None = None) -> Listener | None:
    env = dict(os.environ) if env is None else env
    choice = (env.get("WYSP_STT_PROVIDER") or "auto").lower()
    key = env.get("WYSP_STT_API_KEY") or env.get("GROQ_API_KEY")
    if choice not in ("auto", "groq") or not key:
        return None
    try:
        recorder = MicRecorder()
    except Exception:  # noqa: BLE001 - no audio library or no PortAudio: the feature is off
        return None
    return Listener(recorder, GroqWhisper(key, env.get("WYSP_STT_MODEL") or "whisper-large-v3-turbo"))
