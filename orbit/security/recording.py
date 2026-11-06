"""
Intruder recording.

Records the webcam to an MP4 file using cv2.VideoWriter. Runs in a
background thread and stops automatically after `duration_sec`.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path

import cv2

logger = logging.getLogger("orbit.security.recording")


class IntruderRecorder:
    """
    Records the webcam to MP4 in a background thread.

    Usage:
        recorder = IntruderRecorder(config, camera_provider)
        path = recorder.start(30)   # records for 30s, returns path
        # or
        recorder.start(30)
        ...
        path = recorder.stop()       # stop early
    """

    def __init__(self, config, camera_provider) -> None:
        """
        Args:
            config: ORBIT Config (for recording_dir, resolution).
            camera_provider: callable that returns a cv2.VideoCapture,
                or None. The recorder opens its own capture.
        """
        self._dir = config.security_recording_dir
        self._camera_provider = camera_provider
        self._running = False
        self._thread: threading.Thread | None = None
        self._path: Path | None = None
        self._writer: cv2.VideoWriter | None = None
        self._lock = threading.Lock()

    def start(self, duration_sec: int = 30) -> Path | None:
        """
        Start recording for `duration_sec` seconds in a background thread.
        Returns the file path immediately (recording happens in background).
        """
        with self._lock:
            if self._running:
                logger.warning("Recorder already running")
                return self._path

            now = datetime.now()
            day_dir = self._dir / now.strftime("%Y-%m-%d")
            day_dir.mkdir(parents=True, exist_ok=True)
            self._path = day_dir / f"{now.strftime('%H%M%S')}.mp4"

            self._running = True
            self._thread = threading.Thread(
                target=self._record,
                args=(duration_sec,),
                daemon=True,
                name="intruder-recorder",
            )
            self._thread.start()
            logger.info("Recording started: %s (%ds)", self._path, duration_sec)
            return self._path

    def _record(self, duration_sec: int) -> None:
        """Background recording loop."""
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        fps = 15
        size = (640, 480)

        cap = None
        try:
            cap = cv2.VideoCapture(self._camera_provider()
                                   if callable(self._camera_provider)
                                   else 0)
            if not cap.isOpened():
                # Try default camera
                cap = cv2.VideoCapture(0)
                if not cap.isOpened():
                    logger.error("Recorder: cannot open camera")
                    self._running = False
                    return

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])

            self._writer = cv2.VideoWriter(
                str(self._path), fourcc, fps, size
            )
            if not self._writer.isOpened():
                logger.error("Recorder: cannot open VideoWriter")
                self._running = False
                return

            frames_to_capture = duration_sec * fps
            captured = 0
            while self._running and captured < frames_to_capture:
                ret, frame = cap.read()
                if not ret:
                    break
                self._writer.write(frame)
                captured += 1

        except Exception:
            logger.exception("Recording error")
        finally:
            self._running = False
            if self._writer is not None:
                self._writer.release()
                self._writer = None
            if cap is not None:
                cap.release()
            logger.info("Recording stopped: %s (%d frames)", self._path, captured)

    def stop(self) -> Path | None:
        """Stop recording early. Returns the file path."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        return self._path
