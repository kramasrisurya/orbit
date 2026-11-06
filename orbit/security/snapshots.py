"""
Snapshot capture.

Saves the current webcam frame as a JPEG to
~/ORBIT/security/snapshots/{YYYY-MM-DD}/{HHMMSS}.jpg
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger("orbit.security.snapshots")


class SnapshotCapture:
    """Saves webcam frames as timestamped JPEG snapshots."""

    def __init__(self, config) -> None:
        self._dir = config.security_snapshot_dir

    def capture(self, frame: np.ndarray) -> Path | None:
        """
        Save the frame as a JPEG.
        Returns the file path, or None on failure.
        """
        try:
            now = datetime.now()
            day_dir = self._dir / now.strftime("%Y-%m-%d")
            day_dir.mkdir(parents=True, exist_ok=True)
            path = day_dir / f"{now.strftime('%H%M%S')}.jpg"

            ok = cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                logger.info("Snapshot saved: %s", path)
                return path
            logger.warning("cv2.imwrite failed for snapshot")
            return None
        except Exception:
            logger.exception("Snapshot capture failed")
            return None
