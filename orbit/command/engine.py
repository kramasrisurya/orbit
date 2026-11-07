"""
ORBIT Command Engine.

Subscribes to all command-triggering events on the EventBus and maps
them to action functions:

  - GESTURE_RECOGNIZED → config.gestures lookup → action
  - PHONE_SHAKE        → 1=screenshot, 2=lock, 3=next_app
  - PHONE_REMOTE_COMMAND → action string mapping
  - NFC_MODE_TRIGGERED → ModeManager.switch_mode

Sensitive actions pause for phone approval (via ApprovalManager)
before executing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from core.event_bus import (
    EventBus, OrbitEvent,
    GESTURE_RECOGNIZED, PHONE_SHAKE, PHONE_REMOTE_COMMAND,
    NFC_MODE_TRIGGERED,
)
try:
    from orbit.command import windows_api
except ImportError:
    from command import windows_api
from utils import windows

logger = logging.getLogger("orbit.command.engine")

# Actions that require phone approval before executing
SENSITIVE_ACTIONS = {"lock", "launch:powerpoint"}


class CommandEngine:
    """
    Maps incoming events to system actions.

    All actions are logged. Sensitive actions require approval from the
    phone (with a timeout that defaults to denial).
    """

    def __init__(
        self,
        bus: EventBus,
        config,
        mode_manager=None,
        approval_manager=None,
    ) -> None:
        self._bus = bus
        self._config = config
        self._mode_manager = mode_manager
        self._approval = approval_manager

        self._bus.subscribe(GESTURE_RECOGNIZED, self._on_gesture)
        self._bus.subscribe(PHONE_SHAKE, self._on_shake)
        self._bus.subscribe(PHONE_REMOTE_COMMAND, self._on_remote)
        self._bus.subscribe(NFC_MODE_TRIGGERED, self._on_nfc)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def _on_gesture(self, event: OrbitEvent) -> None:
        gesture = event.payload.get("gesture", "")
        action = self._config.gestures.get(gesture)
        if action is None:
            logger.debug("Gesture '%s' has no mapped action", gesture)
            return
        logger.info("Gesture: %s → %s", gesture, action)
        self._execute(action, source=f"gesture:{gesture}")

    def _on_shake(self, event: OrbitEvent) -> None:
        count = int(event.payload.get("count", 1))
        # Log shake events without executing disruptive lock/screenshot actions on accidental phone motion
        logger.info("Phone shake detected: count=%d (auto-lock and screenshot actions disabled)", count)

    def _on_remote(self, event: OrbitEvent) -> None:
        action = event.payload.get("action", "")
        if not action:
            return
        logger.info("Phone remote command: %s", action)
        self._execute(action, source="phone_remote")

    def _on_nfc(self, event: OrbitEvent) -> None:
        mode = event.payload.get("mode", "")
        if self._mode_manager:
            self._mode_manager.switch_mode(mode)
        else:
            logger.warning("NFC mode '%s' — no ModeManager available", mode)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def _execute(self, action: str, source: str) -> None:
        """
        Execute an action string, with an approval gate for sensitive
        actions. Schedules the async approval flow on the event loop.
        """
        # Actions triggered directly from paired phone remote or phone shake do not require phone self-approval
        if action in SENSITIVE_ACTIONS and self._approval is not None and not source.startswith("phone") and not source.startswith("shake"):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self._execute_with_approval(action, source))
                else:
                    loop.run_until_complete(self._execute_with_approval(action, source))
                return
            except RuntimeError:
                # No loop (called from a thread) — run inline with a new loop
                logger.debug("No running loop; running approval inline")

        self._run_action(action, source)

    async def _execute_with_approval(self, action: str, source: str) -> None:
        """Wait for phone approval, then execute (or skip if denied)."""
        assert self._approval is not None
        try:
            granted = await self._approval.approve(
                f"{action} (triggered by {source})"
            )
        except Exception:
            logger.exception("Approval flow failed for '%s'", action)
            return

        if granted:
            logger.info("Approved: %s", action)
            self._run_action(action, source)
        else:
            logger.warning("Denied/timeout: %s — action not executed", action)

    def _run_action(self, action: str, source: str) -> None:
        """Dispatch an action string to its implementation."""
        try:
            if action == "screenshot":
                path = windows_api.take_screenshot()
                if path:
                    self._bus.publish(OrbitEvent(
                        type="ACTION_EXECUTED", source="command",
                        payload={"action": action, "result": str(path)},
                    ))

            elif action == "lock":
                windows.lock_workstation()
                self._bus.publish(OrbitEvent(
                    type="PC_LOCKED", source="command",
                    payload={"reason": action, "trigger": source},
                ))

            elif action == "next_app":
                windows.send_input_event("alt+tab")

            elif action == "click":
                # Click at the current mouse position
                windows.send_input_event("click")

            elif action == "meeting_mode":
                if self._mode_manager:
                    self._mode_manager.switch_mode("meeting")
                else:
                    logger.warning("meeting_mode: no ModeManager")

            elif action.startswith("mode:") or action.startswith("switch_mode:"):
                target_mode = action.split(":", 1)[1]
                if self._mode_manager:
                    self._mode_manager.switch_mode(target_mode)
                else:
                    logger.warning("switch_mode: no ModeManager")

            elif action in ("entertainment", "study", "coding", "exam", "work", "meeting", "home", "away", "presenting"):
                if self._mode_manager:
                    self._mode_manager.switch_mode(action)
                else:
                    logger.warning("mode switch: no ModeManager")

            elif action.startswith("launch:"):
                app = action.split(":", 1)[1]
                windows_api.launch_app(app)

            elif action == "desktop":
                windows_api.minimize_all()

            elif action == "mute":
                windows_api.mute_system()

            elif action == "unmute":
                windows_api.unmute_system()

            elif action == "vol_up":
                windows.send_input_event("volume_up")

            elif action == "vol_down":
                windows.send_input_event("volume_down")

            elif action == "focus_start":
                self._bus.publish(OrbitEvent(
                    type="FOCUS_SESSION_START", source="command",
                    payload={"trigger": source},
                ))

            elif action == "focus_end":
                self._bus.publish(OrbitEvent(
                    type="FOCUS_SESSION_END", source="command",
                    payload={"trigger": source},
                ))

            elif action in ("pause_camera", "resume_camera", "toggle_camera"):
                self._bus.publish(OrbitEvent(
                    type="COMMAND", source="phone_remote",
                    payload={"action": action, "paused": True if action == "pause_camera" else (False if action == "resume_camera" else None)},
                ))

            else:
                logger.warning("Unknown action: %s", action)
                return

            logger.info("Action executed: %s (source: %s)", action, source)
        except Exception:
            logger.exception("Action '%s' failed", action)
