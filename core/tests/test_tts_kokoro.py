"""Neural voice provider, tested with a fake engine (no model, no real synthesis)."""

import asyncio
import wave
from io import BytesIO

from wysp_core import tts


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def create(self, text, voice, speed, lang):
        self.calls.append((text, voice, lang))
        return [0.0] * 2400, 24000


def test_kokoro_wav_and_voice_by_language():
    engine = FakeEngine()
    provider = tts.KokoroTTS(engine=engine)
    audio = asyncio.run(provider.synth("Hello there", "en"))
    asyncio.run(provider.synth("Bonjour", "fr"))
    with wave.open(BytesIO(audio)) as w:
        assert w.getframerate() == 24000 and w.getnframes() == 2400
    assert engine.calls[0][1:] == ("bf_alice", "en-gb")
    assert engine.calls[1][1:] == ("ff_siwis", "fr-fr")


def test_kokoro_voice_override_and_env(tmp_path, monkeypatch):
    engine = FakeEngine()
    asyncio.run(tts.KokoroTTS("af_sarah", engine=engine).synth("Hi", "en"))
    assert engine.calls[0][1] == "af_sarah"
    monkeypatch.setattr(tts, "kokoro_ready", lambda *a: False)
    assert tts.from_env({"WYSP_TTS_PROVIDER": "kokoro"}) is None
    monkeypatch.setattr(tts, "kokoro_ready", lambda *a: True)
    assert tts.from_env({"WYSP_TTS_PROVIDER": "kokoro"}).name == "kokoro"
