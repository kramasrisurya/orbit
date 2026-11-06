"""
BLE listener.

Continuously scans for BLE advertisements from the paired phone using
`bleak`. Publishes PHONE_NEAR on detection and PHONE_FAR when no
advertisement is received for `ble_grace_period_sec`.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime

from core.event_bus import EventBus, OrbitEvent, PHONE_NEAR, PHONE_FAR

logger = logging.getLogger("orbit.phone.ble")

# ORBIT BLE service UUID
ORBIT_SERVICE_UUID = "0000-ORBIT-0000-1000-8000-00805F9B34FB"


class BleListener:
    """
    Background BLE scanner.

    Runs an asyncio scan loop in a dedicated thread with its own event
    loop (bleak's scanner is asyncio-based). Publishes PHONE_NEAR /
    PHONE_FAR to the main EventBus.

    If BLE is unavailable (no adapter, permissions, etc.), logs a warning
    and disables this channel. The system still works via WebSocket.
    """

    def __init__(
        self,
        bus: EventBus,
        config,
    ) -> None:
        self._bus = bus
        self._config = config
        self._running = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_seen: datetime | None = None
        self._last_rssi: int = 0
        self._available = True

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="ble-listener"
        )
        self._thread.start()
        logger.info("BleListener started")

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        logger.info("BleListener stopped")

    def _run(self) -> None:
        """Run the BLE scan loop in this thread's own event loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._scan_loop())
        except Exception:
            logger.exception("BLE scan loop crashed")
        finally:
            self._loop.close()

    async def _scan_loop(self) -> None:
        try:
            from bleak import BleakScanner
        except ImportError:
            logger.warning("bleak not installed — BLE channel disabled")
            self._available = False
            return

        # Check adapter availability
        try:
            from bleak import BleakScanner
            # A quick probe: if the scanner can't start, BLE is unavailable
            test = BleakScanner()
        except Exception:
            logger.warning("BLE adapter unavailable — BLE channel disabled")
            self._available = False
            return

        logger.info("BLE scanning for ORBIT service %s", ORBIT_SERVICE_UUID)

        while self._running:
            try:
                def _callback(device, advertisement_data):
                    # Filter for our service UUID
                    if advertisement_data.service_uuids:
                        for uuid in advertisement_data.service_uuids:
                            if str(uuid) == ORBIT_SERVICE_UUID or \
                               "ORBIT" in str(uuid).upper():
                                rssi = advertisement_data.rssi
                                self._on_device(device.address, rssi)
                                return

                # Scan for a short window, then loop
                await asyncio.wait_for(
                    self._scan_once(_callback),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                pass
            except Exception:
                logger.exception("BLE scan error")

            # Check for PHONE_FAR
            self._check_far()

            await asyncio.sleep(1)

    async def _scan_once(self, callback) -> None:
        from bleak import BleakScanner
        scanner = BleakScanner(callback)
        await scanner.start()
        await asyncio.sleep(3)
        await scanner.stop()

    def _on_device(self, address: str, rssi: int) -> None:
        self._last_seen = datetime.now()
        self._last_rssi = rssi
        # Throttle: only publish near if we haven't recently
        self._bus.publish_async(OrbitEvent(
            type=PHONE_NEAR,
            source="phone",
            payload={"device_id": address, "rssi": rssi},
        ))

    def _check_far(self) -> None:
        if self._last_seen is None:
            return
        elapsed = (datetime.now() - self._last_seen).total_seconds()
        if elapsed > self._config.phone_ble_grace_period_sec:
            self._last_seen = None  # reset to avoid spam
            self._bus.publish_async(OrbitEvent(
                type=PHONE_FAR,
                source="phone",
                payload={"reason": "ble_timeout"},
            ))

    @property
    def is_available(self) -> bool:
        return self._available
