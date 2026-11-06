"""
Face detection using MediaPipe.

Fast, CPU-friendly bounding-box detection with multi-person support.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger("orbit.vision.face_detect")


@dataclass
class FaceBox:
    x: int
    y: int
    w: int
    h: int
    confidence: float


class FaceDetector:
    """
    Detects faces in a frame using MediaPipe Face Detection.

    Usage:
        detector = FaceDetector()
        boxes = detector.detect(frame)  # list[FaceBox]
    """

    def __init__(self, min_detection_confidence: float = 0.5) -> None:
        self._min_conf = min_detection_confidence
        self._detector = None
        self._load()

    def _load(self) -> None:
        try:
            import mediapipe as mp
            self._mp = mp
            self._detector = mp.solutions.face_detection.FaceDetection(
                model_selection=1,  # full-range (10+ cm)
                min_detection_confidence=self._min_conf,
            )
            self._backend = "mediapipe"
            logger.info("FaceDetector initialized (MediaPipe)")
        except Exception:
            logger.warning("MediaPipe unavailable — falling back to OpenCV CascadeClassifier")
            try:
                cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                self._cascade = cv2.CascadeClassifier(cascade_path)
                self._backend = "opencv"
                self._detector = self._cascade
                logger.info("FaceDetector initialized (OpenCV Haar Cascade)")
            except Exception:
                logger.exception("Failed to initialize OpenCV CascadeClassifier")
                self._detector = None
                self._backend = "none"

    def detect(self, frame: np.ndarray) -> list[FaceBox]:
        """Return all detected faces as FaceBox objects."""
        if self._detector is None:
            return []

        try:
            boxes: list[FaceBox] = []
            h, w = frame.shape[:2]

            if self._backend == "mediapipe":
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = self._detector.process(rgb)
                if results.detections:
                    for det in results.detections:
                        score = det.score[0] if det.score else 0.0
                        if score < self._min_conf:
                            continue
                        bbox = det.location_data.bounding_box
                        x = int(bbox.xmin * w)
                        y = int(bbox.ymin * h)
                        bw = int(bbox.width * w)
                        bh = int(bbox.height * h)
                        x = max(0, min(x, w - 1))
                        y = max(0, min(y, h - 1))
                        bw = max(1, min(bw, w - x))
                        bh = max(1, min(bh, h - y))
                        boxes.append(FaceBox(x=x, y=y, w=bw, h=bh, confidence=score))

            elif self._backend == "opencv":
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = self._cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
                )
                for (x, y, bw, bh) in faces:
                    boxes.append(FaceBox(x=int(x), y=int(y), w=int(bw), h=int(bh), confidence=0.85))

            return boxes
        except Exception:
            logger.exception("Face detection failed")
            return []

    def close(self) -> None:
        if self._detector is not None:
            try:
                self._detector.close()
            except Exception:
                pass
            self._detector = None
