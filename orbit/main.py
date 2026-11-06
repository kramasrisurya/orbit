"""
ORBIT — Personal Ambient Awareness System.

Main entry point. Wires up all subsystems and runs them as a single
asyncio application with background threads for camera/BLE.

Usage:
    python main.py
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

# Ensure the orbit/ package is importable
sys.path.insert(0, str(Path(__file__).parent))

from config import load_config
from utils.logger import setup_logger
from core.event_bus import EventBus
from db.database import Database
from db.repositories import (
    EventRepository,
    StatsRepository,
    IntruderRepository,
    ReportRepository,
    FaceModelRepository,
    SettingsRepository,
)
from core.presence import PresenceCore
from core.modes import ModeManager
from productivity.mode_executor import ModeExecutor
from vision.engine import VisionEngine
from phone.websocket_server import PhoneWebSocketServer
from phone.ble_listener import BleListener
from phone.notifications import PhoneNotifier
from phone.pairing import PairingManager
from command.engine import CommandEngine
from security.approval import ApprovalManager
from security.intruder import IntruderDetector
from health.posture_monitor import PostureMonitor
from health.break_reminder import BreakReminder
from health.stress import StressMonitor
from health.daily_report import DailyReport
from productivity.focus import FocusSessionManager
from productivity.clipboard_sync import ClipboardSync
from dashboard.websocket import DashboardWebSocket
from dashboard.server import DashboardServer

logger = setup_logger("orbit.main")


class OrbitApp:
    """
    Top-level application that owns all subsystems and manages
    their lifecycle.
    """

    def __init__(self) -> None:
        # --- Config ---
        self.config = load_config()
        logger.info("Config loaded")

        # --- Event Bus ---
        self.bus = EventBus()

        # --- Database ---
        self.db = Database()
        self.db.init()
        self.event_repo = EventRepository(self.db)
        self.stats_repo = StatsRepository(self.db)
        self.intruder_repo = IntruderRepository(self.db)
        self.report_repo = ReportRepository(self.db)
        self.face_repo = FaceModelRepository(self.db)
        self.settings_repo = SettingsRepository(self.db)

        # --- Pairing ---
        self.pairing = PairingManager(self.config)

        # --- Phone WebSocket Server ---
        self.phone_ws = PhoneWebSocketServer(
            bus=self.bus,
            config=self.config,
            pairing_manager=self.pairing,
        )

        # --- Phone Notifier ---
        self.notifier = PhoneNotifier(
            bus=self.bus,
            config=self.config,
            ws_server=self.phone_ws,
        )

        # --- Presence Core ---
        self.presence = PresenceCore(
            bus=self.bus,
            config=self.config,
            notifier=self.notifier,
        )

        # --- Mode Executor + Mode Manager ---
        self.mode_executor = ModeExecutor(self.config)
        self.mode_manager = ModeManager(
            bus=self.bus,
            config=self.config,
            mode_executor=self.mode_executor,
            presence_core=self.presence,
        )

        # --- Approval Manager ---
        self.approval = ApprovalManager(self.bus, self.config)

        # --- Command Engine ---
        self.command_engine = CommandEngine(
            bus=self.bus,
            config=self.config,
            mode_manager=self.mode_manager,
            approval_manager=self.approval,
        )

        # --- Vision Engine ---
        self.vision = VisionEngine(
            bus=self.bus,
            config=self.config,
        )

        # --- BLE Listener ---
        self.ble = BleListener(
            bus=self.bus,
            config=self.config,
        )

        # --- Security ---
        self.intruder = IntruderDetector(
            bus=self.bus,
            config=self.config,
            notifier=self.notifier,
            intruder_repo=self.intruder_repo,
            camera_index=self.config.vision_camera_index,
        )

        # --- Health ---
        self.posture = PostureMonitor(
            bus=self.bus,
            config=self.config,
            notifier=self.notifier,
            stats_repo=self.stats_repo,
        )
        self.breaks = BreakReminder(
            bus=self.bus,
            config=self.config,
            notifier=self.notifier,
            stats_repo=self.stats_repo,
        )
        self.stress = StressMonitor(
            bus=self.bus,
            config=self.config,
            notifier=self.notifier,
            stats_repo=self.stats_repo,
        )
        self.daily_report = DailyReport(
            config=self.config,
            notifier=self.notifier,
            stats_repo=self.stats_repo,
            report_repo=self.report_repo,
        )

        # --- Productivity ---
        self.focus = FocusSessionManager(
            bus=self.bus,
            presence_core=self.presence,
            stats_repo=self.stats_repo,
            notifier=self.notifier,
        )
        self.clipboard = ClipboardSync(
            bus=self.bus,
            ws_server=self.phone_ws,
        )

        # --- Dashboard ---
        self.dash_ws = DashboardWebSocket(self.bus)
        self.dashboard = DashboardServer(
            bus=self.bus,
            config=self.config,
            presence_core=self.presence,
            mode_manager=self.mode_manager,
            event_repo=self.event_repo,
            stats_repo=self.stats_repo,
            pairing_manager=self.pairing,
            ws=self.dash_ws,
        )

        # --- Event logging (persist all events to DB) ---
        self.bus.subscribe("__all__", self._log_event)

        self._shutdown_event = asyncio.Event()

    def _log_event(self, event) -> None:
        """Persist every event to the database."""
        try:
            self.event_repo.log(event)
        except Exception:
            logger.debug("Failed to log event to DB: %s", event.type)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Start all subsystems in the correct order."""
        logger.info("=== ORBIT starting ===")

        loop = asyncio.get_running_loop()
        self.bus.set_loop(loop)
        self.dash_ws.set_loop(loop)

        # 1. Phone WebSocket server (async)
        await self.phone_ws.start()

        # 2. Presence core (async background tasks)
        await self.presence.start()

        # 3. Vision engine (background thread)
        self.vision.start()

        # 4. BLE listener (background thread)
        self.ble.start()

        # 5. Health monitors (async background tasks)
        await self.breaks.start()
        await self.stress.start()
        await self.daily_report.start()

        # 6. Focus session manager (async background task)
        await self.focus.start_loop()

        # 7. Clipboard sync (async background task)
        await self.clipboard.start()

        # 8. Dashboard server (async)
        await self.dashboard.start()

        logger.info("=== ORBIT running ===")
        logger.info(
            "Dashboard: http://localhost:%d",
            self.config.dashboard_port,
        )
        logger.info(
            "Phone WS:  ws://0.0.0.0:%d",
            self.config.phone_websocket_port,
        )

    async def stop(self) -> None:
        """Stop all subsystems in reverse order."""
        logger.info("=== ORBIT shutting down ===")

        await self.dashboard.stop()
        await self.clipboard.stop()
        await self.focus.stop_loop()
        await self.daily_report.stop()
        await self.stress.stop()
        await self.breaks.stop()
        self.ble.stop()
        self.vision.stop()
        await self.presence.stop()
        await self.phone_ws.stop()
        self.db.close()

        logger.info("=== ORBIT stopped ===")

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    async def run(self) -> None:
        """Start the app and wait for a shutdown signal."""
        await self.start()

        # Wait for SIGINT / SIGTERM
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._shutdown_event.set)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler for SIGTERM
                pass

        logger.info("Press Ctrl+C to stop")
        await self._shutdown_event.wait()
        await self.stop()


def main() -> None:
    """Entry point."""
    app = OrbitApp()
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("Interrupted")


if __name__ == "__main__":
    main()
