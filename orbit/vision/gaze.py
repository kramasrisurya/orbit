"""
Gaze tracking using MediaPipe Face Mesh (468 landmarks).

Estimates where the user is looking relative to the screen using
iris-to-eye-corner ratios. Only emits GAZE_CHANGED on actual direction
change, after 1 second of stability.
"""

from __future__ import annotations

import logging
import time
from enum import Enum

import cv2
import numpy as np

from vision.face_detect import FaceBox

logger = logging.getLogger("orbit.vision.gaze")


class GazeDirection(Enum):
    AT_SCREEN = "at_screen"
    AWAY_LEFT = "away_left"
    AWAY_RIGHT = "away_right"
    DOWN = "down"
    UP = "up"
    UNKNOWN = "unknown"


# Face mesh landmark indices (MediaPipe)
NOSE_TIP = 1
LEFT_EYE_OUTER = 33
LEFT_EYE_INNER = 133
LEFT_IRIS = 468 + 273  # left iris center (refined landmark set)
RIGHT_EYE_OUTER = 263
RIGHT_EYE_INNER = 362
RIGHT_IRIS = 468 + 473  # right iris center


class GazeTracker:
    """
    Tracks the user's gaze direction from face mesh landmarks.

    Emits GAZE_CHANGED only when the direction actually changes,
    and only after the new direction has been stable for 1 second.
    """

    STABILITY_SEC = 1.0

    def __init__(self) -> None:
        self._mesh = None
        self._mp = None
        self._current = GazeDirection.UNKNOWN
        self._candidate = GazeDirection.UNKNOWN
        self._candidate_since: float = 0.0
        self._load()

    def _load(self) -> None:
        try:
            import mediapipe as mp
            self._mp = mp
            self._mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                refine_landmarks=True,  # enables iris landmarks
                min_detection_confidence=0.5,
            )
            logger.info("GazeTracker initialized (MediaPipe FaceMesh)")
        except Exception:
            logger.exception("Failed to initialize GazeTracker")
            self._mesh = None

    def track(self, frame: np.ndarray, face_box: FaceBox) -> GazeDirection:
        """
        Compute gaze direction for the face at face_box.
        Returns the current (stable) GazeDirection.
        """
        if self._mesh is None:
            return GazeDirection.UNKNOWN

        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self._mesh.process(rgb)

            if not results.multi_face_landmarks:
                return self._current

            landmarks = results.multi_face_landmarks[0].landmark

            # Use the first face (we track the primary user)
            lm = landmarks

            def pt(idx: int) -> tuple[float, float]:
                return (lm[idx].x, lm[idx].y)

            # Compute iris positions relative to eye corners
            direction = self._classify(pt)

            # Stability check
            now = time.monotonic()
            if direction != self._candidate:
                self._candidate = direction
                self._candidate_since = now
            elif now - self._candidate_since >= self.STABILITY_SEC:
                if direction != self._current:
                    self._current = direction
                    logger.debug("Gaze changed → %s", direction.value)

            return self._current
        except Exception:
            logger.exception("Gaze tracking failed")
            return self._current

    def _classify(self, pt) -> GazeDirection:
        """
        Classify gaze from iris positions.

        For each eye, compute the iris position as a ratio along the
        eye axis (inner corner → outer corner). A ratio near 0.5 means
        the iris is centered (looking at screen). Shifts indicate
        left/right gaze. Vertical shift of the nose/eyes indicates up/down.
        """
        try:
            # Left eye axis
            le_outer = pt(LEFT_EYE_OUTER)
            le_inner = pt(LEFT_EYE_INNER)
            le_iris = pt(LEFT_IRIS)

            # Right eye axis
            re_outer = pt(RIGHT_EYE_OUTER)
            re_inner = pt(RIGHT_EYE_INNER)
            re_iris = pt(RIGHT_IRIS)

            # Horizontal ratio: 0 = inner, 1 = outer, 0.5 = center
            def h_ratio(outer, inner, iris):
                dx = outer[0] - inner[0]
                if abs(dx) < 1e-6:
                    return 0.5
                return (iris[0] - inner[0]) / dx

            lh = h_ratio(le_outer, le_inner, le_iris)
            rh = h_ratio(re_outer, re_inner, re_iris)
            avg_h = (lh + rh) / 2.0

            # Vertical: compare iris y to eye axis midpoint y
            def v_offset(outer, inner, iris):
                mid_y = (outer[1] + inner[1]) / 2.0
                eye_h = abs(outer[1] - inner[1])
                if eye_h < 1e-6:
                    return 0.0
                return (iris[1] - mid_y) / eye_h

            lv = v_offset(le_outer, le_inner, le_iris)
            rv = v_offset(re_outer, re_inner, re_iris)
            avg_v = (lv + rv) / 2.0

            # Thresholds (tunable)
            H_THRESH = 0.12
            V_THRESH = 0.35

            if avg_v > V_THRESH:
                return GazeDirection.DOWN
            if avg_v < -V_THRESH:
                return GazeDirection.UP
            if avg_h < 0.5 - H_THRESH:
                return GazeDirection.AWAY_LEFT
            if avg_h > 0.5 + H_THRESH:
                return GazeDirection.AWAY_RIGHT
            return GazeDirection.AT_SCREEN
        except (IndexError, ZeroDivisionError):
            return GazeDirection.UNKNOWN

    @property
    def current(self) -> GazeDirection:
        return self._current

    def close(self) -> None:
        if self._mesh is not None:
            try:
                self._mesh.close()
            except Exception:
                pass
            self._mesh = None
