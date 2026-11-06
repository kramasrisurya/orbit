"""
Intruder detector.

Subscribes to MULTI_PERSON_DETECTED. On trigger:
  1. Captures a snapshot
  2. Starts a recording (if configured)
  3. Sends phone notification with snapshot
  4. Logs to DB
  5. Locks the workstation (if intruder_action == "alert_and_lock")

Cooldown: minimum 30 seconds between alerts.
"""

from __future__ import annotations

import base64
import logging
import time
from datetime import datetime
from pathlib import Path

from core.event_bus import EventBus, OrbitEvent, MULTI_PERSON_DETECTED, PC_LOCKED
from security.snapshots import SnapshotCapture
from security.recording import IntruderRecorder
from db.repositories import IntruderRepository
from utils.windows import lock_workstation

logger = logging.getLogger("orbit.security.intruder")

COOLDOWN_SEC = 30


class IntruderDetector:
    """
    Detects and responds to intruders (second person at the PC).
    """

    def __init__(
        self,
        bus: EventBus,
        config,
        notifier=None,
        intruder_repo: IntruderRepository | None = None,
        camera_index: int = 0,
    ) -> None:
        self._bus = bus
        self._config = config
        self._notifier = notifier
        self._repo = intruder_repo
        self._camera_index = camera_index

        self._snapshotter = SnapshotCapture(config)
        self._recorder = IntruderRecorder(config, camera_index)

        self._last_alert_time: float = 0.0

        self._bus.subscribe(MULTI_PERSON_DETECTED, self._on_multi_person)

    def _on_multi_person(self, event: OrbitEvent) -> None:
        now = time.monotonic()
        if now - self._last_alert_time < COOLDOWN_SEC:
            logger.debug("Intruder alert suppressed (cooldown)")
            return

        self._last_alert_time = now
        count = event.payload.get("count", 2)
        logger.warning("INTRUDER DETECTED: %d people in frame", count)

        # 1. Snapshot
        snapshot_path: Path | None = None
        frame_b64 = event.payload.get("frame_b64")
        if frame_b64:
            # Decode the frame from the event payload
            try:
                import cv2
                import numpy as np
                raw = base64.b64decode(frame_b64)
                arr = np.frombuffer(raw, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    snapshot_path = self._snapshotter.capture(frame)
            except Exception:
                logger.exception("Failed to decode frame for snapshot")

        # 2. Recording
        video_path: Path | None = None
        if self._config.security_record_on_intruder:
            try:
                video_path = self._recorder.start(
                    self._config.security_record_duration_sec
                )
            except Exception:
                logger.exception("Failed to start intruder recording")

        # 3. Phone notification
        if self._notifier:
            try:
                snap_data = {}
                if snapshot_path and snapshot_path.exists():
                    snap_bytes = snapshot_path.read_bytes()
                    snap_data["snapshot"] = base64.b64encode(snap_bytes).decode()
                self._notifier.send(
                    "intruder_alert",
                    "⚠️ Intruder Detected",
                    f"Second person at your PC at {datetime.now().strftime('%H:%M')}",
                    snap_data,
                )
            except Exception:
                logger.exception("Failed to send intruder notification")

        # 4. Log to DB
        if self._repo:
            try:
                self._repo.log(
                    timestamp=datetime.now(),
                    snapshot_path=str(snapshot_path) if snapshot_path else None,
                    video_path=str(video_path) if video_path else None,
                    rssi=None,
                )
            except Exception:
                logger.exception("Failed to log intruder alert to DB")

        # 5. Lock workstation
        if self._config.security_intruder_action == "alert_and_lock":
            lock_workstation()
            self._bus.publish(OrbitEvent(
                type=PC_LOCKED,
                source="security",
                payload={"reason": "intruder_detected", "count": count},
            ))

        logger.info(
            "Intruder response complete: snapshot=%s, video=%s, locked=%s",
            snapshot_path, video_path,
            self._config.security_intruder_action == "alert_and_lock",
        )
