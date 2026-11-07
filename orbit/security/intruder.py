"""
Intruder and unauthorized user detector.

Subscribes to:
  - MULTI_PERSON_DETECTED (secondary observers)
  - INTRUDER_ALERT (someone other than the owner using the PC)

On trigger:
  1. Captures a crisp photographic snapshot
  2. Copies snapshot to Downloads and pushes file directly to companion phone
  3. Sends high-priority phone alert with photo attached
  4. Records video clip and automatically transmits to phone upon completion
  5. Workstation remains active (no lock, per owner preference)
"""

from __future__ import annotations

import asyncio
import base64
import logging
import shutil
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

from core.event_bus import EventBus, OrbitEvent, MULTI_PERSON_DETECTED, INTRUDER_ALERT
from security.snapshots import SnapshotCapture
from security.recording import IntruderRecorder
from db.repositories import IntruderRepository

logger = logging.getLogger("orbit.security.intruder")

COOLDOWN_SEC = 20


class IntruderDetector:
    """
    Detects and responds to intruders and unauthorized users.
    """

    def __init__(
        self,
        bus: EventBus,
        config,
        notifier=None,
        intruder_repo: IntruderRepository | None = None,
        camera_index: int = 0,
        phone_server=None,
        vision=None,
    ) -> None:
        self._bus = bus
        self._config = config
        self._notifier = notifier
        self._repo = intruder_repo
        self._camera_index = camera_index
        self._phone_server = phone_server
        self._vision = vision

        self._snapshotter = SnapshotCapture(config)
        self._recorder = IntruderRecorder(config, camera_index)

        self._last_alert_time: float = 0.0

        self._bus.subscribe(MULTI_PERSON_DETECTED, self._on_intruder_event)
        self._bus.subscribe(INTRUDER_ALERT, self._on_intruder_event)

    def record_frame(self, frame) -> None:
        """Push a frame to the active recorder if recording is in progress."""
        self._recorder.write_frame(frame)

    def _on_intruder_event(self, event: OrbitEvent) -> None:
        now = time.monotonic()
        if now - self._last_alert_time < COOLDOWN_SEC:
            logger.debug("Intruder alert suppressed (cooldown)")
            return

        self._last_alert_time = now
        reason = event.payload.get("reason", "multi_person" if event.type == MULTI_PERSON_DETECTED else "unauthorized_user")
        count = event.payload.get("count", event.payload.get("faces", 1))

        if reason == "unauthorized_user":
            logger.warning("UNAUTHORIZED USER DETECTED at workstation!")
            title = "⚠️ Unauthorized Person on Laptop!"
            body = f"Someone other than the owner is currently using your laptop! ({datetime.now().strftime('%H:%M:%S')})"
        else:
            logger.warning("INTRUDER / MULTI-PERSON DETECTED: %d people in frame", count)
            title = "⚠️ Secondary Observer Detected!"
            body = f"{count} people detected in front of your laptop! ({datetime.now().strftime('%H:%M:%S')})"

        # 1. Snapshot
        snapshot_path: Path | None = None
        frame_b64 = event.payload.get("frame_b64")
        frame = None

        if frame_b64:
            try:
                import cv2
                import numpy as np
                raw = base64.b64decode(frame_b64)
                arr = np.frombuffer(raw, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            except Exception:
                logger.exception("Failed to decode frame from event payload")

        if frame is None and self._vision is not None:
            try:
                frame = self._vision.get_latest_frame()
            except Exception:
                pass

        if frame is not None:
            try:
                snapshot_path = self._snapshotter.capture(frame)
            except Exception:
                logger.exception("Failed to capture snapshot")

        # 2. Push snapshot file to phone (so it saves directly into phone Downloads)
        download_url = ""
        target_snap: Path | None = None
        if snapshot_path and snapshot_path.exists():
            try:
                downloads_dir = Path.home() / "Downloads"
                downloads_dir.mkdir(parents=True, exist_ok=True)
                target_snap = downloads_dir / snapshot_path.name
                shutil.copy2(snapshot_path, target_snap)

                if self._phone_server:
                    from phone.pairing import _get_local_ip
                    local_ip = _get_local_ip()
                    download_url = f"http://{local_ip}:8080/api/files/download?file={urllib.parse.quote(target_snap.name)}"
                    loop = getattr(self._phone_server, "_loop", None)
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            self._phone_server.broadcast(
                                "file_incoming",
                                {
                                    "filename": target_snap.name,
                                    "url": download_url,
                                    "size": target_snap.stat().st_size,
                                }
                            ),
                            loop
                        )
            except Exception:
                logger.exception("Failed to prepare snapshot for phone download")

        # 3. Recording (push video when done)
        video_path: Path | None = None
        if self._config.security_record_on_intruder:
            try:
                def _on_video_done(vpath: Path | None) -> None:
                    if vpath and vpath.exists() and self._phone_server:
                        try:
                            downloads_dir = Path.home() / "Downloads"
                            downloads_dir.mkdir(parents=True, exist_ok=True)
                            target_v = downloads_dir / vpath.name
                            shutil.copy2(vpath, target_v)

                            from phone.pairing import _get_local_ip
                            local_ip = _get_local_ip()
                            v_url = f"http://{local_ip}:8080/api/files/download?file={urllib.parse.quote(target_v.name)}"
                            loop = getattr(self._phone_server, "_loop", None)
                            if loop and loop.is_running():
                                asyncio.run_coroutine_threadsafe(
                                    self._phone_server.broadcast(
                                        "file_incoming",
                                        {
                                            "filename": target_v.name,
                                            "url": v_url,
                                            "size": target_v.stat().st_size,
                                        }
                                    ),
                                    loop
                                )
                                logger.info("Pushed intruder video to phone: %s", target_v.name)
                        except Exception:
                            logger.exception("Failed to push intruder video to phone")

                self._recorder.set_completion_callback(_on_video_done)
                video_duration = min(getattr(self._config, "security_record_duration_sec", 10), 10)
                video_path = self._recorder.start(video_duration)
            except Exception:
                logger.exception("Failed to start intruder recording")

        # 4. Phone notification with photo payload
        if self._notifier:
            try:
                snap_data = {
                    "reason": reason,
                    "url": download_url,
                }
                if snapshot_path and snapshot_path.exists():
                    snap_bytes = snapshot_path.read_bytes()
                    snap_data["snapshot"] = base64.b64encode(snap_bytes).decode()
                    snap_data["filename"] = snapshot_path.name

                self._notifier.send(
                    "intruder_alert",
                    title,
                    body,
                    snap_data,
                )
            except Exception:
                logger.exception("Failed to send intruder notification")

        # 4b. Offsite Webhook Dispatch
        webhook_url = getattr(self._config, "security_webhook_url", None)
        if webhook_url:
            self._dispatch_webhook(webhook_url, snapshot_path, count, reason)

        # 5. Log to DB
        if self._repo:
            try:
                self._repo.log(
                    timestamp=datetime.now(),
                    snapshot_path=str(snapshot_path) if snapshot_path else None,
                    video_path=str(video_path) if video_path else None,
                    rssi=None,
                )
            except Exception:
                logger.exception("Failed to log intruder alert to DB")

        # 6. Laptop locking explicitly disabled per user requirement ("turning off laptop is not needed")
        logger.info(
            "Intruder response complete: snapshot=%s, video=%s, laptop remains active",
            snapshot_path, video_path
        )

    def _dispatch_webhook(self, url: str, snapshot_path: Path | None, count: int, reason: str) -> None:
        """Asynchronously dispatch intruder alert to offsite webhook (Discord / Telegram / Slack / generic)."""
        import threading
        import urllib.request
        import json

        def _send() -> None:
            try:
                b64_snap = ""
                if snapshot_path and snapshot_path.exists():
                    b64_snap = base64.b64encode(snapshot_path.read_bytes()).decode()

                payload = {
                    "content": f"🚨 **ORBIT Alert**: Unauthorized activity ({reason}, count={count}) detected at workstation at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    "username": "Orbit Security Node",
                    "event": "intruder_detected",
                    "reason": reason,
                    "count": count,
                    "timestamp": datetime.now().isoformat(),
                    "snapshot_b64": b64_snap[:100] + "..." if b64_snap else None,
                }

                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json", "User-Agent": "Orbit-Security/1.0"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    logger.info("Intruder webhook dispatched successfully (HTTP %d)", resp.status)
            except Exception:
                logger.warning("Failed to dispatch intruder webhook to %s", url)

        threading.Thread(target=_send, daemon=True, name="webhook-dispatcher").start()
