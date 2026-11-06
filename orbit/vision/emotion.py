"""
Heuristic emotion detection from face mesh landmarks.

This is NOT a deep-learning model. It uses geometric heuristics
(brow position, mouth width, eye openness) to produce a rough
"vibe check." Documented as such — not clinical.

Classes: NEUTRAL, FOCUSED, STRESSED, TIRED, HAPPY.
Only emits EMOTION_DETECTED on state change, after
`emotion_stability_sec` of consistent classification.
"""

from __future__ import annotations

import logging
import time
from enum import Enum

import cv2
import numpy as np

from vision.face_detect import FaceBox

logger = logging.getLogger("orbit.vision.emotion")


class Emotion(Enum):
    NEUTRAL = "neutral"
    FOCUSED = "focused"
    STRESSED = "stressed"
    TIRED = "tired"
    HAPPY = "happy"


# Face mesh landmark indices
LEFT_BROW = [70, 63]
RIGHT_BROW = [336, 296]
LEFT_EYE_TOP = 159
LEFT_EYE_BOTTOM = 145
RIGHT_EYE_TOP = 386
RIGHT_EYE_BOTTOM = 374
MOUTH_LEFT = 61
MOUTH_RIGHT = 291
MOUTH_TOP = 0
MOUTH_BOTTOM = 176
NOSE_BRIDGE = 6


class EmotionDetector:
    """
    Heuristic emotion classifier using face mesh geometry.

    Emits EMOTION_DETECTED only on state change, after the new emotion
    has been consistent for `stability_sec` seconds.
    """

    def __init__(self, stability_sec: float = 5.0) -> None:
        self._stability_sec = stability_sec
        self._mesh = None
        self._mp = None
        self._current = Emotion.NEUTRAL
        self._candidate = Emotion.NEUTRAL
        self._candidate_since: float = 0.0
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
            logger.info("EmotionDetector initialized (heuristic, MediaPipe FaceMesh)")
        except (ImportError, ModuleNotFoundError):
            logger.warning("MediaPipe not installed — EmotionDetector disabled")
            self._mesh = None
        except Exception:
            logger.exception("Failed to initialize EmotionDetector")
            self._mesh = None

    def detect(self, frame: np.ndarray, face_box: FaceBox) -> tuple[Emotion, float]:
        """
        Classify the current emotion.
        Returns (emotion, confidence).
        """
        if self._mesh is None:
            return (self._current, 0.0)

        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self._mesh.process(rgb)

            if not results.multi_face_landmarks:
                return (self._current, 0.0)

            lm = results.multi_face_landmarks[0].landmark
            h, w = frame.shape[:2]

            # Convert to pixel coords
            def px(idx: int) -> tuple[float, float]:
                return (lm[idx].x * w, lm[idx].y * h)

            emotion, conf = self._classify(px)

            # Stability
            now = time.monotonic()
            if emotion != self._candidate:
                self._candidate = emotion
                self._candidate_since = now
            elif now - self._candidate_since >= self._stability_sec:
                if emotion != self._current:
                    logger.info("Emotion changed: %s → %s", self._current.value, emotion.value)
                    self._current = emotion

            return (self._current, conf)
        except Exception:
            logger.exception("Emotion detection failed")
            return (self._current, 0.0)

    def _classify(self, px) -> tuple[Emotion, float]:
        """
        Geometric heuristics:
        - Eye openness: distance between eye top/bottom landmarks
        - Brow position: brow y relative to eye y (raised = happy, furrowed = stressed)
        - Mouth width: distance between mouth corners (wide = happy)
        """
        try:
            # Eye openness (normalized by eye width)
            le_top = px(LEFT_EYE_TOP)
            le_bot = px(LEFT_EYE_BOTTOM)
            le_open = abs(le_top[1] - le_bot[1])
            re_top = px(RIGHT_EYE_TOP)
            re_bot = px(RIGHT_EYE_BOTTOM)
            re_open = abs(re_top[1] - re_bot[1])
            avg_eye_open = (le_open + re_open) / 2.0

            # Eye width for normalization
            le_w = abs(px(LEFT_EYE_TOP)[0] - px(133)[0])  # approximate
            if le_w < 1:
                le_w = 1
            eye_open_ratio = avg_eye_open / le_w

            # Brow position: lower brow y = raised brow
            lb = px(LEFT_BROW[0])
            rb = px(RIGHT_BROW[0])
            brow_y = (lb[1] + rb[1]) / 2.0
            eye_y = (le_top[1] + re_top[1]) / 2.0
            brow_offset = (eye_y - brow_y) / max(le_w, 1)  # + = raised

            # Mouth width
            ml = px(MOUTH_LEFT)
            mr = px(MOUTH_RIGHT)
            mouth_w = abs(ml[0] - mr[0])
            mouth_ratio = mouth_w / max(le_w * 2, 1)  # relative to face width

            # --- Classification ---
            # TIRED: eyes very narrow
            if eye_open_ratio < 0.15:
                return (Emotion.TIRED, 0.6)

            # STRESSED: furrowed brows (brow close to/above eye line) + narrow mouth
            if brow_offset < 0.1 and mouth_ratio < 0.3:
                return (Emotion.STRESSED, 0.6)

            # HAPPY: raised brows + wide mouth
            if brow_offset > 0.25 and mouth_ratio > 0.45:
                return (Emotion.HAPPY, 0.7)

            # FOCUSED: eyes wide open, neutral mouth, neutral brows
            if eye_open_ratio > 0.35 and 0.25 < mouth_ratio < 0.4:
                return (Emotion.FOCUSED, 0.5)

            return (Emotion.NEUTRAL, 0.5)
        except (IndexError, ZeroDivisionError):
            return (Emotion.NEUTRAL, 0.0)

    @property
    def current(self) -> Emotion:
        return self._current

    def close(self) -> None:
        if self._mesh is not None:
            try:
                self._mesh.close()
            except Exception:
                pass
            self._mesh = None
