"""
ORBIT data repositories.

Thin, typed wrappers over the Database connection for each table.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, date

from core.event_bus import OrbitEvent
from db.database import Database

logger = logging.getLogger("orbit.db.repositories")


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
class EventRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def log(self, event: OrbitEvent) -> None:
        self._db.execute(
            "INSERT INTO events (ts, type, source, payload) VALUES (?, ?, ?, ?)",
            (
                event.timestamp.isoformat(),
                event.type,
                event.source,
                json.dumps(event.payload, default=str),
            ),
        )

    def query(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        sql = "SELECT ts, type, source, payload FROM events WHERE 1=1"
        params: list = []
        if start:
            sql += " AND ts >= ?"
            params.append(start.isoformat())
        if end:
            sql += " AND ts <= ?"
            params.append(end.isoformat())
        if event_type:
            sql += " AND type = ?"
            params.append(event_type)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)

        rows = self._db.query(sql, tuple(params))
        results = []
        for r in rows:
            try:
                payload = json.loads(r["payload"])
            except (json.JSONDecodeError, TypeError):
                payload = {}
            results.append({
                "ts": r["ts"],
                "type": r["type"],
                "source": r["source"],
                "payload": payload,
            })
        return results

    def purge_older_than(self, days: int) -> int:
        cutoff = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        from datetime import timedelta
        cutoff = cutoff - timedelta(days=days)
        cur = self._db.execute("DELETE FROM events WHERE ts < ?", (cutoff.isoformat(),))
        return cur.rowcount if cur.rowcount else 0


# ---------------------------------------------------------------------------
# Daily stats
# ---------------------------------------------------------------------------
class StatsRepository:
    FIELDS = (
        "focus_minutes", "breaks_taken", "posture_alerts",
        "stress_minutes", "intruder_alerts", "pc_locks", "screen_time_min",
    )

    def __init__(self, db: Database) -> None:
        self._db = db

    def _ensure_row(self, d: str) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO daily_stats (date) VALUES (?)", (d,)
        )

    def get_daily(self, d: str) -> dict:
        self._ensure_row(d)
        rows = self._db.query("SELECT * FROM daily_stats WHERE date = ?", (d,))
        if rows:
            return {k: rows[0][k] for k in rows[0].keys()}
        return {"date": d, **{f: 0 for f in self.FIELDS}}

    def upsert_daily(self, d: str, stats: dict) -> None:
        self._ensure_row(d)
        sets = []
        params = []
        for k, v in stats.items():
            if k in self.FIELDS:
                sets.append(f"{k} = ?")
                params.append(int(v))
        if sets:
            params.append(d)
            self._db.execute(
                f"UPDATE daily_stats SET {', '.join(sets)} WHERE date = ?",
                tuple(params),
            )

    def get_history(self, days: int) -> list[dict]:
        rows = self._db.query(
            "SELECT * FROM daily_stats ORDER BY date DESC LIMIT ?", (days,)
        )
        return [{k: r[k] for k in r.keys()} for r in rows]

    def increment(self, d: str, field: str, amount: int = 1) -> None:
        if field not in self.FIELDS:
            raise ValueError(f"Unknown stats field: {field}")
        self._ensure_row(d)
        self._db.execute(
            f"UPDATE daily_stats SET {field} = {field} + ? WHERE date = ?",
            (amount, d),
        )


# ---------------------------------------------------------------------------
# Face models
# ---------------------------------------------------------------------------
class FaceModelRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, label: str, encoding: bytes) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO face_models (label, encoding, created_at) "
            "VALUES (?, ?, ?)",
            (label, encoding, datetime.now().isoformat()),
        )

    def load(self, label: str) -> bytes | None:
        rows = self._db.query(
            "SELECT encoding FROM face_models WHERE label = ?", (label,)
        )
        if rows:
            return rows[0]["encoding"]
        return None


# ---------------------------------------------------------------------------
# Intruder alerts
# ---------------------------------------------------------------------------
class IntruderRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def log(
        self,
        snapshot_path: str | None = None,
        video_path: str | None = None,
        rssi: int | None = None,
        timestamp: datetime | None = None,
    ) -> int:
        ts = (timestamp or datetime.now()).isoformat()
        cur = self._db.execute(
            "INSERT INTO intruder_alerts (ts, snapshot_path, video_path, rssi) "
            "VALUES (?, ?, ?, ?)",
            (ts, snapshot_path, video_path, rssi),
        )
        return cur.lastrowid

    def list_all(self, limit: int = 50) -> list[dict]:
        rows = self._db.query(
            "SELECT id, ts, snapshot_path, video_path, rssi "
            "FROM intruder_alerts ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        return [{k: r[k] for k in r.keys()} for r in rows]

    get_recent = list_all

    def purge_older_than(self, days: int) -> int:
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cur = self._db.execute("DELETE FROM intruder_alerts WHERE ts < ?", (cutoff,))
        return cur.rowcount if cur.rowcount else 0


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class SettingsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str, default: str | None = None) -> str | None:
        rows = self._db.query("SELECT value FROM settings WHERE key = ?", (key,))
        return rows[0]["value"] if rows else default

    def set(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )

    def get_all(self) -> dict[str, str]:
        rows = self._db.query("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in rows}


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
class ReportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def mark_sent(self, d: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO reports_sent (date, sent_at) VALUES (?, ?)",
            (d, datetime.now().isoformat()),
        )

    def was_sent_today(self, d: str) -> bool:
        rows = self._db.query("SELECT 1 FROM reports_sent WHERE date = ?", (d,))
        return len(rows) > 0
