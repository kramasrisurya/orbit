"""
Face recognition (enrolled-user verification) using the face_recognition
library (dlib-based 128-d encodings).

Maintains a rolling buffer of the last 5 results; only emits
USER_RECOGNIZED when 3+ of 5 are positive (debounce).
"""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from vision.face_detect import FaceBox

logger = logging.getLogger("orbit.vision.face_recognize")

MODEL_DIR = Path.home() / "ORBIT" / "face_models"
OWNER_MODEL_FILE = MODEL_DIR / "owner.enc"

BUFFER_SIZE = 5
POSITIVE_THRESHOLD = 3  # 3 of 5 must be positive


def _extract_opencv_embedding(face_crop: np.ndarray) -> np.ndarray:
    """Extract a normalized 128-d facial embedding using OpenCV."""
    gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY) if len(face_crop.shape) == 3 else face_crop
    eq = cv2.equalizeHist(gray)
    resized = cv2.resize(eq, (16, 8), interpolation=cv2.INTER_AREA).astype(np.float64)
    flat = resized.flatten()
    norm = np.linalg.norm(flat)
    if norm > 1e-6:
        flat = flat / norm
    return flat


class FaceRecognizer:
    """
    Verifies whether a detected face belongs to the enrolled owner.

    If no enrolled model exists, recognition is disabled and the system
    runs in "any face" mode (all detected faces count as present).
    """

    def __init__(self, threshold: float = 0.6) -> None:
        self._threshold = threshold
        self._encoding: np.ndarray | None = None
        self._buffer: deque[bool] = deque(maxlen=BUFFER_SIZE)
        self._enabled = False
        self.load_model()

    def load_model(self) -> None:
        """Load the enrolled owner encoding from disk."""
        try:
            if OWNER_MODEL_FILE.exists():
                raw = OWNER_MODEL_FILE.read_bytes()
                self._encoding = np.frombuffer(raw, dtype=np.float64)
                self._enabled = True
                logger.info(
                    "FaceRecognizer: loaded owner model (%d dims)",
                    len(self._encoding),
                )
            else:
                logger.warning(
                    "FaceRecognizer: no enrolled model at %s — "
                    "running in 'any face' mode",
                    OWNER_MODEL_FILE,
                )
                self._enabled = False
        except Exception:
            logger.exception("Failed to load face model")
            self._enabled = False

    def enroll(self, frame: np.ndarray, label: str = "owner") -> bool:
        """
        Compute a 128-d encoding from the largest face in the frame
        and persist it to disk.
        """
        try:
            try:
                import face_recognition
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                locations = face_recognition.face_locations(rgb)
                if not locations:
                    logger.warning("Enroll: no face found in frame")
                    return False
                encoding = face_recognition.face_encodings(rgb, [locations[0]])[0]
                arr = np.asarray(encoding, dtype=np.float64)
            except ImportError:
                # Fallback to OpenCV face detection + normalized embedding
                from vision.face_detect import FaceDetector
                detector = FaceDetector()
                boxes = detector.detect(frame)
                if not boxes:
                    logger.warning("Enroll: no face found in frame (OpenCV)")
                    return False
                # Pick largest face
                largest = max(boxes, key=lambda b: b.w * b.h)
                crop = frame[largest.y:largest.y + largest.h, largest.x:largest.x + largest.w]
                if crop.size == 0:
                    return False
                arr = _extract_opencv_embedding(crop)

            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            target = MODEL_DIR / f"{label}.enc"
            target.write_bytes(arr.tobytes())
            logger.info("Enrolled face model for '%s' → %s", label, target)

            # Activate immediately
            self._encoding = arr
            self._enabled = True
            return True
        except Exception:
            logger.exception("Face enrollment failed")
            return False

    def recognize(self, frame: np.ndarray, face_box: FaceBox) -> tuple[bool, float]:
        """
        Check whether the face at face_box matches the enrolled owner.

        Returns (is_enrolled_user, confidence).
        In "any face" mode (no model), returns (True, 1.0) for any face.
        """
        if not self._enabled or self._encoding is None:
            # Any-face mode
            return (True, 1.0)

        try:
            pad = 10
            x1 = max(0, face_box.x - pad)
            y1 = max(0, face_box.y - pad)
            x2 = min(frame.shape[1], face_box.x + face_box.w + pad)
            y2 = min(frame.shape[0], face_box.y + face_box.h + pad)
            crop = frame[y1:y2, x1:x2]

            if crop.size == 0:
                return (False, 0.0)

            try:
                import face_recognition
                rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                locations = face_recognition.face_locations(rgb)
                if not locations:
                    return (False, 0.0)

                crop_encoding = face_recognition.face_encodings(rgb, locations)[0]
                distance = face_recognition.face_distance([self._encoding], crop_encoding)[0]
                is_match = distance <= self._threshold
                confidence = max(0.0, 1.0 - distance)
            except ImportError:
                crop_encoding = _extract_opencv_embedding(crop)
                distance = float(np.linalg.norm(self._encoding - crop_encoding))
                is_match = distance <= self._threshold
                confidence = max(0.0, 1.0 - (distance / 2.0))

            # Update rolling buffer
            self._buffer.append(is_match)

            # Debounce: require 3+ of last 5 to be positive
            if len(self._buffer) >= POSITIVE_THRESHOLD:
                positives = sum(self._buffer)
                return (positives >= POSITIVE_THRESHOLD, confidence)

            return (is_match, confidence)
        except Exception:
            logger.exception("Face recognition failed")
            return (False, 0.0)

    @property
    def is_enabled(self) -> bool:
        return self._enabled
