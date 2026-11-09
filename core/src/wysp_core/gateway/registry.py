"""Registry of connected adapters."""

from __future__ import annotations

from typing import Any

from ..session.bus import EventBus
from .connection import AdapterConnection


class AdapterRegistry:
    def __init__(self, bus: EventBus, telemetry=None) -> None:
        self.bus = bus
        self.tm = telemetry
        self._conns: dict[str, AdapterConnection] = {}

    def add(self, conn: AdapterConnection) -> AdapterConnection | None:
        """Register a connection, replacing (and returning) any previous one with the same id."""
        previous = self._conns.get(conn.adapter_id)
        self._conns[conn.adapter_id] = conn
        self.bus.publish("adapter.connected", adapter_id=conn.adapter_id)
        return previous

    def remove(self, conn: AdapterConnection) -> None:
        if self._conns.get(conn.adapter_id) is conn:
            del self._conns[conn.adapter_id]
            self.bus.publish("adapter.disconnected", adapter_id=conn.adapter_id)

    def get(self, adapter_id: str | None) -> AdapterConnection | None:
        return self._conns.get(adapter_id) if adapter_id else None

    def all(self) -> list[AdapterConnection]:
        return list(self._conns.values())

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "adapter_id": c.adapter_id,
                "app": c.manifest.app.model_dump(),
                "integration_level": c.manifest.integration_level,
                "capabilities": list(c.manifest.capabilities),
                "profile_id": c.manifest.profile_id,
                "connected": c.connected,
            }
            for c in self._conns.values()
        ]
