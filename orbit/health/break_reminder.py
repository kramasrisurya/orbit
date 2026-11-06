"""
Screen break reminder.

Tracks continuous screen time. When the user has been active (present)
for `screen_break_interval_min` minutes without a break, sends a
notification suggesting a break.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from core.event_bus import EventBus, OrbitEvent, PRESENCE_CHANGED
from core.presence import PresenceState
from db.repositories import StatsRepository

logger = logging.getLogger("orbit.health.break")


class BreakReminder:
    """
    Reminds the user to take a screen break.

    Resets the timer when:
      - Presence changes to ABSENT (user left)
      - User acknowledges the break (manual reset)
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

        self._interval = timedelta(
            minutes=config.health_screen_break_interval_min
        )
        self._screen_start: datetime | None = None
        self._running = False
        self._task: asyncio.Task | None = None

        self._bus.subscribe(PRESENCE_CHANGED, self._on_presence_changed)

    def _on_presence_changed(self, event: OrbitEvent) -> None:
        state = event.payload.get("state", "")
        if state == PresenceState.ABSENT.value:
            # User left — reset the timer
            self._screen_start = None
            logger.debug("Break timer reset (user left)")
        elif state in (
            PresenceState.PRESENT_HIGH.value,
            PresenceState.PRESENT_MEDIUM.value,
            PresenceState.PRESENT_LOW.value,
        ):
            # User is here — start the timer if not already running
            if self._screen_start is None:
                self._screen_start = datetime.now()
                logger.debug("Break timer started: %s", self._screen_start)

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("BreakReminder started (interval: %s)", self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("BreakReminder stopped")

    async def _check_loop(self) -> None:
        while self._running:
            await asyncio.sleep(60)  # Check every minute
            if not self._running:
                break
            self._check()

    def _check(self) -> None:
        if self._screen_start is None:
            return

        elapsed = datetime.now() - self._screen_start
        if elapsed >= self._interval:
            minutes = int(elapsed.total_seconds() // 60)
            logger.info("Break reminder: %d min of continuous screen time", minutes)

            if self._notifier:
                try:
                    self._notifier.send(
                        "break_reminder",
                        "Time for a Break",
                        f"You've been at the screen for {minutes} minutes. "
                        "Stand up, stretch, and look at something far away.",
                    )
                except Exception:
                    logger.exception("Failed to send break reminder")

            # Track in stats
            if self._stats:
                try:
                    today = datetime.now().strftime("%Y-%m-%d")
                    self._stats.increment(today, "breaks_taken")
                except Exception:
                    pass

            # Reset timer after sending (user gets a fresh interval)
            self._screen_start = datetime.now()

    def reset(self) -> None:
        """Manually reset the break timer."""
        self._screen_start = None
        logger.info("Break timer manually reset")
