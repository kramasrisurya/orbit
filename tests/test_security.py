"""
Tests for ApprovalManager and IntruderDetector.
"""

import asyncio
import pytest
from core.event_bus import (
    EventBus, OrbitEvent, APPROVAL_REQUEST, APPROVAL_GRANTED,
    APPROVAL_DENIED, MULTI_PERSON_DETECTED
)
from security.approval import ApprovalManager
from security.intruder import IntruderDetector


@pytest.mark.asyncio
async def test_approval_manager_grant(event_bus: EventBus, mock_config):
    mock_config.phone_approval_timeout_sec = 2
    am = ApprovalManager(event_bus, mock_config)

    req_events = []
    event_bus.subscribe(APPROVAL_REQUEST, lambda e: req_events.append(e))

    async def simulate_phone_grant():
        await asyncio.sleep(0.05)
        assert len(req_events) == 1
        req_id = req_events[0].payload["request_id"]
        event_bus.publish(OrbitEvent(
            type=APPROVAL_GRANTED,
            source="phone",
            payload={"request_id": req_id}
        ))

    task = asyncio.create_task(simulate_phone_grant())
    granted = await am.approve("launch_app:terminal")
    await task

    assert granted is True


@pytest.mark.asyncio
async def test_approval_manager_deny(event_bus: EventBus, mock_config):
    mock_config.phone_approval_timeout_sec = 2
    am = ApprovalManager(event_bus, mock_config)

    req_events = []
    event_bus.subscribe(APPROVAL_REQUEST, lambda e: req_events.append(e))

    async def simulate_phone_deny():
        await asyncio.sleep(0.05)
        assert len(req_events) == 1
        req_id = req_events[0].payload["request_id"]
        event_bus.publish(OrbitEvent(
            type=APPROVAL_DENIED,
            source="phone",
            payload={"request_id": req_id}
        ))

    task = asyncio.create_task(simulate_phone_deny())
    granted = await am.approve("lock_pc")
    await task

    assert granted is False


@pytest.mark.asyncio
async def test_approval_manager_timeout(event_bus: EventBus, mock_config):
    # Short timeout for quick testing
    mock_config.phone_approval_timeout_sec = 0.1
    am = ApprovalManager(event_bus, mock_config)

    granted = await am.approve("sensitive_action")
    assert granted is False


def test_intruder_detector_cooldown(event_bus: EventBus, mock_config):
    detector = IntruderDetector(bus=event_bus, config=mock_config)

    # First event should trigger
    event_bus.publish(OrbitEvent(
        type=MULTI_PERSON_DETECTED,
        source="vision",
        payload={"count": 2}
    ))
    t1 = detector._last_alert_time
    assert t1 > 0

    # Second event immediately after should be suppressed by cooldown
    event_bus.publish(OrbitEvent(
        type=MULTI_PERSON_DETECTED,
        source="vision",
        payload={"count": 2}
    ))
    assert detector._last_alert_time == t1


def test_intruder_unauthorized_user_alert(event_bus: EventBus, mock_config):
    from unittest.mock import MagicMock
    from core.event_bus import INTRUDER_ALERT

    mock_notifier = MagicMock()
    detector = IntruderDetector(bus=event_bus, config=mock_config, notifier=mock_notifier)

    event_bus.publish(OrbitEvent(
        type=INTRUDER_ALERT,
        source="vision",
        payload={"reason": "unauthorized_user", "faces": 1}
    ))

    assert detector._last_alert_time > 0
    assert mock_notifier.send.called
    call_args = mock_notifier.send.call_args[0]
    assert call_args[0] == "intruder_alert"
    assert "Unauthorized" in call_args[1]

