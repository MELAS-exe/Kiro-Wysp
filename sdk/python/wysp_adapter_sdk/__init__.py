"""Wysp Python adapter SDK. Pure Python (needs only `websocket-client`), safe to embed in Blender."""

from .client import AdapterClient
from .dispatch import Dispatcher, ImmediateDispatcher, QueueDispatcher
from .errors import ErrorCode, WyspError
from .runtime import ActionOutcome, ActionRegistry, AdapterRuntime, OriginTagger

__all__ = [
    "ActionOutcome",
    "ActionRegistry",
    "AdapterClient",
    "AdapterRuntime",
    "Dispatcher",
    "ErrorCode",
    "ImmediateDispatcher",
    "OriginTagger",
    "QueueDispatcher",
    "WyspError",
]
