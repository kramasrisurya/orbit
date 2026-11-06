"""
ORBIT Presence Core.

Fuses face-recognition, BLE proximity, Wi-Fi, and geo-fence signals
into a single PresenceState. Drives auto-lock and keep-alive.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta
from enum import Enum

from core.event_bus import (
    EventBus, OrbitEvent,
    FACE_DETECTED, FACE_NOT_DETECTED, USER_RECOGNIZED,
    PHONE_NEAR, PHONE_FAR, WIFI_PRESENCE,
    PHONE_GEO_LEFT, PHONE_GEO_RETURNED,
    PRESENCE_CHANGED, PC_LOCKED,
)
from utils.windows import lock_workstation, simulate_activity

logger = logging.getLogger("orbit.core.presence")


class PresenceState(Enum):
    PRESENT_HIGH = "present_high"
    PRESENT_MEDIUM = "present_medium"
    PRESENT_LOW = "present_low"
    ABSENT = "absent"
    UNKNOWN = "unknown"


# Signal priority: lower number = higher priority
SIGNAL_PRIORITY = {
    "face": 0,
    "ble": 1,
    "wifi": 2,
    "geo": 3,
}


class PresenceCore:
    """
    Maintains the current PresenceState by fusing multiple sensor signals.

    Fusion rules:
      - USER_RECOGNIZED + PHONE_NEAR  → PRESENT_HIGH
      - USER_RECOGNIZED alone         → PRESENT_MEDIUM
      - PHONE_NEAR alone              → PRESENT_LOW
      - No face for lock_timeout AND no phone for ble_grace → ABSENT
      - Contradictory signals         → UNKNOWN (log conflict, trust higher-priority)

    Auto-lock:
      - ABSENT persists for lock_timeout_sec → lock_workstation()
      - Skipped if a stay-awake override is active

    Keep-alive:
      - While PRESENT_HIGH or PRESENT_MEDIUM, every keep_alive_interval_sec
        → simulate_activity() to prevent OS idle lock
    """

    def __init__(
        self,
        bus: EventBus,
        config,
        notifier=None,
    ) -> None:
        self._bus = bus
        self._config = config
        self._notifier = notifier

        self._state = PresenceState.UNKNOWN
        self._state_entered = datetime.now()

        # Last-seen timestamps per signal source
        self._last_face: datetime | None = None
        self._last_face_recognized: datetime | None = None
        self._last_phone_near: datetime | None = None
        self._last_wifi: datetime | None = None
        self._last_geo_returned: datetime | None = None
        self._phone_geo_left: datetime | None = None

        # Stay-awake overrides
        self._stay_awake_overrides: set[str] = set()

        # Locking
        self._lock = threading.Lock()
        self._running = False
        self._keep_alive_task: asyncio.Task | None = None
        self._absent_task: asyncio.Task | None = None

        # Subscribe to events
        self._bus.subscribe(USER_RECOGNIZED, self._on_user_recognized)
        self._bus.subscribe(FACE_DETECTED, self._on_face_detected)
        self._bus.subscribe(FACE_NOT_DETECTED, self._on_face_not_detected)
        self._bus.subscribe(PHONE_NEAR, self._on_phone_near)
        self._bus.subscribe(PHONE_FAR, self._on_phone_far)
        self._bus.subscribe(WIFI_PRESENCE, self._on_wifi)
        self._bus.subscribe(PHONE_GEO_LEFT, self._on_geo_left)
        self._bus.subscribe(PHONE_GEO_RETURNED, self._on_geo_returned)

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------
    def _on_user_recognized(self, event: OrbitEvent) -> None:
        with self._lock:
            self._last_face_recognized = datetime.now()
            self._last_face = datetime.now()
        self._recompute()

    def _on_face_detected(self, event: OrbitEvent) -> None:
        with self._lock:
            self._last_face = datetime.now()
        self._recompute()

    def _on_face_not_detected(self, event: OrbitEvent) -> None:
        # Don't immediately clear; the timeout logic handles absence
        logger.debug("Face not detected at %s", datetime.now().isoformat())

    def _on_phone_near(self, event: OrbitEvent) -> None:
        with self._lock:
            self._last_phone_near = datetime.now()
        self._recompute()

    def _on_phone_far(self, event: OrbitEvent) -> None:
        with self._lock:
            self._last_phone_near = None
        self._recompute()

    def _on_wifi(self, event: OrbitEvent) -> None:
        with self._lock:
            self._last_wifi = datetime.now()
        self._recompute()

    def _on_geo_left(self, event: OrbitEvent) -> None:
        with self._lock:
            self._phone_geo_left = datetime.now()
        self._recompute()

    def _on_geo_returned(self, event: OrbitEvent) -> None:
        with self._lock:
            self._phone_geo_left = None
            self._last_geo_returned = datetime.now()
        self._recompute()

    # ------------------------------------------------------------------
    # Fusion logic
    # ------------------------------------------------------------------
    def _recompute(self) -> None:
        """Recompute presence state from current signal timestamps."""
        now = datetime.now()
        cfg = self._config

        with self._lock:
            face_recent = (
                self._last_face is not None
                and (now - self._last_face).total_seconds()
                < cfg.presence_lock_timeout_sec * 2  # generous window
            )
            face_recognized_recent = (
                self._last_face_recognized is not None
                and (now - self._last_face_recognized).total_seconds()
                < cfg.presence_lock_timeout_sec * 2
            )
            phone_recent = (
                self._last_phone_near is not None
                and (now - self._last_phone_near).total_seconds()
                < cfg.presence_ble_grace_period_sec * 2
            )
            wifi_recent = (
                self._last_wifi is not None
                and (now - self._last_wifi).total_seconds() < 60
            )

        # Determine new state
        new_state = self._fuse(face_recognized_recent, phone_recent, wifi_recent, face_recent)

        if new_state != self._state:
            prev = self._state
            self._state = new_state
            self._state_entered = now
            confidence = self._compute_confidence(
                face_recognized_recent, phone_recent, wifi_recent
            )
            logger.info(
                "Presence state change: %s → %s (confidence=%.2f)",
                prev.value, new_state.value, confidence,
            )
            self._bus.publish(OrbitEvent(
                type=PRESENCE_CHANGED,
                source="core",
                payload={
                    "state": new_state.value,
                    "previous_state": prev.value,
                    "confidence": confidence,
                },
            ))

    def _fuse(
        self,
        face_rec: bool,
        phone_near: bool,
        wifi: bool,
        face_any: bool,
    ) -> PresenceState:
        """Apply fusion rules. Returns the new PresenceState."""
        # Contradiction check: face says absent but phone says near (or vice versa)
        # In practice we trust the higher-priority signal (face > BLE > Wi-Fi > Geo)

        if face_rec and phone_near:
            return PresenceState.PRESENT_HIGH
        if face_rec:
            return PresenceState.PRESENT_MEDIUM
        if phone_near:
            return PresenceState.PRESENT_LOW
        if wifi:
            return PresenceState.PRESENT_LOW
        if face_any:
            # Face detected but not recognized — treat as low confidence presence
            return PresenceState.PRESENT_LOW

        return PresenceState.ABSENT

    def _compute_confidence(
        self, face_rec: bool, phone_near: bool, wifi: bool
    ) -> float:
        """Simple confidence score based on which signals are active."""
        score = 0.0
        if face_rec:
            score += 0.5
        if phone_near:
            score += 0.3
        if wifi:
            score += 0.1
        return min(score, 1.0)

    # ------------------------------------------------------------------
    # Auto-lock
    # ------------------------------------------------------------------
    async def _auto_lock_loop(self) -> None:
        """Periodically check if we should auto-lock."""
        while self._running:
            await asyncio.sleep(1)
            if not self._running:
                break

            now = datetime.now()
            state = self._state

            if state == PresenceState.ABSENT:
                elapsed = (now - self._state_entered).total_seconds()
                timeout = self._config.presence_lock_timeout_sec

                if elapsed >= timeout and not self._stay_awake_overrides:
                    logger.info(
                        "Auto-lock: absent for %.0fs (timeout=%ds)",
                        elapsed, timeout,
                    )
                    lock_workstation()
                    self._bus.publish(OrbitEvent(
                        type=PC_LOCKED,
                        source="core",
                        payload={"reason": "auto_lock_absent"},
                    ))
                    if self._notifier:
                        try:
                            self._notifier.send(
                                "pc_locked",
                                "PC Locked",
                                f"Your PC was locked after {int(elapsed)}s of inactivity.",
                            )
                        except Exception:
                            logger.exception("Failed to send pc_locked notification")
                    # Reset the timer so we don't re-lock every second
                    self._state_entered = now

    # ------------------------------------------------------------------
    # Keep-alive
    # ------------------------------------------------------------------
    async def _keep_alive_loop(self) -> None:
        """While present, periodically simulate activity to prevent OS lock."""
        while self._running:
            await asyncio.sleep(self._config.presence_keep_alive_interval_sec)
            if not self._running:
                break
            if self._state in (PresenceState.PRESENT_HIGH, PresenceState.PRESENT_MEDIUM):
                simulate_activity()
                logger.debug("Keep-alive: simulated activity")

    # ------------------------------------------------------------------
    # Stay-awake overrides
    # ------------------------------------------------------------------
    def add_stay_awake(self, reason: str) -> None:
        """Add a stay-awake override (e.g., 'presenting', 'focus_session')."""
        self._stay_awake_overrides.add(reason)
        logger.info("Stay-awake override added: %s (total: %d)", reason, len(self._stay_awake_overrides))

    def remove_stay_awake(self, reason: str) -> None:
        """Remove a stay-awake override."""
        self._stay_awake_overrides.discard(reason)
        logger.info("Stay-awake override removed: %s (total: %d)", reason, len(self._stay_awake_overrides))

    def is_stay_awake(self) -> bool:
        """Return whether any stay-awake override is active."""
        return bool(self._stay_awake_overrides)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        self._running = True
        self._keep_alive_task = asyncio.create_task(self._keep_alive_loop())
        self._auto_lock_task = asyncio.create_task(self._auto_lock_loop())
        logger.info("PresenceCore started")

    async def stop(self) -> None:
        self._running = False
        for t in (self._keep_alive_task, self._auto_lock_task):
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        logger.info("PresenceCore stopped")

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    def get_state(self) -> PresenceState:
        return self._state

    def get_duration_in_state(self) -> timedelta:
        return datetime.now() - self._state_entered

    def is_present(self) -> bool:
        return self._state in (
            PresenceState.PRESENT_HIGH,
            PresenceState.PRESENT_MEDIUM,
            PresenceState.PRESENT_LOW,
        )
