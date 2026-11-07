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
        self._frame_sink = None
        self._multi_person_streak = 0
        self._unauthorized_user_streak = 0
        self._last_owner_seen: float = time.monotonic()
        self._active_stream = False
        self._meeting_mode = False
        self._background_interval_sec: float = getattr(config, "vision_background_interval_sec", 15.0)
        self._last_process_time: float = 0.0
        self._latest_raw_frame: np.ndarray | None = None
        self._camera_paused: bool = False
        self._forced_eco_mode: bool = False

        # Subscribe to dashboard stream requests & mode transitions
        self._bus.subscribe("DASHBOARD_STREAM_STATE", self._on_stream_state)
        self._bus.subscribe("MODE_CHANGED", self._on_mode_changed)
        self._bus.subscribe("FACE_ENROLLED", self._on_face_enrolled)

    def _on_face_enrolled(self, event: OrbitEvent) -> None:
        logger.info("Face enrolled event received — reloading biometric recognition models")
        try:
            self._face_recognizer.load_model()
        except Exception:
            logger.exception("Failed to reload face recognizer model")

    def _on_mode_changed(self, event: OrbitEvent) -> None:
        mode = event.payload.get("mode", "").lower()
        is_meeting = (mode == "meeting")
        if is_meeting != self._meeting_mode:
            self._meeting_mode = is_meeting
            if is_meeting:
                logger.info("Meeting mode active — releasing camera sensor for Zoom/Teams/Meet")
                self._release_camera()
            else:
                logger.info("Meeting mode ended — resuming vision engine")

    def _on_stream_state(self, event: OrbitEvent) -> None:
        active = bool(event.payload.get("active", False))
        self.set_active_stream(active)

    def set_active_stream(self, active: bool) -> None:
        if self._active_stream != active:
            self._active_stream = active
            logger.info("VisionEngine stream state: active=%s (Eco Mode=%s)", active, not active)
            if active:
                self._last_process_time = 0.0  # Immediately start streaming

    def set_frame_sink(self, sink) -> None:
        """Register a frame consumer callback (e.g. for intruder recording)."""
        self._frame_sink = sink

    def get_latest_frame(self) -> np.ndarray | None:
        """Return the latest unannotated camera frame if available."""
        if self._latest_raw_frame is not None:
            return self._latest_raw_frame.copy()
        return None

    def toggle_camera_pause(self) -> bool:
        """Toggle privacy camera pause on/off."""
        return self.set_camera_paused(not self._camera_paused)

    def set_camera_paused(self, paused: bool) -> bool:
        """Pause or resume the optical sensor. When paused, hardware handle is released."""
        if self._camera_paused != paused:
            self._camera_paused = paused
            logger.info("VisionEngine camera paused state: %s", paused)
            if paused:
                self._release_camera()
            self._bus.publish(OrbitEvent(
                type="CAMERA_PAUSE_CHANGED",
                source="vision",
                payload={"paused": paused},
            ))
        return self._camera_paused

    def is_camera_paused(self) -> bool:
        return self._camera_paused

    def toggle_eco_mode(self) -> bool:
        """Toggle forced battery saver / eco mode on/off."""
        return self.set_eco_mode(not self._forced_eco_mode)

    def set_eco_mode(self, enabled: bool) -> bool:
        """Force or unforce low-frequency eco snapshots (15s)."""
        self._forced_eco_mode = enabled
        logger.info("VisionEngine forced eco mode: %s", enabled)
        self._bus.publish(OrbitEvent(
            type="ECO_MODE_CHANGED",
            source="vision",
            payload={"eco": enabled},
        ))
        return self._forced_eco_mode

    def is_eco_mode(self) -> bool:
        return self._forced_eco_mode

    def capture_snapshot(self) -> str | None:
        """Save a high-resolution snapshot to disk and return path."""
        frame = self.get_latest_frame()
        if frame is None:
            return None
        from pathlib import Path
        from datetime import datetime
        snap_dir = Path.home() / "ORBIT" / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        fname = f"snap_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        target = snap_dir / fname
        cv2.imwrite(str(target), frame)
        logger.info("Saved manual snapshot: %s", target)
        return str(target)

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
            if self._meeting_mode or self._camera_paused:
                time.sleep(0.5)
                continue

            if not self._open_camera():
                logger.warning(
                    "Camera not available — retrying in %ds",
                    RETRY_INTERVAL_SEC,
                )
                # Sleep in small increments so we can respond to stop() or meeting mode / pause
                for _ in range(RETRY_INTERVAL_SEC * 2):
                    if not self._running or self._meeting_mode or self._camera_paused:
                        break
                    time.sleep(0.5)
                continue

            self._process_frames()

            self._release_camera()

        # Exit
        self._release_camera()

    def _open_camera(self) -> bool:
        idx = self._config.vision_camera_index
        try:
            import sys
            if sys.platform == "win32":
                self._camera = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                if not self._camera.isOpened():
                    self._camera = cv2.VideoCapture(idx)
            else:
                self._camera = cv2.VideoCapture(idx)

            if self._camera.isOpened():
                logger.info("Camera %d opened", idx)
                return True
            if self._camera is not None:
                self._camera.release()
            self._camera = None
        except Exception:
            logger.exception("Failed to open camera %d", idx)
        return False

    def _process_frames(self) -> None:
        """Main frame-processing loop (runs while camera is open)."""
        assert self._camera is not None
        frame_skip = max(1, self._config.vision_frame_skip)
        consecutive_failures = 0

        while self._running and not self._meeting_mode and not self._camera_paused and self._camera is not None and self._camera.isOpened():
            # If dashboard is closed or eco mode is active, throttle down to eco snapshots (e.g. every 15s)
            is_eco = self._forced_eco_mode or (not self._active_stream)
            if is_eco:
                elapsed = time.time() - self._last_process_time
                if elapsed < self._background_interval_sec:
                    time.sleep(0.5)
                    continue
                # Flush stale buffer in eco mode
                self._camera.grab()

            ret, frame = self._camera.read()
            if not ret or frame is None:
                consecutive_failures += 1
                if consecutive_failures % 10 == 1:
                    logger.warning("Camera read failed (%d consecutive)", consecutive_failures)
                if consecutive_failures >= 15:
                    logger.error("Camera read failed 15 times, reopening camera...")
                    break
                time.sleep(0.1)
                continue

            consecutive_failures = 0
            self._frame_count += 1
            self._last_process_time = time.time()
            self._latest_raw_frame = frame.copy()

            # In active stream mode, skip frames according to frame_skip
            if self._active_stream and self._frame_count % frame_skip != 0:
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
        self._latest_raw_frame = frame.copy()
        if self._frame_sink is not None:
            try:
                self._frame_sink(frame)
            except Exception:
                pass

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

            # Intelligent Classroom & Public Space Filter:
            # Distinguish real shoulder-surfers from distant lecture hall / background bystanders.
            primary_face = max(face_boxes, key=lambda b: b.w * b.h)
            near_faces = [
                b for b in face_boxes
                if b == primary_face or b.w >= 85 or (primary_face.w > 0 and b.w >= 0.5 * primary_face.w)
            ]
            n_near_faces = len(near_faces)

            # Multi-person check based on proximate observers
            if n_near_faces >= self._config.vision_multi_person_min_count:
                self._multi_person_streak += 1
                if self._multi_person_streak >= 5:
                    self._bus.publish_async(OrbitEvent(
                        type=MULTI_PERSON_DETECTED,
                        source="vision",
                        payload={"count": n_near_faces, "frame_b64": self._frame_to_b64(frame)},
                    ))
            else:
                self._multi_person_streak = 0

        # 2-6. Per-face processing
        owner_verified = False
        highest_conf = 0.0

        for i, box in enumerate(face_boxes):
            # Draw sleek modern corner brackets instead of crude green box
            self._draw_modern_reticle(annotated, box.x, box.y, box.w, box.h, color=(255, 255, 255), thickness=2, length=20)

            # 2. Face recognition
            is_owner, conf = self._face_recognizer.recognize(frame, box)
            if is_owner:
                owner_verified = True
                highest_conf = max(highest_conf, conf)
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

        # Check for unauthorized user: face(s) detected at PC but owner is not recognized
        if n_faces > 0:
            if owner_verified:
                self._last_owner_seen = time.monotonic()
                self._unauthorized_user_streak = 0
            else:
                # 10s grace period after owner was last seen to allow for natural head turns / looking down at keyboard
                if time.monotonic() - self._last_owner_seen > 10.0:
                    self._unauthorized_user_streak += 1
                    if self._unauthorized_user_streak >= 30:  # ~3-4 seconds of persistent unknown face
                        self._bus.publish_async(OrbitEvent(
                            type=INTRUDER_ALERT,
                            source="vision",
                            payload={
                                "reason": "unauthorized_user",
                                "faces": n_faces,
                                "confidence": highest_conf,
                                "frame_b64": self._frame_to_b64(frame),
                            },
                        ))
                        self._unauthorized_user_streak = 0
        else:
            self._unauthorized_user_streak = 0

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

        # 7. Dashboard update
        if self._active_stream:
            if self._frame_count % (frame_skip * 2) == 0:
                self._bus.publish_async(OrbitEvent(
                    type=DASHBOARD_UPDATE,
                    source="vision",
                    payload={
                        "frame_b64": self._frame_to_b64(annotated),
                        "faces": n_faces,
                        "fps": self._estimate_fps(),
                        "owner_verified": owner_verified,
                        "confidence": round(highest_conf, 2),
                        "eco_mode": False,
                    },
                ))
        else:
            # Eco mode: lightweight status update without expensive base64 JPEG encoding
            self._bus.publish_async(OrbitEvent(
                type=DASHBOARD_UPDATE,
                source="vision",
                payload={
                    "faces": n_faces,
                    "fps": 0,
                    "owner_verified": owner_verified,
                    "confidence": round(highest_conf, 2),
                    "eco_mode": True,
                },
            ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _draw_modern_reticle(img: np.ndarray, x: int, y: int, w: int, h: int, color=(255, 255, 255), thickness=2, length=22) -> None:
        """Draw sleek, modern corner brackets instead of crude security bounding boxes."""
        l = min(length, w // 3, h // 3)
        # Top-left corner
        cv2.line(img, (x, y), (x + l, y), color, thickness)
        cv2.line(img, (x, y), (x, y + l), color, thickness)
        # Top-right corner
        cv2.line(img, (x + w, y), (x + w - l, y), color, thickness)
        cv2.line(img, (x + w, y), (x + w, y + l), color, thickness)
        # Bottom-left corner
        cv2.line(img, (x, y + h), (x + l, y + h), color, thickness)
        cv2.line(img, (x, y + h), (x, y + h - l), color, thickness)
        # Bottom-right corner
        cv2.line(img, (x + w, y + h), (x + w - l, y + h), color, thickness)
        cv2.line(img, (x + w, y + h), (x + w, y + h - l), color, thickness)

    @staticmethod
    def _frame_to_b64(frame: np.ndarray, quality: int = 60) -> str:
        """Encode a BGR frame as a base64 JPEG string."""
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return base64.b64encode(buf).decode("ascii")

    def _estimate_fps(self) -> float:
        # Rough estimate based on frame count and elapsed time
        # (good enough for the dashboard display)
        return 15.0 / max(1, self._config.vision_frame_skip)
