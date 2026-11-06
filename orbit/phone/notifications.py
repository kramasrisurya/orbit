"""
Phone notification dispatcher.

Sends push notifications to the paired phone via Firebase Cloud
Messaging (FCM). If Firebase is not configured, falls back to
WebSocket-only delivery (phone must be connected).

Respects the per-type toggles in the `notifications` config section.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.event_bus import EventBus, OrbitEvent

logger = logging.getLogger("orbit.phone.notifications")

FIREBASE_CREDENTIALS = Path.home() / "ORBIT" / "firebase_credentials.json"

# The 8 notification types
NOTIFICATION_TYPES = (
    "intruder_alert",
    "pc_locked",
    "posture",
    "stress",
    "break_reminder",
    "mode_changed",
    "approval_request",
    "ambient",
)


class PhoneNotifier:
    """
    Sends notifications to the phone.

    Delivery strategy (in order):
      1. FCM push (if Firebase is configured and a device token exists).
      2. WebSocket (if the phone is connected).

    Per-type toggles from config.notifications are respected.
    """

    def __init__(
        self,
        bus: EventBus,
        config,
        ws_server=None,
    ) -> None:
        self._bus = bus
        self._config = config
        self._ws = ws_server
        self._firebase_app = None
        self._messaging = None
        self._device_token: str | None = None
        self._init_firebase()

    def _init_firebase(self) -> None:
        """Initialize Firebase Admin SDK if credentials exist."""
        if not FIREBASE_CREDENTIALS.exists():
            logger.info(
                "Firebase not configured (no %s) — "
                "notifications will use WebSocket only",
                FIREBASE_CREDENTIALS,
            )
            return
        try:
            import firebase_admin
            from firebase_admin import credentials, messaging

            cred = credentials.Certificate(str(FIREBASE_CREDENTIALS))
            self._firebase_app = firebase_admin.initialize_app(cred)
            self._messaging = messaging
            logger.info("Firebase initialized — FCM push enabled")
        except Exception:
            logger.exception("Firebase init failed — falling back to WebSocket only")
            self._firebase_app = None
            self._messaging = None

    def set_device_token(self, token: str) -> None:
        """Store the phone's FCM registration token (sent on pairing)."""
        self._device_token = token
        logger.info("FCM device token stored")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def send(
        self,
        ntype: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> bool:
        """
        Send a notification of the given type.
        Returns True if delivered (via any channel), False otherwise.
        """
        # Respect per-type toggle
        if not self._config.get_notification_enabled(ntype):
            logger.debug("Notification type '%s' disabled in config", ntype)
            return False

        payload = {
            "type": ntype,
            "title": title,
            "body": body,
            **(data or {}),
        }

        delivered = False

        # 1. Try FCM
        if self._messaging is not None and self._device_token:
            delivered = self._send_fcm(ntype, title, body, data)

        # 2. Fall back to / supplement with WebSocket
        if self._ws is not None:
            delivered = self._send_ws(payload) or delivered

        if delivered:
            logger.info("Notification sent [%s]: %s", ntype, title)
        else:
            logger.warning(
                "Notification NOT delivered [%s]: %s (no channel available)",
                ntype, title,
            )
        return delivered

    # ------------------------------------------------------------------
    # Channels
    # ------------------------------------------------------------------
    def _send_fcm(
        self,
        ntype: str,
        title: str,
        body: str,
        data: dict[str, Any] | None,
    ) -> bool:
        try:
            from firebase_admin import messaging

            # FCM data fields must be string values
            fcm_data = {}
            if data:
                for k, v in data.items():
                    fcm_data[k] = v if isinstance(v, str) else json.dumps(v, default=str)

            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=fcm_data,
                token=self._device_token,
            )
            self._messaging.send(message)
            return True
        except Exception:
            logger.exception("FCM send failed")
            return False

    def _send_ws(self, payload: dict[str, Any]) -> bool:
        """Send over WebSocket to all connected phones (async-safe)."""
        if self._ws is None:
            return False
        try:
            loop = getattr(self._ws, "_loop", None)
            if loop is None or loop.is_closed():
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    pass
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._ws.broadcast("notification", payload), loop
                )
                return True
            return False
        except Exception:
            logger.exception("WebSocket notification send failed")
            return False
