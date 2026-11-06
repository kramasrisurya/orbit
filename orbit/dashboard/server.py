"""
Dashboard HTTP server.

Serves the static dashboard UI and exposes a few REST endpoints:
  GET /                → index.html
  GET /api/status      → current system status JSON
  GET /api/events      → recent events
  GET /api/stats       → today's stats
  POST /api/command    → execute a command (e.g., start/stop focus)
  GET /api/pairing_qr  → base64 QR code for phone pairing
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from aiohttp import web

from core.event_bus import EventBus
from core.presence import PresenceCore
from core.modes import ModeManager
from db.repositories import EventRepository, StatsRepository
from phone.pairing import PairingManager
from dashboard.websocket import DashboardWebSocket

logger = logging.getLogger("orbit.dashboard.server")

STATIC_DIR = Path(__file__).parent / "static"


class DashboardServer:
    """
    AioHTTP web server for the dashboard UI.
    """

    def __init__(
        self,
        bus: EventBus,
        config,
        presence_core: PresenceCore | None = None,
        mode_manager: ModeManager | None = None,
        event_repo: EventRepository | None = None,
        stats_repo: StatsRepository | None = None,
        pairing_manager: PairingManager | None = None,
        ws: DashboardWebSocket | None = None,
    ) -> None:
        self._bus = bus
        self._config = config
        self._presence = presence_core
        self._modes = mode_manager
        self._events = event_repo
        self._stats = stats_repo
        self._pairing = pairing_manager
        self._ws = ws

        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def start(self) -> None:
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/api/status", self._handle_status)
        self._app.router.add_get("/api/events", self._handle_events)
        self._app.router.add_get("/api/stats", self._handle_stats)
        self._app.router.add_post("/api/command", self._handle_command)
        self._app.router.add_get("/api/pairing_qr", self._handle_pairing_qr)
        self._app.router.add_post("/api/enroll", self._handle_enroll)
        if self._ws is not None:
            self._app.router.add_get("/ws", self._ws.handle)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", self._config.dashboard_port)
        await self._site.start()
        logger.info("Dashboard server running on http://localhost:%d", self._config.dashboard_port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
        logger.info("Dashboard server stopped")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    async def _handle_index(self, request: web.Request) -> web.Response:
        index = STATIC_DIR / "index.html"
        if index.exists():
            return web.Response(text=index.read_text(), content_type="text/html")
        return web.Response(text="<h1>ORBIT Dashboard</h1><p>UI not found.</p>")

    async def _handle_status(self, request: web.Request) -> web.Response:
        status = {
            "presence": "unknown",
            "mode": "work",
            "focus_active": False,
            "phones_connected": 0,
        }
        if self._presence:
            status["presence"] = self._presence.get_state().value
        if self._modes:
            status["mode"] = self._modes.get_current_mode()
        return web.json_response(status)

    async def _handle_events(self, request: web.Request) -> web.Response:
        limit = int(request.query.get("limit", "50"))
        if self._events:
            try:
                events = self._events.query(limit=limit)
                return web.json_response(events)
            except Exception:
                logger.exception("Failed to query events")
        return web.json_response([])

    async def _handle_stats(self, request: web.Request) -> web.Response:
        if self._stats:
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                stats = self._stats.get_daily(today)
                return web.json_response(stats)
            except Exception:
                logger.exception("Failed to get stats")
        return web.json_response({})

    async def _handle_command(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)

        action = data.get("action", "")

        if action == "focus_start":
            from core.event_bus import OrbitEvent, FOCUS_SESSION_START
            self._bus.publish(OrbitEvent(
                type=FOCUS_SESSION_START, source="dashboard", payload={}
            ))
            return web.json_response({"ok": True, "action": action})

        elif action == "focus_end":
            from core.event_bus import OrbitEvent, FOCUS_SESSION_END
            self._bus.publish(OrbitEvent(
                type=FOCUS_SESSION_END, source="dashboard", payload={}
            ))
            return web.json_response({"ok": True, "action": action})

        elif action == "switch_mode":
            mode = data.get("mode", "")
            if self._modes:
                ok = self._modes.switch_mode(mode)
                return web.json_response({"ok": ok, "action": action})
            return web.json_response({"ok": False, "error": "no mode manager"}, status=500)

        elif action == "lock":
            from utils.windows import lock_workstation
            lock_workstation()
            return web.json_response({"ok": True, "action": action})

        return web.json_response({"ok": False, "error": f"unknown action: {action}"}, status=400)

    async def _handle_pairing_qr(self, request: web.Request) -> web.Response:
        if self._pairing:
            try:
                qr_b64 = self._pairing.initiate_pairing()
                return web.json_response({"qr": qr_b64})
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"error": "pairing not available"}, status=500)

    async def _handle_enroll(self, request: web.Request) -> web.Response:
        """Enroll a face from camera capture or provided image."""
        try:
            from enroll import enroll_from_frame
            data = {}
            if request.can_read_body:
                try:
                    data = await request.json()
                except Exception:
                    pass
            label = data.get("label", "owner")
            b64_img = data.get("image")

            if b64_img:
                import base64
                import numpy as np
                import cv2
                img_bytes = base64.b64decode(b64_img.split(",")[-1])
                nparr = np.frombuffer(img_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if frame is None:
                    return web.json_response({"ok": False, "error": "Invalid image data"}, status=400)
                ok = enroll_from_frame(frame, label=label)
                return web.json_response({"ok": ok})
            else:
                import cv2
                cam_idx = self._config.vision_camera_index
                cap = cv2.VideoCapture(cam_idx)
                if not cap.isOpened():
                    return web.json_response({"ok": False, "error": f"Cannot open camera {cam_idx}"}, status=500)
                ret, frame = cap.read()
                cap.release()
                if not ret or frame is None:
                    return web.json_response({"ok": False, "error": "Failed to read camera frame"}, status=500)
                ok = enroll_from_frame(frame, label=label)
                return web.json_response({"ok": ok})
        except Exception as e:
            logger.exception("Enroll endpoint error")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

