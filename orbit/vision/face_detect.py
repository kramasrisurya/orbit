"""
Face detection using YuNet (modern neural network), MediaPipe, and OpenCV Cascades.

Robust, CPU-friendly bounding-box detection with support for profile, tilted,
and backlit faces.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger("orbit.vision.face_detect")

YUNET_MODEL_FILE = Path(__file__).parent / "face_detection_yunet_2023mar.onnx"


@dataclass
class FaceBox:
    x: int
    y: int
    w: int
    h: int
    confidence: float
    landmarks: list[tuple[float, float]] | None = None


class FaceDetector:
    """
    Detects faces in a frame using:
      1. OpenCV YuNet (high accuracy, neural network)
      2. MediaPipe (if installed)
      3. OpenCV Cascades (frontal, profile, and upper-body fallback)
    """

    def __init__(self, min_detection_confidence: float = 0.3) -> None:
        self._min_conf = min_detection_confidence
        self._detector = None
        self._backend = "none"
        self._load()

    def _load(self) -> None:
        # 1. Try OpenCV YuNet (lightweight ONNX model)
        if YUNET_MODEL_FILE.exists() and hasattr(cv2, "FaceDetectorYN"):
            try:
                self._detector = cv2.FaceDetectorYN.create(
                    str(YUNET_MODEL_FILE),
                    "",
                    (640, 480),
                    score_threshold=self._min_conf,
                    nms_threshold=0.3,
                )
                self._backend = "yunet"
                logger.info("FaceDetector initialized (OpenCV YuNet ONNX)")
                return
            except Exception:
                logger.exception("Failed to initialize YuNet")

        # 2. Try MediaPipe
        try:
            import mediapipe as mp
            self._mp = mp
            self._detector = mp.solutions.face_detection.FaceDetection(
                model_selection=1,
                min_detection_confidence=self._min_conf,
            )
            self._backend = "mediapipe"
            logger.info("FaceDetector initialized (MediaPipe)")
            return
        except Exception:
            pass

        # 3. Fallback to OpenCV Haar Cascades
        try:
            cascade_dir = cv2.data.haarcascades
            self._cascade_frontal = cv2.CascadeClassifier(cascade_dir + "haarcascade_frontalface_alt2.xml")
            if self._cascade_frontal.empty():
                self._cascade_frontal = cv2.CascadeClassifier(cascade_dir + "haarcascade_frontalface_default.xml")
            self._cascade_profile = cv2.CascadeClassifier(cascade_dir + "haarcascade_profileface.xml")
            self._cascade_upper = cv2.CascadeClassifier(cascade_dir + "haarcascade_upperbody.xml")
            self._backend = "opencv_cascade"
            logger.info("FaceDetector initialized (OpenCV Multi-Cascade)")
        except Exception:
            logger.exception("Failed to initialize OpenCV Cascades")
            self._detector = None
            self._backend = "none"

    def detect(self, frame: np.ndarray) -> list[FaceBox]:
        """Return all detected faces as FaceBox objects."""
        if frame is None or frame.size == 0:
            return []

        try:
            boxes: list[FaceBox] = []
            h, w = frame.shape[:2]

            if self._backend == "yunet":
                self._detector.setInputSize((w, h))
                _, faces = self._detector.detect(frame)
                if faces is not None:
                    for f in faces:
                        fx = max(0, min(int(f[0]), w - 1))
                        fy = max(0, min(int(f[1]), h - 1))
                        fw = max(1, min(int(f[2]), w - fx))
                        fh = max(1, min(int(f[3]), h - fy))
                        score = float(f[-1])
                        # Filter out tiny noise and boundary artifacts
                        if fw < 50 or fh < 50 or score < 0.6:
                            continue
                        landmarks = [
                            (float(f[4]), float(f[5])),   # right eye
                            (float(f[6]), float(f[7])),   # left eye
                            (float(f[8]), float(f[9])),   # nose
                            (float(f[10]), float(f[11])), # right mouth
                            (float(f[12]), float(f[13])), # left mouth
                        ]
                        boxes.append(FaceBox(x=fx, y=fy, w=fw, h=fh, confidence=score, landmarks=landmarks))

            elif self._backend == "mediapipe":
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

            elif self._backend == "opencv_cascade":
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                # Frontal face
                f_front = self._cascade_frontal.detectMultiScale(
                    gray, scaleFactor=1.08, minNeighbors=4, minSize=(45, 45)
                )
                for (x, y, bw, bh) in f_front:
                    boxes.append(FaceBox(x=int(x), y=int(y), w=int(bw), h=int(bh), confidence=0.85))

                # If no frontal face detected, check profile
                if not boxes and not self._cascade_profile.empty():
                    f_prof = self._cascade_profile.detectMultiScale(
                        gray, scaleFactor=1.08, minNeighbors=3, minSize=(45, 45)
                    )
                    for (x, y, bw, bh) in f_prof:
                        boxes.append(FaceBox(x=int(x), y=int(y), w=int(bw), h=int(bh), confidence=0.75))

                    if not boxes:
                        # Check flipped profile (other direction)
                        gray_flip = cv2.flip(gray, 1)
                        f_prof_flip = self._cascade_profile.detectMultiScale(
                            gray_flip, scaleFactor=1.08, minNeighbors=3, minSize=(45, 45)
                        )
                        for (x, y, bw, bh) in f_prof_flip:
                            orig_x = w - (x + bw)
                            boxes.append(FaceBox(x=int(orig_x), y=int(y), w=int(bw), h=int(bh), confidence=0.75))

                # If still no face, check upper body presence
                if not boxes and not self._cascade_upper.empty():
                    f_upper = self._cascade_upper.detectMultiScale(
                        gray, scaleFactor=1.08, minNeighbors=3, minSize=(60, 60)
                    )
                    for (x, y, bw, bh) in f_upper:
                        # Estimate head position at top third of upper body box
                        head_h = int(bh * 0.45)
                        head_w = int(bw * 0.6)
                        head_x = int(x + (bw - head_w) / 2)
                        head_y = int(y)
                        boxes.append(FaceBox(x=head_x, y=head_y, w=head_w, h=head_h, confidence=0.65))

            return boxes
        except Exception:
            logger.exception("Face detection failed")
            return []

    def close(self) -> None:
        if self._detector is not None:
            try:
                close = getattr(self._detector, "close", None)
                if close:
                    close()
            except Exception:
                pass
