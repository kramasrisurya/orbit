"""
Tests for DashboardServer REST endpoints.
"""

import pytest
from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web
from core.event_bus import EventBus
from core.presence import PresenceCore
from core.modes import ModeManager
from db.database import Database
from db.repositories import EventRepository, StatsRepository
from phone.pairing import PairingManager
from dashboard.server import DashboardServer


@pytest.mark.asyncio
async def test_dashboard_endpoints(event_bus: EventBus, temp_db: Database, mock_config):
    presence = PresenceCore(bus=event_bus, config=mock_config)
    modes = ModeManager(bus=event_bus, config=mock_config)
    events_repo = EventRepository(temp_db)
    stats_repo = StatsRepository(temp_db)
    pairing = PairingManager(mock_config)

    server = DashboardServer(
        bus=event_bus,
        config=mock_config,
        presence_core=presence,
        mode_manager=modes,
        event_repo=events_repo,
        stats_repo=stats_repo,
        pairing_manager=pairing,
        ws=None,
    )

    app = web.Application()
    app.router.add_get("/", server._handle_index)
    app.router.add_get("/api/status", server._handle_status)
    app.router.add_get("/api/events", server._handle_events)
    app.router.add_get("/api/stats", server._handle_stats)
    app.router.add_post("/api/command", server._handle_command)
    app.router.add_get("/api/pairing_qr", server._handle_pairing_qr)
    app.router.add_post("/api/enroll", server._handle_enroll)
    app.router.add_get("/api/clipboard", server._handle_get_clipboard)
    app.router.add_post("/api/clipboard", server._handle_set_clipboard)
    app.router.add_get("/api/files/list", server._handle_file_list)

    async with TestClient(TestServer(app)) as client:
        # 1. Test index page
        resp = await client.get("/")
        assert resp.status == 200

        # 2. Test status endpoint
        resp = await client.get("/api/status")
        assert resp.status == 200
        data = await resp.json()
        assert data["presence"] == "unknown"
        assert data["mode"] == "work"

        # 3. Test switch_mode command
        resp = await client.post("/api/command", json={"action": "switch_mode", "mode": "meeting"})
        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        assert modes.get_current_mode() == "meeting"

        # 4. Test pairing QR endpoint
        resp = await client.get("/api/pairing_qr")
        assert resp.status == 200
        data = await resp.json()
        assert "qr" in data

        # 5. Test stats endpoint
        resp = await client.get("/api/stats")
        assert resp.status == 200

        # 6. Test enroll endpoint with mock frame from vision engine
        import numpy as np
        class MockVision:
            def get_latest_frame(self):
                # Return 200x200 black image (no face, so returns error message safely without crash)
                return np.zeros((200, 200, 3), dtype=np.uint8)

        server._vision = MockVision()
        resp = await client.post("/api/enroll")
        assert resp.status in (400, 200)
        enroll_data = await resp.json()
        assert "ok" in enroll_data

        # 7. Test clipboard endpoint
        clip_resp = await client.post("/api/clipboard", json={"text": "Hello Orbit P2P"})
        assert clip_resp.status == 200
        clip_data = await clip_resp.json()
        assert clip_data["ok"] is True

        # 8. Test file list endpoint
        files_resp = await client.get("/api/files/list")
        assert files_resp.status == 200
        files_data = await files_resp.json()
        assert isinstance(files_data, list)
