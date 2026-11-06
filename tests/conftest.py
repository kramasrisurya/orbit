"""
ORBIT — Test configuration and shared fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

# Ensure orbit/ is on Python path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "orbit"))
sys.path.insert(0, str(REPO_ROOT))

from core.event_bus import EventBus
from db.database import Database
from config import load_config, Config


@pytest.fixture
def event_bus() -> EventBus:
    """Provide a fresh in-memory EventBus."""
    return EventBus()


@pytest.fixture
def temp_db(tmp_path: Path) -> Database:
    """Provide an initialized SQLite database in a temporary directory."""
    db_file = tmp_path / "test_orbit.db"
    db = Database(path=db_file)
    db.init()
    yield db
    db.close()


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
    """Provide a test Config with temporary paths."""
    cfg = load_config()
    cfg.presence_lock_timeout_sec = 2
    cfg.dashboard_port = 8999
    cfg.phone_websocket_port = 8799
    cfg.security_snapshot_dir = str(tmp_path / "snapshots")
    cfg.security_recording_dir = str(tmp_path / "recordings")
    return cfg
