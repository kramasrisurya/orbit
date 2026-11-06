"""
Tests for PresenceCore.
"""

from unittest.mock import MagicMock
from core.event_bus import (
    EventBus, OrbitEvent, USER_RECOGNIZED, FACE_DETECTED,
    PHONE_NEAR, PHONE_FAR, PRESENCE_CHANGED
)
from core.presence import PresenceCore, PresenceState


def test_presence_initial_state(event_bus: EventBus, mock_config):
    core = PresenceCore(bus=event_bus, config=mock_config)
    assert core.get_state() == PresenceState.UNKNOWN


def test_presence_face_and_phone_high(event_bus: EventBus, mock_config):
    changed_events = []
    event_bus.subscribe(PRESENCE_CHANGED, lambda e: changed_events.append(e))

    core = PresenceCore(bus=event_bus, config=mock_config)

    # Publish face recognized and phone near
    event_bus.publish(OrbitEvent(type=USER_RECOGNIZED, source="vision"))
    event_bus.publish(OrbitEvent(type=PHONE_NEAR, source="phone"))

    assert core.get_state() == PresenceState.PRESENT_HIGH
    assert len(changed_events) > 0
    assert changed_events[-1].payload["state"] == "present_high"


def test_presence_face_alone_medium(event_bus: EventBus, mock_config):
    core = PresenceCore(bus=event_bus, config=mock_config)

    event_bus.publish(OrbitEvent(type=USER_RECOGNIZED, source="vision"))
    assert core.get_state() == PresenceState.PRESENT_MEDIUM


def test_presence_phone_alone_low(event_bus: EventBus, mock_config):
    core = PresenceCore(bus=event_bus, config=mock_config)

    event_bus.publish(OrbitEvent(type=PHONE_NEAR, source="phone"))
    assert core.get_state() == PresenceState.PRESENT_LOW


def test_presence_phone_far_clears_phone(event_bus: EventBus, mock_config):
    core = PresenceCore(bus=event_bus, config=mock_config)

    event_bus.publish(OrbitEvent(type=PHONE_NEAR, source="phone"))
    assert core.get_state() == PresenceState.PRESENT_LOW

    event_bus.publish(OrbitEvent(type=PHONE_FAR, source="phone"))
    assert core.get_state() == PresenceState.ABSENT


def test_stay_awake_override(event_bus: EventBus, mock_config):
    core = PresenceCore(bus=event_bus, config=mock_config)

    core.add_stay_awake("meeting_mode")
    assert core.is_stay_awake() is True

    core.remove_stay_awake("meeting_mode")
    assert core.is_stay_awake() is False
