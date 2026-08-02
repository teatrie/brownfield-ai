"""WebSocket connection manager for real-time dashboard updates.

Manages WebSocket client connections and provides broadcast and
per-epic targeted messaging for live artifact timeline updates.
"""

import asyncio
import json
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections for real-time dashboard updates.

    Tracks connected clients and supports broadcast messaging and
    per-epic channel targeting for selective update delivery.
    """

    def __init__(self) -> None:
        """Initialize the connection manager with empty connection tracking."""
        self._connections: list[WebSocket] = []
        self._epic_subscriptions: dict[str, list[WebSocket]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection.

        Args:
            websocket: The WebSocket connection to register.
        """
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from all tracking.

        Args:
            websocket: The WebSocket connection to remove.
        """
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)
            for subs in self._epic_subscriptions.values():
                if websocket in subs:
                    subs.remove(websocket)

    async def subscribe(self, websocket: WebSocket, epic_id: str) -> None:
        """Subscribe a WebSocket to updates for a specific epic.

        Args:
            websocket: The WebSocket connection to subscribe.
            epic_id: The epic identifier to subscribe to.
        """
        async with self._lock:
            if epic_id not in self._epic_subscriptions:
                self._epic_subscriptions[epic_id] = []
            if websocket not in self._epic_subscriptions[epic_id]:
                self._epic_subscriptions[epic_id].append(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a message to all connected clients.

        Disconnected clients are silently removed during broadcast.

        Args:
            message: The message payload to broadcast as JSON.
        """
        payload = json.dumps(message)
        disconnected: list[WebSocket] = []
        async with self._lock:
            for ws in self._connections:
                try:
                    await ws.send_text(payload)
                except (RuntimeError, ConnectionError):
                    disconnected.append(ws)
            for ws in disconnected:
                self._connections.remove(ws)

    async def send_to_epic(self, epic_id: str, message: dict[str, Any]) -> None:
        """Send a message to all clients subscribed to a specific epic.

        Args:
            epic_id: The epic identifier to target.
            message: The message payload to send as JSON.
        """
        payload = json.dumps(message)
        async with self._lock:
            subscribers = self._epic_subscriptions.get(epic_id, [])
            disconnected: list[WebSocket] = []
            for ws in subscribers:
                try:
                    await ws.send_text(payload)
                except (RuntimeError, ConnectionError):
                    disconnected.append(ws)
            for ws in disconnected:
                subscribers.remove(ws)
