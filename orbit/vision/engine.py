"""
ORBIT Vision Engine.

Opens the webcam, runs the frame-processing pipeline in a background
thread, and publishes events to the EventBus.

Pipeline (every Nth frame, per `frame_skip`):
  1. FaceDetector.detect(frame) → list[FaceBox]
  2. For each FaceBox: FaceRecognizer.recognize(frame, box)
  3. For each FaceBox: GazeTracker.track(frame, box)
  4. GestureRecognizer.recognize(frame) → list[GestureResult]
  5. For each FaceBox: EmotionDetector.detect(frame, box)
  6. For each FaceBox: PostureTracker.track(frame, box)
  7. Publish all resulting events via EventBus.publish_async
  8. Publish DASHBOARD_UPDATE with annotated frame
"""

from __future__ import annotations

import base64
import logging
import threading
import time

import cv2
import numpy as np

from core.event_bus import (
    EventBus, OrbitEvent,
    FACE_DETECTED, FACE_NOT_DETECTED, USER_RECOGNIZED, UNKNOWN_FACE,
    GAZE_CHANGED, GESTURE_RECOGNIZED, MULTI_PERSON_DETECTED,
    EMOTION_DETECTED, POSTURE_ALERT, DASHBOARD_UPDATE,
)
from vision.face_detect import FaceDetector, FaceBox
from vision.face_recognize import FaceRecognizer
from vision.gaze import GazeTracker, GazeDirection
from vision.gestures import GestureRecognizer
from vision.emotion import EmotionDetector, Emotion
from vision.posture import PostureTracker

logger = logging.getLogger("orbit.vision.engine")

RETRY_INTERVAL_SEC = 30


class VisionEngine:
    """
    Background-thread webcam capture + vision processing.

    Thread-safe start/stop. If the camera fails to open, retries
    every 30 seconds.
    """

    def __init__(
        self,
        bus: EventBus,
        config,
    ) -> None:
        self._bus = bus
        self._config = config
        self._running = False
        self._thread: threading.Thread | None = None

        # Sub-processors
        self._face_detector = FaceDetector()
        self._face_recognizer = FaceRecognizer(
            threshold=config.presence_face_recognition_threshold,
        )
        self._gaze_tracker = GazeTracker()
        self._gesture_recognizer = GestureRecognizer(
            debounce_frames=config.vision_gesture_debounce_frames,
        )
        self._emotion_detector = EmotionDetector(
            stability_sec=config.vision_emotion_stability_sec,
        )
        self._posture_tracker = PostureTracker(
            alert_threshold_sec=config.vision_posture_alert_threshold_sec,
        )

        # State
        self._last_gaze: GazeDirection = GazeDirection.UNKNOWN
        self._last_emotion: Emotion = Emotion.NEUTRAL
        self._camera: cv2.VideoCapture | None = None
        self._frame_count = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start the camera thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="vision-engine"
        )
        self._thread.start()
        logger.info("VisionEngine started")

    def stop(self) -> None:
        """Stop the camera thread and release the camera."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self._release_camera()
        self._close_processors()
        logger.info("VisionEngine stopped")

    def _release_camera(self) -> None:
        if self._camera is not None:
            try:
                self._camera.release()
            except Exception:
                pass
            self._camera = None

    def _close_processors(self) -> None:
        for p in (
            self._face_detector, self._face_recognizer,
            self._gaze_tracker, self._gesture_recognizer,
            self._emotion_detector, self._posture_tracker,
        ):
            close = getattr(p, "close", None)
            if close:
                try:
                    close()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def _run_loop(self) -> None:
        while self._running:
            if not self._open_camera():
                logger.warning(
                    "Camera not available — retrying in %ds",
                    RETRY_INTERVAL_SEC,
                )
                # Sleep in small increments so we can respond to stop()
                for _ in range(RETRY_INTERVAL_SEC * 2):
                    if not self._running:
                        return
                    time.sleep(0.5)
                continue

            self._process_frames()

            self._release_camera()

        # Exit
        self._release_camera()

    def _open_camera(self) -> bool:
        idx = self._config.vision_camera_index
        try:
            self._camera = cv2.VideoCapture(idx)
            if self._camera.isOpened():
                logger.info("Camera %d opened", idx)
                return True
            self._camera.release()
            self._camera = None
        except Exception:
            logger.exception("Failed to open camera %d", idx)
        return False

    def _process_frames(self) -> None:
        """Main frame-processing loop (runs while camera is open)."""
        assert self._camera is not None
        frame_skip = max(1, self._config.vision_frame_skip)

        while self._running and self._camera is not None and self._camera.isOpened():
            ret, frame = self._camera.read()
            if not ret:
                logger.warning("Camera read failed")
                time.sleep(0.1)
                continue

            self._frame_count += 1

            # Process every Nth frame
            if self._frame_count % frame_skip != 0:
                continue

            try:
                self._process_frame(frame)
            except Exception:
                logger.exception("Frame processing error")

    # ------------------------------------------------------------------
    # Per-frame processing
    # ------------------------------------------------------------------
    def _process_frame(self, frame: np.ndarray) -> None:
        """Run the full vision pipeline on one frame."""
        annotated = frame.copy()
        frame_skip = max(1, self._config.vision_frame_skip)

        # 1. Face detection
        face_boxes = self._face_detector.detect(frame)
        n_faces = len(face_boxes)

        if n_faces == 0:
            self._bus.publish_async(OrbitEvent(
                type=FACE_NOT_DETECTED,
                source="vision",
                payload={"count": 0},
            ))
        else:
            self._bus.publish_async(OrbitEvent(
                type=FACE_DETECTED,
                source="vision",
                payload={"count": n_faces},
            ))

            # Multi-person check
            if n_faces >= self._config.vision_multi_person_min_count:
                self._bus.publish_async(OrbitEvent(
                    type=MULTI_PERSON_DETECTED,
                    source="vision",
                    payload={"count": n_faces, "frame_b64": self._frame_to_b64(frame)},
                ))

        # 2-6. Per-face processing
        for i, box in enumerate(face_boxes):
            # Draw box on annotated frame
            cv2.rectangle(
                annotated,
                (box.x, box.y),
                (box.x + box.w, box.y + box.h),
                (0, 255, 0), 2,
            )

            # 2. Face recognition
            is_owner, conf = self._face_recognizer.recognize(frame, box)
            if is_owner:
                self._bus.publish_async(OrbitEvent(
                    type=USER_RECOGNIZED,
                    source="vision",
                    payload={"face_index": i, "confidence": conf},
                ))
            else:
                self._bus.publish_async(OrbitEvent(
                    type=UNKNOWN_FACE,
                    source="vision",
                    payload={"face_index": i, "confidence": conf},
                ))

            # 3. Gaze tracking
            gaze = self._gaze_tracker.track(frame, box)
            if gaze != self._last_gaze:
                self._last_gaze = gaze
                self._bus.publish_async(OrbitEvent(
                    type=GAZE_CHANGED,
                    source="vision",
                    payload={"direction": gaze.value},
                ))

            # 5. Emotion detection
            emotion, emo_conf = self._emotion_detector.detect(frame, box)
            if emotion != self._last_emotion:
                self._last_emotion = emotion
                self._bus.publish_async(OrbitEvent(
                    type=EMOTION_DETECTED,
                    source="vision",
                    payload={"emotion": emotion.value, "confidence": emo_conf},
                ))

            # 6. Posture tracking
            metrics = self._posture_tracker.track(frame, box)
            if metrics is not None:
                alert_type, duration = self._posture_tracker.check_alert()
                if alert_type is not None:
                    self._bus.publish_async(OrbitEvent(
                        type=POSTURE_ALERT,
                        source="vision",
                        payload={
                            "type": alert_type,
                            "duration_sec": duration,
                            "tilt_x": metrics.tilt_x,
                            "tilt_y": metrics.tilt_y,
                            "distance_ratio": metrics.distance_ratio,
                        },
                    ))

        # 4. Gesture recognition
        gesture_results = self._gesture_recognizer.recognize(frame)
        for gr in gesture_results:
            if gr.gesture.value != "none":
                self._bus.publish_async(OrbitEvent(
                    type=GESTURE_RECOGNIZED,
                    source="vision",
                    payload={
                        "gesture": gr.gesture.value,
                        "hand": gr.hand,
                        "confidence": gr.confidence,
                    },
                ))
                # Annotate
                cv2.putText(
                    annotated, gr.gesture.value.upper(),
                    (10, 30 + 30 * len(gesture_results)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2,
                )

        # 7. Dashboard update with annotated frame (throttled)
        if self._frame_count % (frame_skip * 2) == 0:
            self._bus.publish_async(OrbitEvent(
                type=DASHBOARD_UPDATE,
                source="vision",
                payload={
                    "frame_b64": self._frame_to_b64(annotated),
                    "faces": n_faces,
                    "fps": self._estimate_fps(),
                },
            ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _frame_to_b64(frame: np.ndarray, quality: int = 60) -> str:
        """Encode a BGR frame as a base64 JPEG string."""
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return base64.b64encode(buf).decode("ascii")

    def _estimate_fps(self) -> float:
        # Rough estimate based on frame count and elapsed time
        # (good enough for the dashboard display)
        return 15.0 / max(1, self._config.vision_frame_skip)
