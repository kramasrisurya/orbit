"""
Tests for EventBus.
"""

import asyncio
import pytest
from core.event_bus import (
    EventBus, OrbitEvent, FACE_DETECTED, USER_RECOGNIZED, MODE_CHANGED
)


def test_event_bus_publish_subscribe(event_bus: EventBus):
    received = []

    def handler(evt: OrbitEvent):
        received.append(evt)

    event_bus.subscribe(FACE_DETECTED, handler)

    event = OrbitEvent(type=FACE_DETECTED, source="test", payload={"confidence": 0.95})
    event_bus.publish(event)

    assert len(received) == 1
    assert received[0].type == FACE_DETECTED
    assert received[0].payload["confidence"] == 0.95


def test_event_bus_wildcard_subscription(event_bus: EventBus):
    all_events = []
    mode_events = []

    event_bus.subscribe("__all__", lambda e: all_events.append(e))
    event_bus.subscribe(MODE_CHANGED, lambda e: mode_events.append(e))

    e1 = OrbitEvent(type=FACE_DETECTED, source="test")
    e2 = OrbitEvent(type=MODE_CHANGED, source="test", payload={"mode": "focus"})

    event_bus.publish(e1)
    event_bus.publish(e2)

    assert len(all_events) == 2
    assert len(mode_events) == 1
    assert mode_events[0].payload["mode"] == "focus"


def test_event_bus_handler_exception_isolated(event_bus: EventBus):
    received = []

    def bad_handler(evt: OrbitEvent):
        raise RuntimeError("Handler failure")

    def good_handler(evt: OrbitEvent):
        received.append(evt)

    event_bus.subscribe(USER_RECOGNIZED, bad_handler)
    event_bus.subscribe(USER_RECOGNIZED, good_handler)

    # Should not raise exception
    event_bus.publish(OrbitEvent(type=USER_RECOGNIZED, source="test"))

    assert len(received) == 1


@pytest.mark.asyncio
async def test_event_bus_publish_async(event_bus: EventBus):
    import pytest
    loop = asyncio.get_running_loop()
    event_bus.set_loop(loop)

    received = []
    event_bus.subscribe(FACE_DETECTED, lambda e: received.append(e))

    event_bus.publish_async(OrbitEvent(type=FACE_DETECTED, source="thread"))
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].source == "thread"
