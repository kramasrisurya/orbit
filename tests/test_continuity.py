"""
Tests for Universal Control, Universal Clipboard Sync, and File Sharing endpoints.
"""

import pytest
import io
from pathlib import Path
from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web, FormData
from core.event_bus import EventBus
from productivity.clipboard_sync import ClipboardSync
from productivity.universal_control import UniversalControl
from dashboard.server import DashboardServer


@pytest.mark.asyncio
async def test_universal_control_lifecycle(event_bus: EventBus):
    uc = UniversalControl(bus=event_bus, enabled=True)
    assert uc.is_enabled() is True
    assert uc.is_leaped() is False

    uc.set_enabled(False)
    assert uc.is_enabled() is False

    uc.set_enabled(True)
    assert uc.is_enabled() is True


@pytest.mark.asyncio
async def test_clipboard_sync_operations(event_bus: EventBus):
    sync = ClipboardSync(bus=event_bus, ws_server=None)

    received_events = []
    event_bus.subscribe("CLIPBOARD_UPDATED", lambda e: received_events.append(e))

    sync.set_current("Testing Universal Clipboard Sync 2026")
    assert sync.get_current() == "Testing Universal Clipboard Sync 2026"
    assert len(received_events) == 1
    assert received_events[0].payload["text"] == "Testing Universal Clipboard Sync 2026"


@pytest.mark.asyncio
async def test_file_upload_and_download_flow(event_bus: EventBus, mock_config, tmp_path, monkeypatch):
    # Mock user home directory to tmp_path so files are isolated during testing
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    server = DashboardServer(bus=event_bus, config=mock_config)

    app = web.Application()
    app.router.add_post("/api/files/upload", server._handle_file_upload)
    app.router.add_get("/api/files/list", server._handle_file_list)
    app.router.add_get("/api/files/download", server._handle_file_download)

    events_fired = []
    event_bus.subscribe("FILE_TRANSFERRED", lambda e: events_fired.append(e))

    async with TestClient(TestServer(app)) as client:
        # 1. Upload a file
        form = FormData()
        test_content = b"Orbit AirDrop File Sharing Payload 2026"
        form.add_field("file", io.BytesIO(test_content), filename="test_orbit_doc.txt", content_type="text/plain")

        resp = await client.post("/api/files/upload", data=form)
        assert resp.status == 200
        res_json = await resp.json()
        assert res_json["ok"] is True
        assert len(res_json["files"]) == 1
        uploaded_name = res_json["files"][0]["filename"]
        assert "test_orbit_doc" in uploaded_name

        # Verify event was broadcast
        assert len(events_fired) == 1
        assert events_fired[0].payload["filename"] == uploaded_name

        # 2. List files
        list_resp = await client.get("/api/files/list")
        assert list_resp.status == 200
        file_list = await list_resp.json()
        assert any(f["name"] == uploaded_name for f in file_list)

        # 3. Download the uploaded file
        dl_resp = await client.get(f"/api/files/download?file={uploaded_name}")
        assert dl_resp.status == 200
        downloaded_bytes = await dl_resp.read()
        assert downloaded_bytes == test_content
