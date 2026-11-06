"""
Daily health report.

At `daily_report_time` (config), compiles the day's stats and sends a
summary to the phone. Tracks whether today's report was already sent
(via ReportRepository) to avoid duplicates.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time as dtime

from db.repositories import StatsRepository, ReportRepository

logger = logging.getLogger("orbit.health.report")


class DailyReport:
    """
    Sends a daily health/usage summary at the configured time.
    """

    def __init__(
        self,
        config,
        notifier=None,
        stats_repo: StatsRepository | None = None,
        report_repo: ReportRepository | None = None,
    ) -> None:
        self._config = config
        self._notifier = notifier
        self._stats = stats_repo
        self._reports = report_repo

        # Parse the report time "HH:MM"
        hh, mm = config.health_daily_report_time.split(":")
        self._report_time = dtime(int(hh), int(mm))

        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "DailyReport started (sends at %s)",
            self._config.health_daily_report_time,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DailyReport stopped")

    async def _loop(self) -> None:
        while self._running:
            now = datetime.now()
            current = now.time()

            # Fire when we cross the report time (and haven't sent today)
            if current >= self._report_time:
                today = now.strftime("%Y-%m-%d")
                if self._should_send(today):
                    await self._send_report(today)

            # Sleep until the next check (30s granularity is fine)
            await asyncio.sleep(30)

    def _should_send(self, today: str) -> bool:
        if self._reports is None:
            return True
        try:
            return not self._reports.was_sent_today(today)
        except Exception:
            logger.exception("Failed to check report status")
            return True

    async def _send_report(self, today: str) -> None:
        if self._stats is None:
            logger.warning("No StatsRepository — cannot build report")
            return

        try:
            stats = self._stats.get_daily(today)
        except Exception:
            logger.exception("Failed to fetch daily stats")
            return

        body = (
            f"Focus: {stats.get('focus_minutes', 0)} min\n"
            f"Screen time: {stats.get('screen_time_min', 0)} min\n"
            f"Breaks taken: {stats.get('breaks_taken', 0)}\n"
            f"Posture alerts: {stats.get('posture_alerts', 0)}\n"
            f"Stress minutes: {stats.get('stress_minutes', 0)}\n"
            f"Intruder alerts: {stats.get('intruder_alerts', 0)}\n"
            f"PC locks: {stats.get('pc_locks', 0)}"
        )

        logger.info("Sending daily report for %s", today)

        if self._notifier:
            try:
                self._notifier.send(
                    "daily_report",
                    f"Your Day — {today}",
                    body,
                )
            except Exception:
                logger.exception("Failed to send daily report")

        # Mark as sent
        if self._reports:
            try:
                self._reports.mark_sent(today)
            except Exception:
                logger.exception("Failed to mark report as sent")
