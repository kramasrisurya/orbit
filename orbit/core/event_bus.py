"""
ORBIT in-process pub/sub event bus.

Thread-safe. Supports both synchronous publish (from threads) and
asynchronous publish (from the asyncio event loop).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger("orbit.core.event_bus")


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------
FACE_DETECTED = "FACE_DETECTED"
FACE_NOT_DETECTED = "FACE_NOT_DETECTED"
USER_RECOGNIZED = "USER_RECOGNIZED"
UNKNOWN_FACE = "UNKNOWN_FACE"
GAZE_CHANGED = "GAZE_CHANGED"
GESTURE_RECOGNIZED = "GESTURE_RECOGNIZED"
MULTI_PERSON_DETECTED = "MULTI_PERSON_DETECTED"
EMOTION_DETECTED = "EMOTION_DETECTED"
POSTURE_ALERT = "POSTURE_ALERT"

PHONE_NEAR = "PHONE_NEAR"
PHONE_FAR = "PHONE_FAR"
WIFI_PRESENCE = "WIFI_PRESENCE"
PHONE_SHAKE = "PHONE_SHAKE"
NFC_MODE_TRIGGERED = "NFC_MODE_TRIGGERED"
PHONE_REMOTE_COMMAND = "PHONE_REMOTE_COMMAND"
PHONE_GEO_LEFT = "PHONE_GEO_LEFT"
PHONE_GEO_RETURNED = "PHONE_GEO_RETURNED"

APPROVAL_REQUEST = "APPROVAL_REQUEST"
APPROVAL_GRANTED = "APPROVAL_GRANTED"
APPROVAL_DENIED = "APPROVAL_DENIED"

PRESENCE_CHANGED = "PRESENCE_CHANGED"
MODE_CHANGED = "MODE_CHANGED"
PC_LOCKED = "PC_LOCKED"
PC_UNLOCKED = "PC_UNLOCKED"

CLIPBOARD_SYNC = "CLIPBOARD_SYNC"
DASHBOARD_UPDATE = "DASHBOARD_UPDATE"
FOCUS_SESSION_START = "FOCUS_SESSION_START"
FOCUS_SESSION_END = "FOCUS_SESSION_END"

# --- Security (intruder) ---
INTRUDER_ALERT = "INTRUDER_ALERT"

# --- Phone connectivity ---
PHONE_CONNECTED = "PHONE_CONNECTED"
PHONE_DISCONNECTED = "PHONE_DISCONNECTED"


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------
@dataclass
class OrbitEvent:
    type: str
    source: str
    timestamp: datetime = field(default_factory=datetime.now)
    payload: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------
class EventBus:
    """Thread-safe in-process pub/sub event bus."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[OrbitEvent], None]]] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the asyncio loop for publish_async."""
        self._loop = loop

    def subscribe(self, event_type: str, handler: Callable[[OrbitEvent], None]) -> None:
        """
        Subscribe a handler to an event type.
        Use "__all__" as event_type to receive every event (wildcard).
        """
        with self._lock:
            self._handlers.setdefault(event_type, []).append(handler)
        logger.debug("Subscribed %s to %s", handler.__name__, event_type)

    def publish(self, event: OrbitEvent) -> None:
        """
        Synchronously dispatch to all handlers for the event type,
        plus any wildcard ("__all__") handlers.
        Safe to call from any thread. Exceptions in handlers are caught
        and logged so one bad handler never breaks the bus.
        """
        with self._lock:
            handlers = list(self._handlers.get(event.type, []))
            # Append wildcard handlers
            handlers.extend(self._handlers.get("__all__", []))
        for h in handlers:
            try:
                h(event)
            except Exception:
                logger.exception(
                    "Handler %s failed for event %s",
                    getattr(h, "__name__", repr(h)),
                    event.type,
                )

    def publish_async(self, event: OrbitEvent) -> None:
        """
        Schedule a publish on the asyncio event loop.
        Use this from background threads to hop into the async world.
        """
        if self._loop is None or self._loop.is_closed():
            # Fall back to synchronous publish
            self.publish(event)
            return
        try:
            self._loop.call_soon_threadsafe(self.publish, event)
        except RuntimeError:
            # Loop closed; fall back
            self.publish(event)
