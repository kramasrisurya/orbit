"""
Phone pairing manager.

Generates a 256-bit pairing key, encodes it (with the PC's IP and port)
into a QR code for the phone to scan, and tracks paired devices.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import socket
from typing import Any

import qrcode

from utils import crypto

logger = logging.getLogger("orbit.phone.pairing")


def _get_local_ip() -> str:
    """Best-effort detection of the PC's LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Doesn't actually send a packet; connects to a public address
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class PairingManager:
    """
    Manages phone pairing.

    Flow:
      1. initiate_pairing() → generates a key (if none exists), builds a
         QR code encoding {key, ip, port}, returns it as base64 PNG.
      2. Phone scans the QR, stores the key, connects to the WS server.
      3. complete_pairing(device_id) → records the device as paired.
    """

    def __init__(self, config) -> None:
        self._config = config
        self._paired_devices: set[str] = set()

    # ------------------------------------------------------------------
    # Pairing
    # ------------------------------------------------------------------
    def initiate_pairing(self) -> str:
        """
        Generate (or reuse) the pairing key and produce a QR code.
        Returns the QR code as a base64-encoded PNG string.
        """
        key = crypto.load_key()
        if key is None:
            key = crypto.generate_key()
            crypto.save_key(key)
            logger.info("New pairing key generated and saved")
        else:
            logger.info("Reusing existing pairing key")

        ip = _get_local_ip()
        port = self._config.phone_websocket_port

        # QR payload
        payload = json.dumps({
            "key": base64.b64encode(key).decode(),
            "ip": ip,
            "port": port,
        })

        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=8,
            border=4,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image()

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def complete_pairing(self, device_id: str) -> None:
        """Called when a phone successfully completes the WS handshake."""
        self._paired_devices.add(device_id)
        logger.info("Device paired: %s (%d total)", device_id, len(self._paired_devices))

    def is_paired(self, device_id: str) -> bool:
        """Return whether device is paired."""
        return device_id in self._paired_devices

    def get_paired_devices(self) -> list[str]:
        return list(self._paired_devices)

    def revoke_device(self, device_id: str) -> None:
        """Revoke a paired device."""
        self._paired_devices.discard(device_id)
        logger.info("Device revoked: %s", device_id)
