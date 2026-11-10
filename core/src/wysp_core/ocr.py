"""Text recognition on interface screenshots (``POST /api/ocr``), for the visual side of a hybrid adapter.

An adapter whose host exposes no widget geometry can screenshot one of its own panels and ask where a
label is. Recognition is local: Windows' built-in OCR engine (``Windows.Media.Ocr``) through the PyWinRT
bindings. Images are processed in memory, never stored and never logged.

``WYSP_OCR_PROVIDER``: ``auto`` (default: Windows OCR when available) or ``none``.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Any

MAX_IMAGE_BYTES = 8 * 1024 * 1024


@dataclass
class Word:
    text: str
    x: float
    y: float
    w: float
    h: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "x": round(self.x, 1),
            "y": round(self.y, 1),
            "w": round(self.w, 1),
            "h": round(self.h, 1),
        }


class WindowsOcr:
    name = "windows"

    def __init__(self) -> None:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine

        english = Language("en-US")
        if OcrEngine.is_language_supported(english):
            self._engine = OcrEngine.try_create_from_language(english)
        else:
            self._engine = OcrEngine.try_create_from_user_profile_languages()
        if self._engine is None:
            raise RuntimeError("no OCR language is installed in Windows")
        self.language = self._engine.recognizer_language.language_tag

    async def recognize(self, image: bytes) -> dict[str, Any]:
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

        started = time.monotonic()
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(image)
        await writer.store_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        result = await self._engine.recognize_async(bitmap)
        lines = []
        for line in result.lines:
            words = [
                Word(w.text, w.bounding_rect.x, w.bounding_rect.y, w.bounding_rect.width, w.bounding_rect.height)
                for w in line.words
            ]
            lines.append({"text": line.text, "words": [w.to_dict() for w in words]})
        return {
            "width": bitmap.pixel_width,
            "height": bitmap.pixel_height,
            "lines": lines,
            "language": self.language,
            "ms": round((time.monotonic() - started) * 1000, 1),
        }


def from_env(env: dict[str, str] | None = None):
    """Return an OCR provider, or None when recognition is not available on this machine."""
    env = dict(os.environ) if env is None else env
    if (env.get("WYSP_OCR_PROVIDER") or "auto").lower() == "none" or sys.platform != "win32":
        return None
    try:
        return WindowsOcr()
    except Exception:  # noqa: BLE001 - missing bindings or OCR language: the feature is simply off
        return None


def is_png(data: bytes) -> bool:
    return data[:8] == b"\x89PNG\r\n\x1a\n"
