"""Wysp Python adapter SDK. Pure Python (needs only `websocket-client`), safe to embed in Blender."""

from .client import AdapterClient
from .dispatch import Dispatcher, ImmediateDispatcher, QueueDispatcher
from .errors import ErrorCode, WyspError
from .runtime import ActionOutcome, ActionRegistry, AdapterRuntime, OriginTagger

# Keep in step with pyproject.toml. Hosts that cache wheels by version (Blender) only pick up SDK changes
# when this number changes, so bump it whenever the SDK's API changes.
__version__ = "0.2.0"

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
