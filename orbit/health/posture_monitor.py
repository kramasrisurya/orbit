"""
Posture monitor.

Subscribes to POSTURE_ALERT events from the vision pipeline.
Sends a phone notification with a cooldown to prevent spam.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from core.event_bus import EventBus, OrbitEvent, POSTURE_ALERT
from db.repositories import StatsRepository

logger = logging.getLogger("orbit.health.posture")


class PostureMonitor:
    """
    Monitors posture alerts and notifies the user.

    Cooldown: minimum `posture_alert_cooldown_min` minutes between
    notifications of the same type.
    """

    def __init__(
        self,
        bus: EventBus,
        config,
        notifier=None,
        stats_repo: StatsRepository | None = None,
    ) -> None:
        self._bus = bus
        self._config = config
        self._notifier = notifier
        self._stats = stats_repo

        # Last notification time per alert type
        self._last_notified: dict[str, float] = {}
        self._cooldown_sec = config.health_posture_alert_cooldown_min * 60

        self._bus.subscribe(POSTURE_ALERT, self._on_posture_alert)

    def _on_posture_alert(self, event: OrbitEvent) -> None:
        alert_type = event.payload.get("type", "unknown")
        duration = event.payload.get("duration_sec", 0)

        now = time.monotonic()
        last = self._last_notified.get(alert_type, 0)
        if now - last < self._cooldown_sec:
            logger.debug("Posture alert suppressed (cooldown): %s", alert_type)
            return

        self._last_notified[alert_type] = now

        # Build a friendly message
        messages = {
            "HUNCHED": "You've been hunched over your screen for a while. Straighten up!",
            "TOO_CLOSE": "You're too close to the screen. Lean back a bit.",
            "TILTED": "Your head is tilted. Try to keep it level.",
        }
        msg = messages.get(alert_type, f"Posture alert: {alert_type}")

        logger.info("Posture alert: %s (%.0fs)", alert_type, duration)

        # Notify phone
        if self._notifier:
            try:
                self._notifier.send("posture", "Posture Check", msg)
            except Exception:
                logger.exception("Failed to send posture notification")

        # Track in daily stats
        if self._stats:
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                self._stats.increment(today, "posture_alerts")
            except Exception:
                logger.exception("Failed to increment posture stats")
