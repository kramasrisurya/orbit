"""
Face recognition (enrolled-user verification) using OpenCV SFace (Deep Learning),
face_recognition (dlib), or normalized embeddings.

Stores and queries face encodings from the local SQLite database (face_models table).
Maintains a rolling buffer of results for debounce verification.
"""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
from typing import Any

import cv2
import numpy as np

try:
    from orbit.vision.face_detect import FaceBox
except ImportError:
    from vision.face_detect import FaceBox

try:
    from orbit.db.database import Database
    from orbit.db.repositories import FaceModelRepository
except ImportError:
    try:
        from db.database import Database
        from db.repositories import FaceModelRepository
    except ImportError:
        Database = None
        FaceModelRepository = None

logger = logging.getLogger("orbit.vision.face_recognize")

MODEL_DIR = Path.home() / ".orbit" / "face_models"
OWNER_MODEL_FILE = MODEL_DIR / "owner.enc"
LEGACY_MODEL_FILE = Path.home() / "ORBIT" / "face_models" / "owner.enc"

SFACE_MODEL_FILE = Path(__file__).parent / "face_recognition_sface_2021dec.onnx"
YUNET_MODEL_FILE = Path(__file__).parent / "face_detection_yunet_2023mar.onnx"

BUFFER_SIZE = 5
POSITIVE_THRESHOLD = 3  # 3 of 5 must be positive


class FaceRecognizer:
    """
    Verifies whether a detected face belongs to the enrolled owner by querying
    the local SQLite database and comparing 128-d deep facial embeddings.
    """

    def __init__(self, threshold: float = 0.35, db: Any = None) -> None:
        # SFace cosine similarity metric: ~0.35 threshold ensures high accuracy while accepting natural head pose
        if threshold > 0.5:
            self._threshold = 0.35
        else:
            self._threshold = threshold

        self._db = db
        self._encoding: np.ndarray | None = None
        self._encodings: list[np.ndarray] = []
        self._buffer: deque[bool] = deque(maxlen=BUFFER_SIZE)
        self._landmark_history: deque[list[tuple[float, float]]] = deque(maxlen=8)
        self._enabled = False
        self._sface: cv2.FaceRecognizerSF | None = None
        self._yunet: cv2.FaceDetectorYN | None = None

        self._init_models()
        self.load_model()

    def _init_models(self) -> None:
        """Initialize OpenCV SFace & YuNet neural network backends if present."""
        if SFACE_MODEL_FILE.exists() and hasattr(cv2, "FaceRecognizerSF"):
            try:
                self._sface = cv2.FaceRecognizerSF.create(str(SFACE_MODEL_FILE), "")
                logger.info("FaceRecognizer: SFace deep neural network initialized")
            except Exception:
                logger.exception("Failed to load SFace model")
                self._sface = None

        if YUNET_MODEL_FILE.exists() and hasattr(cv2, "FaceDetectorYN"):
            try:
                self._yunet = cv2.FaceDetectorYN.create(
                    str(YUNET_MODEL_FILE), "", (640, 480), score_threshold=0.4, nms_threshold=0.3
                )
            except Exception:
                self._yunet = None

    def load_model(self) -> None:
        """Load enrolled owner encoding from SQLite database, with disk fallback."""
        raw_bytes: bytes | None = None

        # 1. Query SQLite database first
        try:
            from db.database import Database
            from db.repositories import FaceModelRepository
            db = self._db or Database()
            if self._db is None:
                db.init()
            repo = FaceModelRepository(db)
            raw_bytes = repo.load("owner")
            if raw_bytes:
                logger.info("FaceRecognizer: Loaded owner model directly from SQLite database")
        except Exception:
            logger.debug("Database load not available or table empty")

        # 2. Disk fallback if not yet in SQLite
        if not raw_bytes:
            for p in (OWNER_MODEL_FILE, LEGACY_MODEL_FILE):
                if p.exists():
                    raw_bytes = p.read_bytes()
                    logger.info("FaceRecognizer: Loaded owner model from disk file %s", p)
                    # Sync to SQLite
                    try:
                        from db.database import Database
                        from db.repositories import FaceModelRepository
                        db = self._db or Database()
                        if self._db is None:
                            db.init()
                        repo = FaceModelRepository(db)
                        repo.save("owner", raw_bytes)
                    except Exception:
                        pass
                    break

        if raw_bytes:
            try:
                # SFace features are float32 (128 dims, 512 bytes per template)
                if len(raw_bytes) % 512 == 0 and len(raw_bytes) > 0:
                    n_templates = len(raw_bytes) // 512
                    self._encodings = [
                        np.frombuffer(raw_bytes[i * 512 : (i + 1) * 512], dtype=np.float32).reshape(1, 128)
                        for i in range(n_templates)
                    ]
                    self._encoding = self._encodings[0]
                else:
                    self._encoding = np.frombuffer(raw_bytes, dtype=np.float64)
                    self._encodings = [self._encoding]

                self._enabled = bool(self._encodings)
                logger.info("FaceRecognizer: Owner verification active (%d template(s))", len(self._encodings))
                return
            except Exception:
                logger.exception("Failed to parse face model encoding")

        logger.warning("FaceRecognizer: No enrolled owner model found in database or disk")
        self._enabled = False

    def _extract_feature(self, frame: np.ndarray) -> bytes | None:
        """Extract a 128-d float32 facial feature from a frame."""
        if frame is None or frame.size == 0:
            return None

        # 1. SFace neural feature extraction
        if self._sface is not None and self._yunet is not None:
            h, w = frame.shape[:2]
            self._yunet.setInputSize((w, h))
            _, faces = self._yunet.detect(frame)
            if faces is not None and len(faces) > 0:
                largest = max(faces, key=lambda f: f[2] * f[3])
                aligned = self._sface.alignCrop(frame, largest)
                feat = self._sface.feature(aligned)
                return feat.astype(np.float32).tobytes()

        # 2. Face_recognition dlib fallback
        try:
            import face_recognition
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            locs = face_recognition.face_locations(rgb)
            if locs:
                enc = face_recognition.face_encodings(rgb, [locs[0]])[0]
                return np.asarray(enc, dtype=np.float64).tobytes()
        except Exception:
            pass

        return None

    def enroll(self, frame: np.ndarray, label: str = "owner") -> bool:
        """
        Compute a 128-d deep encoding from the face in the frame
        and persist it to SQLite database and local disk.
        """
        return self.enroll_multiple([frame], label=label)

    def enroll_multiple(self, frames: list[np.ndarray], label: str = "owner") -> bool:
        """
        Compute and store multiple 128-d encodings (multi-template bank) from
        several frames, allowing reliable recognition across natural poses.
        """
        if not frames:
            return False

        try:
            templates: list[bytes] = []
            for frame in frames:
                feat_bytes = self._extract_feature(frame)
                if feat_bytes is not None:
                    templates.append(feat_bytes)

            if not templates:
                logger.warning("Enroll: Failed to extract facial feature from any provided frame")
                return False

            combined_bytes = b"".join(templates)

            # Update in-memory models
            if len(combined_bytes) % 512 == 0:
                n_templates = len(combined_bytes) // 512
                self._encodings = [
                    np.frombuffer(combined_bytes[i * 512 : (i + 1) * 512], dtype=np.float32).reshape(1, 128)
                    for i in range(n_templates)
                ]
                self._encoding = self._encodings[0]
            else:
                self._encoding = np.frombuffer(combined_bytes, dtype=np.float64)
                self._encodings = [self._encoding]
            self._enabled = True

            # Persist to SQLite Database
            try:
                from db.database import Database
                from db.repositories import FaceModelRepository
                db = self._db or Database()
                if self._db is None:
                    db.init()
                repo = FaceModelRepository(db)
                repo.save(label, combined_bytes)
                logger.info("Persisted '%s' model (%d template(s)) to SQLite database", label, len(self._encodings))
            except Exception as e:
                logger.warning("Failed to save to SQLite database: %s", e)

            # Persist to Disk File
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            (MODEL_DIR / f"{label}.enc").write_bytes(combined_bytes)
            logger.info("Enrolled face model for '%s' successfully (%d templates)", label, len(self._encodings))
            return True

        except Exception:
            logger.exception("Face enrollment failed")
            return False

    def recognize(self, frame: np.ndarray, face_box: FaceBox) -> tuple[bool, float]:
        """
        Check whether the face at face_box matches the enrolled owner.
        Returns (is_owner, confidence).
        """
        if not self._enabled or not self._encodings:
            return (False, 0.0)

        try:
            score = 0.0
            is_match = False
            best_cosine = -1.0

            # 1. Use SFace deep metric matching across template bank if available
            if self._sface is not None and self._yunet is not None:
                h, w = frame.shape[:2]
                self._yunet.setInputSize((w, h))
                _, faces = self._yunet.detect(frame)
                if faces is not None and len(faces) > 0:
                    # Find detected face closest to face_box
                    best_face = None
                    min_dist = float("inf")
                    for f in faces:
                        fx, fy, fw, fh = f[:4]
                        d = (fx - face_box.x) ** 2 + (fy - face_box.y) ** 2
                        if d < min_dist:
                            min_dist = d
                            best_face = f

                    if best_face is not None:
                        aligned = self._sface.alignCrop(frame, best_face)
                        live_feat = self._sface.feature(aligned)

                        # Match against all templates in owner bank
                        for enc in self._encodings:
                            try:
                                cos = float(self._sface.match(enc, live_feat, cv2.FaceRecognizerSF_FR_COSINE))
                                if cos > best_cosine:
                                    best_cosine = cos
                            except Exception:
                                pass

                        is_match = best_cosine >= self._threshold
                        score = max(0.0, min(1.0, (best_cosine + 0.1) / 0.6))

                        # Liveness anti-spoof check: verify dynamic micro-motion across frames
                        if face_box.landmarks and len(face_box.landmarks) >= 5:
                            self._landmark_history.append(face_box.landmarks)
                            if len(self._landmark_history) >= 5:
                                ratios = []
                                for lm in self._landmark_history:
                                    re, le, nose, _, _ = lm
                                    eye_dist = ((re[0] - le[0])**2 + (re[1] - le[1])**2)**0.5
                                    eye_center = ((re[0] + le[0]) / 2, (re[1] + le[1]) / 2)
                                    nose_dist = ((nose[0] - eye_center[0])**2 + (nose[1] - eye_center[1])**2)**0.5
                                    if eye_dist > 0:
                                        ratios.append(nose_dist / eye_dist)
                                if len(ratios) >= 5 and float(np.var(ratios)) < 1e-8:
                                    # Static photo / frozen screen spoof detected
                                    logger.warning("Anti-spoofing alert: zero landmark micro-movement detected")
                                    is_match = False
                                    score = 0.15
                                    logger.warning("Anti-spoofing alert: zero landmark micro-movement detected")
                                    is_match = False
                                    score = 0.15

            # 2. Fallback distance calculation
            if not is_match and self._sface is None:
                pad = 10
                x1 = max(0, face_box.x - pad)
                y1 = max(0, face_box.y - pad)
                x2 = min(frame.shape[1], face_box.x + face_box.w + pad)
                y2 = min(frame.shape[0], face_box.y + face_box.h + pad)
                crop = frame[y1:y2, x1:x2]
                if crop.size > 0:
                    try:
                        import face_recognition
                        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                        locs = face_recognition.face_locations(rgb)
                        if locs:
                            enc = face_recognition.face_encodings(rgb, locs)[0]
                            dist = face_recognition.face_distance([self._encoding], enc)[0]
                            is_match = dist <= 0.6
                            score = max(0.0, 1.0 - dist)
                    except Exception:
                        pass

            # Update rolling buffer (debounce)
            self._buffer.append(is_match)
            if len(self._buffer) >= POSITIVE_THRESHOLD:
                positives = sum(self._buffer)
                verified = positives >= POSITIVE_THRESHOLD
                return (verified, score)

            return (is_match, score)

        except Exception:
            logger.exception("Face recognition failed")
            return (False, 0.0)

    @property
    def is_enabled(self) -> bool:
        return self._enabled
