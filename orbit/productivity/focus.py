"""
Focus session manager.

Tracks focus sessions (started via phone command, gesture, or dashboard).
While a session is active:
  - Adds a "focus_session" stay-awake override to PresenceCore
  - Tracks elapsed time
  - On end, records focus minutes to daily stats and notifies the phone
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from core.event_bus import (
    EventBus, OrbitEvent,
    FOCUS_SESSION_START, FOCUS_SESSION_END, DASHBOARD_UPDATE,
)
from core.presence import PresenceCore
from db.repositories import StatsRepository

logger = logging.getLogger("orbit.productivity.focus")


class FocusSessionManager:
    """
    Manages focus (deep-work) sessions.
    """

    def __init__(
        self,
        bus: EventBus,
        presence_core: PresenceCore | None = None,
        stats_repo: StatsRepository | None = None,
        notifier=None,
    ) -> None:
        self._bus = bus
        self._presence = presence_core
        self._stats = stats_repo
        self._notifier = notifier

        self._active = False
        self._start: datetime | None = None
        self._elapsed_display = 0  # seconds, updated for dashboard

        self._bus.subscribe(FOCUS_SESSION_START, self._on_start)
        self._bus.subscribe(FOCUS_SESSION_END, self._on_end)

        self._running = False
        self._task: asyncio.Task | None = None

    def _on_start(self, event: OrbitEvent) -> None:
        self.start()

    def _on_end(self, event: OrbitEvent) -> None:
        self.end()

    def start(self) -> None:
        if self._active:
            logger.debug("Focus session already active")
            return
        self._active = True
        self._start = datetime.now()
        logger.info("Focus session started")

        if self._presence:
            self._presence.add_stay_awake("focus_session")

    def end(self) -> None:
        if not self._active:
            logger.debug("No focus session to end")
            return

        duration_min = 0
        if self._start:
            duration_min = int(
                (datetime.now() - self._start).total_seconds() // 60
            )

        self._active = False
        self._start = None
        logger.info("Focus session ended (%d min)", duration_min)

        if self._presence:
            self._presence.remove_stay_awake("focus_session")

        # Record to stats
        if self._stats and duration_min > 0:
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                self._stats.increment(today, "focus_minutes", duration_min)
            except Exception:
                logger.exception("Failed to record focus minutes")

        # Notify phone
        if self._notifier and duration_min > 0:
            try:
                self._notifier.send(
                    "focus",
                    "Focus Session Complete",
                    f"Nice work — {duration_min} minutes of focused time.",
                )
            except Exception:
                logger.exception("Failed to send focus notification")

    async def start_loop(self) -> None:
        """Background loop that updates elapsed time for the dashboard."""
        self._running = True
        self._task = asyncio.create_task(self._tick())
        logger.info("FocusSessionManager loop started")

    async def stop_loop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _tick(self) -> None:
        while self._running:
            await asyncio.sleep(1)
            if self._active and self._start:
                self._elapsed_display = int(
                    (datetime.now() - self._start).total_seconds()
                )

    @property
    def is_active(self) -> bool:
        return self._active

    def get_elapsed_minutes(self) -> int:
        if not self._active or not self._start:
            return 0
        return int((datetime.now() - self._start).total_seconds() // 60)
