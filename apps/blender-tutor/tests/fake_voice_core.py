"""A test Core whose microphone and speech service are fakes, for GUI checks of push-to-talk.

    uv run python apps/blender-tutor/tests/fake_voice_core.py --port 8799

Whatever the button records, the Core "hears" ``--heard``. Never touches a real microphone or Groq.
"""

from __future__ import annotations

import argparse
import array

import uvicorn
from wysp_core.app import Config, create_app
from wysp_core.listen import Listener
from wysp_core.llm import ScriptedLLM


class FakeRecorder:
    rate = 16000

    def __init__(self) -> None:
        self.on = False

    def start(self) -> None:
        self.on = True

    def stop(self):
        self.on = False
        return array.array("h", [6000, -6000] * 12000).tobytes(), 1.5

    def cancel(self) -> None:
        self.on = False


class FakeWhisper:
    name = "fake"

    def __init__(self, heard: str) -> None:
        self.heard = heard

    async def transcribe(self, wav: bytes, lang: str = "en") -> str:
        return self.heard


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--heard", default="show me the add menu")
    args = ap.parse_args()
    llm = ScriptedLLM(
        [
            {"when": "add menu", "calls": [
                {"name": "highlight", "arguments": {"ref": "blender://ui/label/VIEW_3D/Add"}},
                {"name": "narrate", "arguments": {"segments": [
                    {"text": "New objects come from the Add menu, at the top of the 3D Viewport.", "provenance": "observed"}]}}]},
            {"when": "typed hello", "say": "Hello! Ask me anything about your scene."},
        ]
    )  # fmt: skip
    app = create_app(Config(port=args.port), llm)
    app.state.listener = Listener(FakeRecorder(), FakeWhisper(args.heard))
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
