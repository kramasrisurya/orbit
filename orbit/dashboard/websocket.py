"""
Dashboard WebSocket bridge.

Bridges EventBus events to connected dashboard browser clients in real
time. The dashboard UI connects to ws://host:port/ws and receives a
stream of JSON events (presence changes, mode changes, camera frames,
alerts, etc.).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import web

from core.event_bus import EventBus, OrbitEvent

logger = logging.getLogger("orbit.dashboard.websocket")

# Event types that are forwarded to the dashboard in real time
FORWARDED_EVENTS = {
    "PRESENCE_CHANGED", "MODE_CHANGED", "FACE_DETECTED",
    "FACE_NOT_DETECTED", "USER_RECOGNIZED", "UNKNOWN_FACE",
    "GAZE_CHANGED", "GESTURE_RECOGNIZED", "EMOTION_DETECTED",
    "POSTURE_ALERT", "INTRUDER_ALERT", "PC_LOCKED",
    "FOCUS_SESSION_START", "FOCUS_SESSION_END", "DASHBOARD_UPDATE",
    "PHONE_CONNECTED", "PHONE_DISCONNECTED",
}


class DashboardWebSocket:
    """
    Manages dashboard WebSocket connections and forwards EventBus events.

    Integrate into the aiohttp app:
        app.router.add_get("/ws", ws.handle)
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._clients: set[web.WebSocketResponse] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bus.subscribe("__all__", self._on_event)

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _on_event(self, event: OrbitEvent) -> None:
        """Forward qualifying events to all connected dashboard clients."""
        if event.type not in FORWARDED_EVENTS:
            return
        if not self._clients:
            return

        msg = json.dumps({
            "type": event.type,
            "source": event.source,
            "ts": event.timestamp.isoformat(),
            "payload": event.payload,
        }, default=str)

        loop = self._loop
        if loop is None or loop.is_closed():
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

        if loop and loop.is_running():
            for ws in list(self._clients):
                if not ws.closed:
                    try:
                        asyncio.run_coroutine_threadsafe(ws.send_str(msg), loop)
                    except Exception:
                        self._clients.discard(ws)

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        """aiohttp route handler for /ws."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        logger.info("Dashboard client connected (%d total)", len(self._clients))

        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    # Dashboard can send commands back (e.g., switch mode)
                    await self._handle_client_message(msg.data)
                elif msg.type in (web.WSMsgType.Close, web.WSMsgType.Closing):
                    break
        except Exception:
            logger.exception("Dashboard WS error")
        finally:
            self._clients.discard(ws)
            logger.info("Dashboard client disconnected (%d total)", len(self._clients))

        return ws

    async def _handle_client_message(self, data: str) -> None:
        """Handle commands sent from the dashboard UI."""
        try:
            cmd = json.loads(data)
        except json.JSONDecodeError:
            return
        action = cmd.get("action")
        if action:
            logger.info("Dashboard command: %s", action)
            # Commands are routed via the EventBus by the main app
            # (the main app subscribes to a DASHBOARD_COMMAND pseudo-event)
            from core.event_bus import OrbitEvent
            self._bus.publish(OrbitEvent(
                type="DASHBOARD_COMMAND",
                source="dashboard",
                payload=cmd,
            ))

    @property
    def client_count(self) -> int:
        return len(self._clients)
