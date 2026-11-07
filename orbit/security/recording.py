"""
Intruder recording.

Records the webcam to an MP4 file using cv2.VideoWriter. Runs in a
background thread or accepts pushed frames from the VisionEngine,
stopping automatically after `duration_sec`.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger("orbit.security.recording")


class IntruderRecorder:
    """
    Records the webcam to MP4. Can record from a camera provider or receive
    frames pushed from the primary VisionEngine to avoid device conflicts.

    Usage:
        recorder = IntruderRecorder(config, camera_provider)
        path = recorder.start(30)   # records for 30s, returns path
        ...
        recorder.write_frame(frame) # pushed from vision pipeline
        ...
        path = recorder.stop()       # stop early
    """

    def __init__(self, config, camera_provider: Any = None) -> None:
        """
        Args:
            config: ORBIT Config (for recording_dir, resolution).
            camera_provider: callable that returns a cv2.VideoCapture,
                or camera index (int), or None.
        """
        self._dir = Path(config.security_recording_dir).expanduser() if hasattr(config, "security_recording_dir") else Path("recordings")
        self._camera_provider = camera_provider
        self._running = False
        self._thread: threading.Thread | None = None
        self._path: Path | None = None
        self._writer: cv2.VideoWriter | None = None
        self._lock = threading.Lock()
        self._frames_remaining = 0
        self._captured_count = 0
        self._completion_callback: Any = None

    def set_completion_callback(self, callback: Any) -> None:
        """Set a callback invoked when recording finishes: callback(path)."""
        self._completion_callback = callback

    def start(self, duration_sec: int = 30) -> Path | None:
        """
        Start recording for `duration_sec` seconds.
        Returns the file path immediately.
        """
        with self._lock:
            if self._running:
                logger.warning("Recorder already running")
                return self._path

            now = datetime.now()
            day_dir = self._dir / now.strftime("%Y-%m-%d")
            day_dir.mkdir(parents=True, exist_ok=True)
            self._path = day_dir / f"{now.strftime('%H%M%S')}.mp4"

            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            fps = 15
            size = (640, 480)
            try:
                self._writer = cv2.VideoWriter(str(self._path), fourcc, fps, size)
            except Exception:
                logger.exception("Failed to initialize VideoWriter")
                self._writer = None

            self._frames_remaining = duration_sec * fps
            self._captured_count = 0
            self._running = True
            logger.info("Recording started: %s (%ds)", self._path, duration_sec)

            # Only launch dedicated camera polling thread if camera_provider is a callable
            # that provides a separate capture. If camera_provider is an int or None,
            # frames will be fed via write_frame() to avoid hardware conflicts.
            if callable(self._camera_provider):
                self._thread = threading.Thread(
                    target=self._record_from_provider,
                    args=(duration_sec,),
                    daemon=True,
                    name="intruder-recorder",
                )
                self._thread.start()

            return self._path

    def write_frame(self, frame: np.ndarray) -> None:
        """Feed a frame directly from the main vision pipeline."""
        with self._lock:
            if not self._running or self._writer is None:
                return

            try:
                h, w = frame.shape[:2]
                if (w, h) != (640, 480):
                    frame = cv2.resize(frame, (640, 480))
                self._writer.write(frame)
                self._captured_count += 1
                self._frames_remaining -= 1

                if self._frames_remaining <= 0:
                    self._stop_locked()
            except Exception:
                logger.exception("Error writing frame to recorder")

    def _record_from_provider(self, duration_sec: int) -> None:
        """Background recording loop for dedicated camera provider."""
        fps = 15
        cap = None
        try:
            cap = self._camera_provider()
            if cap is None or not cap.isOpened():
                logger.error("Recorder: camera provider returned closed capture")
                self.stop()
                return

            frames_to_capture = duration_sec * fps
            captured = 0
            while self._running and captured < frames_to_capture:
                ret, frame = cap.read()
                if not ret:
                    break
                self.write_frame(frame)
                captured += 1
        except Exception:
            logger.exception("Recording provider error")
        finally:
            self.stop()

    def _stop_locked(self) -> Path | None:
        self._running = False
        if self._writer is not None:
            try:
                self._writer.release()
            except Exception:
                pass
            self._writer = None
        logger.info("Recording stopped: %s (%d frames)", self._path, self._captured_count)
        if self._completion_callback and self._path:
            try:
                cb = self._completion_callback
                self._completion_callback = None
                threading.Thread(target=cb, args=(self._path,), daemon=True).start()
            except Exception:
                logger.exception("Error running recording completion callback")
        return self._path

    def stop(self) -> Path | None:
        """Stop recording early. Returns the file path."""
        with self._lock:
            path = self._stop_locked()

        if self._thread is not None and self._thread != threading.current_thread():
            self._thread.join(timeout=3)
            self._thread = None
        return path
