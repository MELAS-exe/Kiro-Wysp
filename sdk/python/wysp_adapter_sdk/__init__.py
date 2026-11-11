"""Wysp Python adapter SDK. Pure Python (needs only `websocket-client`), safe to embed in Blender."""

from .client import AdapterClient
from .dispatch import Deferred, Dispatcher, ImmediateDispatcher, QueueDispatcher
from .errors import ErrorCode, WyspError
from .runtime import ActionOutcome, ActionRegistry, AdapterRuntime, OriginTagger

# Keep in step with pyproject.toml. Hosts that cache wheels by version (Blender) only pick up SDK changes
# when this number changes, so bump it whenever the SDK's API changes.
__version__ = "0.3.0"

__all__ = [
    "ActionOutcome",
    "ActionRegistry",
    "AdapterClient",
    "AdapterRuntime",
    "Deferred",
    "Dispatcher",
    "ErrorCode",
    "ImmediateDispatcher",
    "OriginTagger",
    "QueueDispatcher",
    "WyspError",
]
