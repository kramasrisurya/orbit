"""
Clipboard sync.

Subscribes to CLIPBOARD_SYNC events (from the phone) and writes the
text to the PC clipboard. Also periodically pushes the PC clipboard
to the phone (one-way phone→PC is the primary direction).
"""

from __future__ import annotations

import asyncio
import logging
import time

from core.event_bus import EventBus, OrbitEvent, CLIPBOARD_SYNC
from utils.windows import set_clipboard, get_clipboard

logger = logging.getLogger("orbit.productivity.clipboard")


class ClipboardSync:
    """
    Syncs clipboard content between phone and PC.

    Phone → PC: immediate, on CLIPBOARD_SYNC event.
    PC → Phone: periodic push of the current PC clipboard (every 10s),
                only when the content changes.
    """

    def __init__(
        self,
        bus: EventBus,
        ws_server=None,
        phone_id: str | None = None,
    ) -> None:
        self._bus = bus
        self._ws = ws_server
        self._phone_id = phone_id
        self._last_pushed: str = ""

        self._running = False
        self._task: asyncio.Task | None = None

        self._bus.subscribe(CLIPBOARD_SYNC, self._on_phone_clipboard)

    def _on_phone_clipboard(self, event: OrbitEvent) -> None:
        text = event.payload.get("text", "")
        if not text:
            return
        logger.info("Phone → PC clipboard sync (%d chars)", len(text))
        try:
            set_clipboard(text)
        except Exception:
            logger.exception("Failed to set PC clipboard")

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._push_loop())
        logger.info("ClipboardSync started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ClipboardSync stopped")

    async def _push_loop(self) -> None:
        """Periodically push the PC clipboard to the phone."""
        while self._running:
            await asyncio.sleep(10)
            if not self._running:
                break
            if self._ws is None or self._phone_id is None:
                continue
            try:
                text = get_clipboard()
                if text and text != self._last_pushed:
                    self._last_pushed = text
                    await self._ws.send_notification(
                        self._phone_id,
                        "clipboard",
                        {"text": text},
                    )
                    logger.debug("PC → Phone clipboard push (%d chars)", len(text))
            except Exception:
                logger.exception("Clipboard push failed")
