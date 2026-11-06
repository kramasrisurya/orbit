"""
ORBIT structured JSON logging.

- Custom JSONFormatter: each record → single-line JSON.
- setup_logger(name): writes to stdout + ~/ORBIT/logs/orbit-{date}.log
- One log file per day, 7-day retention.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from logging import Handler, LogRecord
from pathlib import Path

LOG_DIR = Path.home() / "ORBIT" / "logs"


class JSONFormatter(logging.Formatter):
    """Format a LogRecord as a single-line JSON object."""

    def format(self, record: LogRecord) -> str:
        entry: dict = {
            "ts": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "msg": record.getMessage(),
        }
        # Attach structured data if the record carries an extra "data" field
        if hasattr(record, "data") and record.data:
            entry["data"] = record.data
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


class DailyFileHandler(Handler):
    """
    Writes to ~/ORBIT/logs/orbit-{YYYY-MM-DD}.log.
    Rotates by date (new file each day). Prunes files older than 7 days.
    """

    def __init__(self, log_dir: Path, retention_days: int = 7) -> None:
        super().__init__()
        self.log_dir = log_dir
        self.retention_days = retention_days
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._current_date: str = ""
        self._file = None
        self.setFormatter(JSONFormatter())

    def _today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _open_file(self) -> None:
        date_str = self._today()
        if self._file is not None and date_str == self._current_date:
            return
        # Close old file
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                pass
        self._current_date = date_str
        path = self.log_dir / f"orbit-{date_str}.log"
        self._file = open(path, "a", encoding="utf-8")
        self._prune()

    def _prune(self) -> None:
        """Remove log files older than retention_days."""
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        pattern = re.compile(r"orbit-(\d{4}-\d{2}-\d{2})\.log")
        for f in self.log_dir.iterdir():
            m = pattern.match(f.name)
            if m:
                try:
                    file_date = datetime.strptime(m.group(1), "%Y-%m-%d")
                    if file_date < cutoff:
                        f.unlink(missing_ok=True)
                except ValueError:
                    pass

    def emit(self, record: LogRecord) -> None:
        try:
            self._open_file()
            if self._file is not None:
                msg = self.format(record) + "\n"
                self._file.write(msg)
                self._file.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None
        super().close()


def setup_logger(name: str) -> logging.Logger:
    """
    Configure a logger that writes JSON to stdout and a daily log file.
    Safe to call multiple times for the same name (idempotent).
    """
    lg = logging.getLogger(name)
    if lg.handlers:
        return lg  # already configured

    lg.setLevel(logging.DEBUG)
    lg.propagate = False

    # stdout
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(JSONFormatter())
    lg.addHandler(sh)

    # daily file
    fh = DailyFileHandler(LOG_DIR)
    fh.setLevel(logging.DEBUG)
    lg.addHandler(fh)

    return lg
