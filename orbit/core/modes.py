"""
ORBIT Mode Manager.

Manages environment modes (work, meeting, home, presenting, away).
Switches modes via NFC tags, gestures, or presence changes.
Delegates execution to the ModeExecutor.
"""

from __future__ import annotations

import logging
from typing import Any

from core.event_bus import (
    EventBus, OrbitEvent,
    NFC_MODE_TRIGGERED, GESTURE_RECOGNIZED,
    PRESENCE_CHANGED, MODE_CHANGED,
)
from core.presence import PresenceState

logger = logging.getLogger("orbit.core.modes")

VALID_MODES = {
    "entertainment", "study", "coding", "exam",
    "work", "meeting", "home", "presenting", "away"
}


class ModeManager:
    """
    Tracks the current environment mode and orchestrates transitions.

    Subscribes to:
      - NFC_MODE_TRIGGERED → switch to the named mode
      - GESTURE_RECOGNIZED (thumbs_up) → switch to "meeting"
      - PRESENCE_CHANGED (ABSENT) → switch to "away"

    On each transition, calls ModeExecutor.execute(mode_name).
    """

    def __init__(
        self,
        bus: EventBus,
        config,
        mode_executor=None,
        presence_core=None,
    ) -> None:
        self._bus = bus
        self._config = config
        self._mode_executor = mode_executor
        self._presence_core = presence_core

        self._current_mode: str = "work"
        self._previous_mode: str = "work"

        # Subscribe
        self._bus.subscribe(NFC_MODE_TRIGGERED, self._on_nfc)
        self._bus.subscribe(GESTURE_RECOGNIZED, self._on_gesture)
        self._bus.subscribe(PRESENCE_CHANGED, self._on_presence_changed)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def _on_nfc(self, event: OrbitEvent) -> None:
        mode = event.payload.get("mode", "")
        if mode in VALID_MODES:
            logger.info("NFC trigger: switching to %s", mode)
            self.switch_mode(mode)
        else:
            logger.warning("NFC trigger: unknown mode '%s'", mode)

    def _on_gesture(self, event: OrbitEvent) -> None:
        gesture = event.payload.get("gesture", "")
        if gesture == "thumbs_up":
            logger.info("Gesture trigger: thumbs_up → meeting mode")
            self.switch_mode("meeting")

    def _on_presence_changed(self, event: OrbitEvent) -> None:
        state = event.payload.get("state", "")
        if state == PresenceState.ABSENT.value:
            if self._current_mode != "away":
                logger.info("Presence ABSENT → switching to away mode")
                self.switch_mode("away")
        elif state in (
            PresenceState.PRESENT_HIGH.value,
            PresenceState.PRESENT_MEDIUM.value,
        ):
            # User returned — go back to the previous non-away mode
            if self._current_mode == "away" and self._previous_mode != "away":
                logger.info("User returned → restoring %s mode", self._previous_mode)
                self.switch_mode(self._previous_mode)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def switch_mode(self, new_mode: str) -> bool:
        """
        Validate and execute a mode transition.
        Returns True if the mode actually changed.
        """
        if new_mode not in VALID_MODES:
            logger.warning("Cannot switch to invalid mode: %s", new_mode)
            return False

        is_same_mode = (new_mode == self._current_mode)
        if not is_same_mode:
            self._previous_mode = self._current_mode
            self._current_mode = new_mode

            logger.info(
                "Mode change: %s → %s",
                self._previous_mode, new_mode,
            )

            # Update stay-awake overrides based on mode
            if self._presence_core:
                if new_mode == "presenting":
                    self._presence_core.add_stay_awake("presenting")
                else:
                    self._presence_core.remove_stay_awake("presenting")

            # Publish event
            self._bus.publish(OrbitEvent(
                type=MODE_CHANGED,
                source="core",
                payload={
                    "mode": new_mode,
                    "previous_mode": self._previous_mode,
                },
            ))

        # Always delegate to executor (so re-clicking active mode triggers actions like opening Brave / setting volume)
        if self._mode_executor:
            try:
                self._mode_executor.execute(new_mode)
            except Exception:
                logger.exception("ModeExecutor failed for mode '%s'", new_mode)

        return True

    def get_current_mode(self) -> str:
        return self._current_mode

    def get_mode_config(self, mode: str) -> dict[str, Any]:
        return self._config.get_mode_config(mode)

    def get_all_modes(self) -> dict[str, dict[str, Any]]:
        return self._config.modes
