"""
Tests for SQLite Database and Repositories.
"""

from datetime import datetime
from db.database import Database
from db.repositories import (
    EventRepository, StatsRepository, IntruderRepository,
    FaceModelRepository, SettingsRepository
)
from core.event_bus import OrbitEvent, FACE_DETECTED


def test_db_initialization(temp_db: Database):
    assert temp_db.connection is not None
    rows = temp_db.query("SELECT name FROM sqlite_master WHERE type='table'")
    table_names = {r["name"] for r in rows}
    assert "events" in table_names
    assert "daily_stats" in table_names
    assert "face_models" in table_names
    assert "intruder_alerts" in table_names


def test_event_repository(temp_db: Database):
    repo = EventRepository(temp_db)
    event = OrbitEvent(
        type=FACE_DETECTED, source="vision", payload={"confidence": 0.99}
    )
    repo.log(event)

    events = repo.query(limit=10)
    assert len(events) == 1
    assert events[0]["type"] == FACE_DETECTED
    assert events[0]["source"] == "vision"


def test_stats_repository(temp_db: Database):
    repo = StatsRepository(temp_db)
    date_str = datetime.now().strftime("%Y-%m-%d")

    repo.increment(date_str, "focus_minutes", 25)
    repo.increment(date_str, "breaks_taken", 1)

    daily = repo.get_daily(date_str)
    assert daily["focus_minutes"] == 25
    assert daily["breaks_taken"] == 1
    assert daily["intruder_alerts"] == 0


def test_face_model_repository(temp_db: Database):
    repo = FaceModelRepository(temp_db)
    raw_encoding = b"mock-128-byte-encoding-data"

    repo.save("owner", raw_encoding)
    loaded = repo.load("owner")
    assert loaded == raw_encoding

    assert repo.load("non_existent") is None


def test_intruder_repository(temp_db: Database):
    repo = IntruderRepository(temp_db)
    repo.log(snapshot_path="/tmp/snap1.jpg", video_path="/tmp/vid1.mp4", rssi=-65)

    alerts = repo.get_recent(limit=5)
    assert len(alerts) == 1
    assert alerts[0]["snapshot_path"] == "/tmp/snap1.jpg"
    assert alerts[0]["rssi"] == -65


def test_settings_repository(temp_db: Database):
    repo = SettingsRepository(temp_db)
    repo.set("camera_index", "1")
    assert repo.get("camera_index") == "1"
    assert repo.get("non_existent", default="0") == "0"
