"""
Stress monitor.

Aggregates EMOTION_DETECTED events. When the "stressed" emotion is
detected for `stress_threshold_min` consecutive minutes (with some
tolerance for brief neutral blips), sends a calming notification.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta

from core.event_bus import EventBus, OrbitEvent, EMOTION_DETECTED
from db.repositories import StatsRepository

logger = logging.getLogger("orbit.health.stress")


class StressMonitor:
    """
    Tracks sustained stress from emotion detection.

    A "stress window" is a sliding 1-minute buffer of emotion samples.
    If the fraction of STRESSED samples in the window exceeds a threshold
    for `stress_threshold_min` consecutive minutes, an alert fires.
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

        self._threshold_min = config.health_stress_threshold_min
        # Sliding window of (timestamp, is_stressed) samples
        self._window: deque[tuple[datetime, bool]] = deque()
        # How long stress has been sustained
        self._sustained_since: datetime | None = None
        self._last_alert: datetime | None = None
        self._alert_cooldown = timedelta(minutes=10)

        self._running = False
        self._task: asyncio.Task | None = None

        self._bus.subscribe(EMOTION_DETECTED, self._on_emotion)

    def _on_emotion(self, event: OrbitEvent) -> None:
        emotion = event.payload.get("emotion", "neutral")
        is_stressed = emotion == "stressed"
        self._window.append((datetime.now(), is_stressed))

        # Prune samples older than 2 minutes
        cutoff = datetime.now() - timedelta(minutes=2)
        while self._window and self._window[0][0] < cutoff:
            self._window.popleft()

    def _current_stress_fraction(self) -> float:
        """Fraction of samples in the last 1 minute that were stressed."""
        if not self._window:
            return 0.0
        cutoff = datetime.now() - timedelta(minutes=1)
        recent = [s for ts, s in self._window if ts >= cutoff]
        if not recent:
            return 0.0
        return sum(recent) / len(recent)

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info(
            "StressMonitor started (threshold: %d min)", self._threshold_min
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("StressMonitor stopped")

    async def _check_loop(self) -> None:
        while self._running:
            await asyncio.sleep(30)  # Check every 30s
            if not self._running:
                break
            self._check()

    def _check(self) -> None:
        fraction = self._current_stress_fraction()
        is_stressed_now = fraction > 0.5

        now = datetime.now()

        if is_stressed_now:
            if self._sustained_since is None:
                self._sustained_since = now
                logger.debug("Stress sustained tracking started")
        else:
            # Stress broke — reset the sustained timer
            self._sustained_since = None
            return

        # Check if sustained long enough
        if self._sustained_since is not None:
            sustained = now - self._sustained_since
            if sustained >= timedelta(minutes=self._threshold_min):
                # Respect cooldown
                if self._last_alert is not None and \
                   now - self._last_alert < self._alert_cooldown:
                    return

                self._last_alert = now
                self._sustained_since = None  # reset after alert
                minutes = int(sustained.total_seconds() // 60)

                logger.info("Stress alert: sustained for %d min", minutes)

                if self._notifier:
                    try:
                        self._notifier.send(
                            "stress",
                            "You seem stressed",
                            "I've noticed you look tense for a while. "
                            "Take a slow breath, roll your shoulders, "
                            "and step away for a minute if you can.",
                        )
                    except Exception:
                        logger.exception("Failed to send stress notification")

                if self._stats:
                    try:
                        today = now.strftime("%Y-%m-%d")
                        self._stats.increment(today, "stress_minutes", minutes)
                    except Exception:
                        pass
