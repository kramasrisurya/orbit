"""
ORBIT SQLite database.

Single connection with check_same_thread=False + a threading lock,
since SQLite is the storage engine and all access is local.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("orbit.db.database")

DATA_DIR = Path.home() / "ORBIT" / "data"
DB_PATH = DATA_DIR / "orbit.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    source TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);

CREATE TABLE IF NOT EXISTS daily_stats (
    date TEXT PRIMARY KEY,
    focus_minutes INTEGER NOT NULL DEFAULT 0,
    breaks_taken INTEGER NOT NULL DEFAULT 0,
    posture_alerts INTEGER NOT NULL DEFAULT 0,
    stress_minutes INTEGER NOT NULL DEFAULT 0,
    intruder_alerts INTEGER NOT NULL DEFAULT 0,
    pc_locks INTEGER NOT NULL DEFAULT 0,
    screen_time_min INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS face_models (
    label TEXT PRIMARY KEY,
    encoding BLOB NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intruder_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    snapshot_path TEXT,
    video_path TEXT,
    rssi INTEGER
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports_sent (
    date TEXT PRIMARY KEY,
    sent_at TEXT NOT NULL
);
"""


class Database:
    """
    Thread-safe SQLite wrapper.

    Usage:
        db = Database()
        db.init()
        conn = db.connection  # use inside db.lock
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DB_PATH
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def init(self) -> None:
        """Create the data directory and all tables if they don't exist."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        logger.info("Database initialized at %s", self.path)

    @property
    def connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not initialized — call init() first")
        return self._conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def executemany(self, sql: str, params_list: list[tuple]) -> None:
        with self._lock:
            self._conn.executemany(sql, params_list)
            self._conn.commit()

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
        logger.info("Database closed")
