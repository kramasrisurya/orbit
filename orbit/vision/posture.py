"""
Posture tracking from face mesh landmarks.

Estimates head tilt (Euler angles from the face plane) and head distance
(from face bounding-box size relative to frame). Emits POSTURE_ALERT
when a bad posture condition persists for `posture_alert_threshold_sec`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import cv2
import numpy as np

from vision.face_detect import FaceBox

logger = logging.getLogger("orbit.vision.posture")


@dataclass
class PostureMetrics:
    tilt_x: float  # degrees, sideways tilt (left/right)
    tilt_y: float  # degrees, up/down tilt (chin up/down)
    distance_ratio: float  # 0 = far, 1 = very close (face fills frame)


class PostureTracker:
    """
    Tracks head posture from face mesh landmarks.

    Emits POSTURE_ALERT when a condition persists for
    `posture_alert_threshold_sec`:
      - HUNCHED:   tilt_y > 30°  (looking down)
      - TOO_CLOSE: distance_ratio > 0.8
      - TILTED:    abs(tilt_x) > 30°  (head tilted sideways)
    """

    def __init__(self, alert_threshold_sec: float = 300.0, window: int = 30) -> None:
        self._threshold_sec = alert_threshold_sec
        self._window = window
        self._mesh = None
        self._mp = None
        # Running window of measurements
        self._history: list[PostureMetrics] = []
        # Alert state: which alert type is currently active + since when
        self._active_alert: str | None = None
        self._alert_since: float = 0.0
        self._load()

    def _load(self) -> None:
        try:
            import mediapipe as mp
            self._mp = mp
            self._mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                refine_landmarks=False,
                min_detection_confidence=0.5,
            )
            logger.info("PostureTracker initialized (MediaPipe FaceMesh)")
        except Exception:
            logger.exception("Failed to initialize PostureTracker")
            self._mesh = None

    def track(self, frame: np.ndarray, face_box: FaceBox) -> PostureMetrics | None:
        """
        Compute posture metrics for the current frame.
        Returns PostureMetrics, or None if no face mesh data.
        """
        if self._mesh is None:
            return None

        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self._mesh.process(rgb)

            if not results.multi_face_landmarks:
                return None

            lm = results.multi_face_landmarks[0].landmark
            h, w = frame.shape[:2]

            # --- Distance ratio ---
            # Face height in pixels relative to frame height
            face_h_ratio = face_box.h / h
            # Invert: larger face = closer. Normalize so 0.8 ≈ "too close"
            distance_ratio = min(1.0, face_h_ratio / 0.5)  # 0.5 frame height = max

            # --- Tilt estimation ---
            # Use nose tip, left cheek, right cheek to estimate face plane
            nose = np.array([lm[1].x * w, lm[1].y * h])
            left_cheek = np.array([lm[234].x * w, lm[234].y * h])
            right_cheek = np.array([lm[454].x * w, lm[454].y * h])
            forehead = np.array([lm[10].x * w, lm[10].y * h])
            chin = np.array([lm[152].x * w, lm[152].y * h])

            # tilt_x (sideways): angle of the line between cheeks from horizontal
            cheek_vec = right_cheek - left_cheek
            tilt_x = float(np.degrees(np.arctan2(cheek_vec[1], cheek_vec[0])))

            # tilt_y (up/down): angle of nose-to-chin from vertical
            vertical_vec = chin - forehead
            tilt_y = float(np.degrees(np.arctan2(vertical_vec[0], -vertical_vec[1])))

            metrics = PostureMetrics(
                tilt_x=tilt_x,
                tilt_y=tilt_y,
                distance_ratio=distance_ratio,
            )

            # Maintain running window
            self._history.append(metrics)
            if len(self._history) > self._window:
                self._history.pop(0)

            return metrics
        except Exception:
            logger.exception("Posture tracking failed")
            return None

    def check_alert(self) -> tuple[str | None, float]:
        """
        Check if a posture condition has persisted long enough to alert.
        Returns (alert_type, duration_sec) or (None, 0).
        """
        if not self._history:
            return (None, 0.0)

        # Use the most recent measurement
        m = self._history[-1]
        now = time.monotonic()

        alert_type: str | None = None
        if m.tilt_y > 30:
            alert_type = "HUNCHED"
        elif m.distance_ratio > 0.8:
            alert_type = "TOO_CLOSE"
        elif abs(m.tilt_x) > 30:
            alert_type = "TILTED"

        if alert_type is not None:
            if self._active_alert == alert_type:
                duration = now - self._alert_since
                if duration >= self._threshold_sec:
                    return (alert_type, duration)
            else:
                self._active_alert = alert_type
                self._alert_since = now
        else:
            self._active_alert = None
            self._alert_since = 0.0

        return (None, 0.0)

    def close(self) -> None:
        if self._mesh is not None:
            try:
                self._mesh.close()
            except Exception:
                pass
            self._mesh = None
