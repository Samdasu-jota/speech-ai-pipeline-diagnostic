"""
WebSocket manager — broadcasts diagnostic reports and alerts to all
connected React dashboard clients in real time.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages the pool of active WebSocket connections."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info("ws_client_connected", extra={"total": len(self._connections)})

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.remove(ws)
        logger.info("ws_client_disconnected", extra={"total": len(self._connections)})

    async def broadcast(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message)
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)

    @property
    def active_connections(self) -> int:
        return len(self._connections)


# Module-level singleton — imported by DiagnosticsEngine and the FastAPI route
manager = ConnectionManager()


async def broadcast_report(report_dict: dict[str, Any]) -> None:
    """Broadcast a diagnostic report to all connected WebSocket clients."""
    await manager.broadcast({"type": "diagnostic_report", "data": report_dict})


async def broadcast_alert(alert_dict: dict[str, Any]) -> None:
    """Broadcast a single alert to all connected WebSocket clients."""
    await manager.broadcast({"type": "alert", "data": alert_dict})
