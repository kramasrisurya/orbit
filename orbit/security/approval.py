"""
Approval manager.

Gates sensitive actions behind phone approval. Sends an APPROVAL_REQUEST
to the phone and waits (with a timeout) for APPROVAL_GRANTED or
APPROVAL_DENIED.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from core.event_bus import (
    EventBus, OrbitEvent,
    APPROVAL_REQUEST, APPROVAL_GRANTED, APPROVAL_DENIED,
)

logger = logging.getLogger("orbit.security.approval")


class ApprovalManager:
    """
    Coordinates approval of sensitive actions.

    Flow:
      1. request_approval(desc) → publishes APPROVAL_REQUEST to the bus
         (which the phone WS server relays to the phone) and returns an
         asyncio.Event.
      2. The phone responds → APPROVAL_GRANTED / APPROVAL_DENIED event.
      3. The matching waiting event is set.
      4. approve() awaits the event with a timeout; timeout = denial.
    """

    def __init__(self, bus: EventBus, config) -> None:
        self._bus = bus
        self._config = config
        # request_id → (asyncio.Event, description, outcome_box)
        # outcome_box is a single-element list: [bool | None]
        self._pending: dict[str, tuple[asyncio.Event, str, list]] = {}

        self._bus.subscribe(APPROVAL_GRANTED, self._on_granted)
        self._bus.subscribe(APPROVAL_DENIED, self._on_denied)

    def _on_granted(self, event: OrbitEvent) -> None:
        req_id = event.payload.get("request_id")
        if req_id and req_id in self._pending:
            ev, _, outcome = self._pending[req_id]
            outcome[0] = True
            ev.set()
            logger.info("Approval granted for: %s", req_id)

    def _on_denied(self, event: OrbitEvent) -> None:
        req_id = event.payload.get("request_id")
        if req_id and req_id in self._pending:
            ev, _, outcome = self._pending[req_id]
            outcome[0] = False
            ev.set()
            logger.info("Approval denied for: %s", req_id)

    def request_approval(self, action_description: str) -> tuple[str, asyncio.Event]:
        """
        Publish an APPROVAL_REQUEST and return (request_id, event).
        The event is set when the phone responds (grant or deny).
        """
        req_id = uuid.uuid4().hex[:12]
        ev = asyncio.Event()
        outcome: list[bool | None] = [None]
        self._pending[req_id] = (ev, action_description, outcome)

        self._bus.publish(OrbitEvent(
            type=APPROVAL_REQUEST,
            source="security",
            payload={
                "request_id": req_id,
                "action": action_description,
                "timeout_sec": self._config.phone_approval_timeout_sec,
            },
        ))
        logger.info("Approval requested: %s (%s)", req_id, action_description)
        return req_id, ev

    async def approve(self, action: str) -> bool:
        """
        Request approval and wait for the phone's response.
        Returns True if granted, False if denied or timed out.
        """
        req_id, ev = self.request_approval(action)
        timeout = self._config.phone_approval_timeout_sec
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            logger.warning("Approval timed out (%ds) for: %s", timeout, action)
            return False

        # Read the outcome recorded by _on_granted / _on_denied
        entry = self._pending.pop(req_id, None)
        if entry is None:
            return False
        outcome = entry[2][0]
        return outcome is True
