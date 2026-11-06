"""
Tests for ModeManager.
"""

from unittest.mock import MagicMock
from core.event_bus import (
    EventBus, OrbitEvent, NFC_MODE_TRIGGERED,
    GESTURE_RECOGNIZED, PRESENCE_CHANGED, MODE_CHANGED
)
from core.modes import ModeManager
from core.presence import PresenceState


def test_mode_manager_initial_state(event_bus: EventBus, mock_config):
    mm = ModeManager(bus=event_bus, config=mock_config)
    assert mm.get_current_mode() == "work"


def test_mode_manager_switch_mode(event_bus: EventBus, mock_config):
    mode_events = []
    event_bus.subscribe(MODE_CHANGED, lambda e: mode_events.append(e))

    mm = ModeManager(bus=event_bus, config=mock_config)
    ok = mm.switch_mode("meeting")

    assert ok is True
    assert mm.get_current_mode() == "meeting"
    assert len(mode_events) == 1
    assert mode_events[0].payload["mode"] == "meeting"
    assert mode_events[0].payload["previous_mode"] == "work"


def test_mode_manager_switch_invalid_mode(event_bus: EventBus, mock_config):
    mm = ModeManager(bus=event_bus, config=mock_config)
    ok = mm.switch_mode("party_mode")

    assert ok is False
    assert mm.get_current_mode() == "work"


def test_mode_manager_nfc_trigger(event_bus: EventBus, mock_config):
    mm = ModeManager(bus=event_bus, config=mock_config)

    event_bus.publish(OrbitEvent(
        type=NFC_MODE_TRIGGERED, source="phone", payload={"mode": "home"}
    ))

    assert mm.get_current_mode() == "home"


def test_mode_manager_gesture_trigger(event_bus: EventBus, mock_config):
    mm = ModeManager(bus=event_bus, config=mock_config)

    event_bus.publish(OrbitEvent(
        type=GESTURE_RECOGNIZED, source="vision", payload={"gesture": "thumbs_up"}
    ))

    assert mm.get_current_mode() == "meeting"


def test_mode_manager_presence_away_and_return(event_bus: EventBus, mock_config):
    mm = ModeManager(bus=event_bus, config=mock_config)
    mm.switch_mode("work")

    # User leaves -> presence absent
    event_bus.publish(OrbitEvent(
        type=PRESENCE_CHANGED, source="presence", payload={"state": PresenceState.ABSENT.value}
    ))
    assert mm.get_current_mode() == "away"

    # User returns -> presence high
    event_bus.publish(OrbitEvent(
        type=PRESENCE_CHANGED, source="presence", payload={"state": PresenceState.PRESENT_HIGH.value}
    ))
    assert mm.get_current_mode() == "work"
