"""
Hand gesture recognition using MediaPipe Hands (21 landmarks per hand).

Classifies: PALM_OPEN, FIST, WAVE, THUMBS_UP, TWO_FINGER_CIRCLE, POINT, NONE.
A gesture must be stable for `debounce_frames` consecutive frames before
it is emitted.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

import cv2
import numpy as np

logger = logging.getLogger("orbit.vision.gestures")


class Gesture(Enum):
    PALM_OPEN = "palm_open"
    FIST = "fist"
    WAVE = "wave"
    THUMBS_UP = "thumbs_up"
    TWO_FINGER_CIRCLE = "two_finger_circle"
    POINT = "point"
    NONE = "none"


# MediaPipe Hands landmark indices
THUMB_CMC = 1
THUMB_MCP = 2
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_TIP = 12
RING_MCP = 13
RING_PIP = 14
RING_TIP = 16
PINKY_MCP = 17
PINKY_PIP = 18
PINKY_TIP = 20
WRIST = 0


@dataclass
class GestureResult:
    gesture: Gesture
    hand: str  # "left" | "right"
    confidence: float


class GestureRecognizer:
    """
    Recognizes hand gestures from video frames.

    Each gesture must be stable for `debounce_frames` consecutive frames
    before it is emitted. WAVE is detected as PALM_OPEN + lateral movement
    over 3 consecutive frames.
    """

    def __init__(self, debounce_frames: int = 3) -> None:
        self._debounce = debounce_frames
        self._hands = None
        self._mp = None
        # Per-hand debounce state
        self._hand_history: dict[str, deque[Gesture]] = {
            "left": deque(maxlen=debounce_frames),
            "right": deque(maxlen=debounce_frames),
        }
        # For wave detection: track palm x-position over last 3 frames
        self._palm_x_history: dict[str, deque[float]] = {
            "left": deque(maxlen=3),
            "right": deque(maxlen=3),
        }
        self._load()

    def _load(self) -> None:
        try:
            import mediapipe as mp
            self._mp = mp
            self._hands = mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=2,
                min_detection_confidence=0.6,
            )
            logger.info("GestureRecognizer initialized (MediaPipe Hands)")
        except (ImportError, ModuleNotFoundError):
            logger.warning("MediaPipe not installed — GestureRecognizer disabled")
            self._hands = None
        except Exception:
            logger.exception("Failed to initialize GestureRecognizer")
            self._hands = None

    def recognize(self, frame: np.ndarray) -> list[GestureResult]:
        """
        Detect hands and classify gestures.
        Returns a list of GestureResult for hands that passed debounce.
        """
        if self._hands is None:
            return []

        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self._hands.process(rgb)

            output: list[GestureResult] = []

            if results.multi_hands:
                for handedness, landmarks in zip(
                    results.multi_handedness,
                    results.multi_hand_landmarks,
                ):
                    label = handedness.classification[0]
                    # MediaPipe flips left/right (mirror image)
                    hand = "left" if label.label == "Right" else "right"
                    score = label.score

                    pts = [
                        (lm.x, lm.y, lm.z)
                        for lm in landmarks.landmark
                    ]

                    base = self._classify(pts)
                    wave = self._check_wave(hand, pts)
                    final = wave if wave else base

                    # Debounce
                    hist = self._hand_history[hand]
                    hist.append(final)
                    if len(hist) == self._debounce and len(set(hist)) == 1:
                        output.append(GestureResult(
                            gesture=final,
                            hand=hand,
                            confidence=score,
                        ))

            return output
        except Exception:
            logger.exception("Gesture recognition failed")
            return []

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------
    def _classify(self, pts: list[tuple[float, float, float]]) -> Gesture:
        """Classify a single hand's landmark set into a base gesture."""
        try:
            # Helper: is fingertip "above" (further from wrist in y) its PIP?
            # In image coords, y increases downward, so "extended" = tip.y < pip.y
            def extended(tip_idx: int, pip_idx: int) -> bool:
                return pts[tip_idx][1] < pts[pip_idx][1]

            index_ext = extended(INDEX_TIP, INDEX_PIP)
            middle_ext = extended(MIDDLE_TIP, MIDDLE_PIP)
            ring_ext = extended(RING_TIP, RING_PIP)
            pinky_ext = extended(PINKY_TIP, PINKY_PIP)
            thumb_ext = pts[THUMB_TIP][0] > pts[THUMB_MCP][0]  # thumb to the side

            # TWO_FINGER_CIRCLE: index+thumb tips close, other 3 extended
            d_idx_thumb = self._dist(pts[INDEX_TIP], pts[THUMB_TIP])
            d_ref = self._dist(pts[INDEX_MCP], pts[MIDDLE_MCP])
            if d_idx_thumb < 0.5 * d_ref and middle_ext and ring_ext and pinky_ext:
                return Gesture.TWO_FINGER_CIRCLE

            # THUMBS_UP: thumb tip above index MCP, others curled
            if (
                pts[THUMB_TIP][1] < pts[INDEX_MCP][1]
                and not index_ext and not middle_ext
                and not ring_ext and not pinky_ext
            ):
                return Gesture.THUMBS_UP

            # POINT: index extended, all others curled
            if index_ext and not middle_ext and not ring_ext and not pinky_ext:
                return Gesture.POINT

            # FIST: all 5 fingertips below their PIPs (curled)
            if not index_ext and not middle_ext and not ring_ext and not pinky_ext:
                return Gesture.FIST

            # PALM_OPEN: all 5 extended
            if index_ext and middle_ext and ring_ext and pinky_ext and thumb_ext:
                return Gesture.PALM_OPEN

            return Gesture.NONE
        except (IndexError, TypeError):
            return Gesture.NONE

    def _check_wave(self, hand: str, pts: list[tuple[float, float, float]]) -> Gesture | None:
        """
        WAVE = PALM_OPEN + lateral hand movement > threshold over 3 frames.
        """
        if self._classify(pts) != Gesture.PALM_OPEN:
            self._palm_x_history[hand].clear()
            return None

        # Use wrist x as the hand's lateral position
        x = pts[WRIST][0]
        hist = self._palm_x_history[hand]
        hist.append(x)

        if len(hist) == 3:
            xs = list(hist)
            lateral = max(xs) - min(xs)
            # Threshold in normalized coords (~5% of frame width)
            if lateral > 0.05:
                return Gesture.WAVE
        return None

    @staticmethod
    def _dist(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
        return float(np.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2))

    def close(self) -> None:
        if self._hands is not None:
            try:
                self._hands.close()
            except Exception:
                pass
            self._hands = None
