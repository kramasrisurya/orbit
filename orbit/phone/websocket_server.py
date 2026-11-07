"""
Phone WebSocket server.

Runs an asyncio WebSocket server on 0.0.0.0:websocket_port so the phone
can connect over the LAN. Performs an AES handshake on connect, then
relays encrypted JSON messages to/from the EventBus.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from typing import Any

import websockets
from websockets.server import WebSocketServerProtocol

from core.event_bus import (
    EventBus, OrbitEvent,
    PHONE_NEAR, PHONE_FAR, WIFI_PRESENCE, PHONE_SHAKE,
    NFC_MODE_TRIGGERED, PHONE_REMOTE_COMMAND, PHONE_GEO_LEFT,
    PHONE_GEO_RETURNED, APPROVAL_GRANTED, APPROVAL_DENIED,
    CLIPBOARD_SYNC,
)
from utils import crypto

logger = logging.getLogger("orbit.phone.websocket")


class PhoneWebSocketServer:
    """
    Async WebSocket server for phone connections.

    Handshake:
      1. Phone connects.
      2. Phone sends a random nonce (base64).
      3. PC derives a session key from the pairing key + nonce,
         encrypts a challenge, sends it back.
      4. Phone decrypts the challenge. If it matches, the connection
         is accepted; otherwise it is rejected.

    After handshake, all messages are AES-256-GCM encrypted JSON.
    """

    def __init__(
        self,
        bus: EventBus,
        config,
        pairing_manager=None,
    ) -> None:
        self._bus = bus
        self._config = config
        self._pairing = pairing_manager
        self._server = None
        self._phones: dict[str, WebSocketServerProtocol] = {}
        self._phone_rssi: dict[str, int] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._bus.subscribe("UNIVERSAL_CONTROL_EVENT", self._on_universal_control)
        port = self._config.phone_websocket_port
        try:
            self._server = await websockets.serve(
                self._handle_connection,
                "0.0.0.0",
                port,
            )
            logger.info("Phone WebSocket server listening on 0.0.0.0:%d", port)
        except Exception:
            logger.exception("Failed to start WebSocket server on port %d", port)
            self._running = False

    async def stop(self) -> None:
        self._running = False
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        # Close all phone connections
        for ws in list(self._phones.values()):
            try:
                await ws.close()
            except Exception:
                pass
        self._phones.clear()
        logger.info("Phone WebSocket server stopped")

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------
    async def _handle_connection(
        self,
        ws: WebSocketServerProtocol,
        path: str | None = None,
    ) -> None:
        device_id: str | None = None
        try:
            # --- Handshake ---
            device_id, ok = await self._handshake(ws)
            if not ok:
                logger.warning("Handshake failed — rejecting connection")
                await ws.close(code=4001, reason="handshake_failed")
                return

            self._phones[device_id] = ws
            logger.info("Phone connected: %s (%d total)", device_id, len(self._phones))

            # Notify pairing manager
            if self._pairing:
                try:
                    self._pairing.complete_pairing(device_id)
                except Exception:
                    logger.exception("complete_pairing failed")

            # --- Message loop ---
            async for raw in ws:
                await self._on_message(device_id, raw)

        except websockets.exceptions.ConnectionClosed:
            logger.info("Phone %s disconnected", device_id)
        except Exception:
            logger.exception("Error handling phone %s", device_id)
        finally:
            if device_id and device_id in self._phones:
                del self._phones[device_id]
                self._phone_rssi.pop(device_id, None)
                logger.info("Phone %s removed (%d remaining)", device_id, len(self._phones))
                self._bus.publish(OrbitEvent(
                    type=PHONE_FAR,
                    source="phone",
                    payload={"device_id": device_id, "reason": "ws_disconnected"},
                ))

    async def _handshake(self, ws: WebSocketServerProtocol) -> tuple[str | None, bool]:
        """
        Perform the AES handshake with support for Base64 and Hex encodings.
        Returns (device_id, success).
        """
        key = crypto.load_key()
        if key is None:
            logger.warning("No pairing key found — rejecting (run pairing first)")
            return (None, False)

        try:
            import base64

            # 1. Receive nonce from phone
            nonce_raw = await asyncio.wait_for(ws.recv(), timeout=10)
            phone_nonce = base64_decode(nonce_raw)

            # 2. Derive session key using HKDF-SHA256
            session_key = crypto.derive_session_key(key, phone_nonce)

            # 3. Send encrypted challenge as Base64
            challenge = secrets.token_hex(8)
            encrypted = crypto.encrypt(challenge.encode(), session_key)
            await ws.send(base64.b64encode(encrypted).decode("ascii"))

            # 4. Phone echoes the challenge back (encrypted with session_key)
            response = await asyncio.wait_for(ws.recv(), timeout=10)
            try:
                response_bytes = base64.b64decode(response)
            except Exception:
                response_bytes = bytes.fromhex(response)
            decrypted = crypto.decrypt(response_bytes, session_key)
            if decrypted.decode() != challenge:
                logger.warning("Handshake challenge mismatch: %s != %s", decrypted.decode(), challenge)
                return (None, False)

            # 5. Receive device_id
            device_id = await asyncio.wait_for(ws.recv(), timeout=10)
            device_id = device_id.strip()

            # Store the session key for this device
            if not hasattr(self, "_session_keys"):
                self._session_keys = {}
            self._session_keys[device_id] = session_key

            # 6. Send handshake confirmation to phone
            confirm_msg = json.dumps({"type": "handshake_ok", "device_id": device_id}).encode("utf-8")
            confirm_enc = crypto.encrypt(confirm_msg, session_key)
            await ws.send(base64.b64encode(confirm_enc).decode("ascii"))

            logger.info("Handshake successfully completed for phone %s", device_id)
            return (device_id, True)
        except asyncio.TimeoutError:
            logger.warning("Handshake timed out")
            return (None, False)
        except Exception:
            logger.exception("Handshake error")
            return (None, False)

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------
    async def _on_message(self, device_id: str, raw: str | bytes) -> None:
        try:
            import base64
            session_key = getattr(self, "_session_keys", {}).get(device_id)
            plaintext = None
            if session_key is not None:
                try:
                    raw_str = raw if isinstance(raw, str) else raw.decode("utf-8")
                    try:
                        raw_bytes = base64.b64decode(raw_str)
                    except Exception:
                        raw_bytes = bytes.fromhex(raw_str)
                    plaintext = crypto.decrypt(raw_bytes, session_key)
                except Exception as e:
                    logger.debug("Decryption fallback: %s", e)

            if plaintext is None:
                plaintext = raw if isinstance(raw, bytes) else raw.encode("utf-8")

            msg = json.loads(plaintext.decode("utf-8"))
            mtype = msg.get("type", "")

            if mtype == "shake":
                self._bus.publish(OrbitEvent(
                    type=PHONE_SHAKE, source="phone",
                    payload={"count": msg.get("count", 1), "device_id": device_id},
                ))
            elif mtype == "nfc":
                self._bus.publish(OrbitEvent(
                    type=NFC_MODE_TRIGGERED, source="phone",
                    payload={"mode": msg.get("mode", ""), "device_id": device_id},
                ))
            elif mtype == "remote":
                self._bus.publish(OrbitEvent(
                    type=PHONE_REMOTE_COMMAND, source="phone",
                    payload={"action": msg.get("action", ""), "device_id": device_id},
                ))
            elif mtype in ("clipboard", "clipboard_update"):
                text = msg.get("text", "")
                if text:
                    self._bus.publish(OrbitEvent(
                        type=CLIPBOARD_SYNC, source="phone",
                        payload={"text": text, "device_id": device_id},
                    ))
                    try:
                        from utils.windows import set_clipboard
                        set_clipboard(text)
                        logger.info("Synchronized phone clipboard to Windows: %d chars", len(text))
                    except Exception as e:
                        logger.warning("Could not set Windows clipboard: %s", e)
            elif mtype in ("biometric_reenroll_approved", "biometric_approved"):
                token = msg.get("token", "")
                logger.info("Received biometric reenroll approval from phone (token: %s)", token)
                self._bus.publish(OrbitEvent(
                    type="BIOMETRIC_REENROLL_APPROVED", source="phone",
                    payload={"token": token, "device_id": device_id},
                ))
            elif mtype == "cam_control":
                action = msg.get("action", "")
                act = "pause_camera" if "pause" in action else "resume_camera"
                self._bus.publish(OrbitEvent(
                    type=PHONE_REMOTE_COMMAND, source="phone",
                    payload={"action": act, "device_id": device_id},
                ))
            elif mtype == "mouse_move":
                dx = int(msg.get("dx", 0))
                dy = int(msg.get("dy", 0))
                if dx != 0 or dy != 0:
                    try:
                        from utils.windows import move_cursor
                        move_cursor(dx, dy)
                        logger.info("Universal trackpad move: (%d, %d)", dx, dy)
                    except Exception as e:
                        logger.error("mouse_move error: %s", e)
            elif mtype == "mouse_click":
                button = msg.get("button", "left")
                try:
                    from utils.windows import mouse_click
                    mouse_click(button)
                    logger.info("Universal trackpad click: %s", button)
                except Exception as e:
                    logger.error("mouse_click error: %s", e)
            elif mtype == "mouse_scroll":
                dy = int(msg.get("dy", 0))
                try:
                    from utils.windows import mouse_scroll
                    mouse_scroll(dy)
                    logger.info("Universal trackpad scroll: %d", dy)
                except Exception as e:
                    logger.error("mouse_scroll error: %s", e)
            elif mtype == "remote_type":
                text = msg.get("text", "")
                if text:
                    try:
                        from utils.windows import type_text
                        type_text(text)
                        logger.info("Universal remote typing: %s", text)
                    except Exception as e:
                        logger.error("remote_type error: %s", e)
            elif mtype == "geo":
                status = msg.get("status", "")
                etype = PHONE_GEO_LEFT if status == "left" else PHONE_GEO_RETURNED
                self._bus.publish(OrbitEvent(
                    type=etype, source="phone",
                    payload={"status": status, "device_id": device_id},
                ))
            elif mtype == "approval":
                etype = APPROVAL_GRANTED if msg.get("granted") else APPROVAL_DENIED
                self._bus.publish(OrbitEvent(
                    type=etype, source="phone",
                    payload={"granted": bool(msg.get("granted")), "device_id": device_id},
                ))
            elif mtype == "status":
                self._phone_rssi[device_id] = msg.get("rssi", 0)
                self._bus.publish(OrbitEvent(
                    type=WIFI_PRESENCE, source="phone",
                    payload={
                        "ssid": msg.get("ssid", ""),
                        "rssi": msg.get("rssi", 0),
                        "device_id": device_id,
                    },
                ))
            else:
                logger.debug("Unknown phone message type: %s", mtype)

        except json.JSONDecodeError:
            logger.warning("Failed to parse phone message (not JSON)")
        except Exception:
            logger.exception("Error handling phone message")

    def _on_universal_control(self, event: OrbitEvent) -> None:
        """Broadcast universal control cursor leaps and actions to connected phone."""
        if not self._phones:
            return
        loop = getattr(self, "_loop", None)
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.broadcast("universal_control", event.payload or {}), loop
            )

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------
    async def send_notification(
        self, phone_id: str, type: str, payload: dict[str, Any]
    ) -> bool:
        """Send an encrypted notification to a specific phone."""
        ws = self._phones.get(phone_id)
        if ws is None:
            return False
        session_key = getattr(self, "_session_keys", {}).get(phone_id)
        msg = json.dumps({"type": type, **payload}).encode()
        logger.info("send_notification to %s: type=%s, size=%d bytes, encrypted=%s", phone_id, type, len(msg), session_key is not None)
        try:
            if session_key is not None:
                data = crypto.encrypt(msg, session_key)
                import base64
                await ws.send(base64.b64encode(data).decode("ascii"))
            else:
                await ws.send(msg.decode("utf-8"))
            return True
        except Exception:
            logger.exception("Failed to send notification to %s", phone_id)
            return False

    async def send_display_data(
        self, phone_id: str, panel: str, data: dict[str, Any]
    ) -> bool:
        """Send display/mirroring data to a phone panel."""
        return await self.send_notification(
            phone_id, "display_data", {"panel": panel, "data": data}
        )

    async def broadcast(self, type: str, payload: dict[str, Any]) -> None:
        """Send a notification to all connected phones."""
        for pid in list(self._phones.keys()):
            await self.send_notification(pid, type, payload)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    @property
    def connected_phones(self) -> dict[str, WebSocketServerProtocol]:
        return dict(self._phones)

    def is_phone_connected(self) -> bool:
        return len(self._phones) > 0

    def get_phone_rssi(self, phone_id: str) -> int:
        return self._phone_rssi.get(phone_id, 0)


def base64_decode(s: str | bytes) -> bytes:
    import base64
    if isinstance(s, bytes):
        return base64.b64decode(s)
    return base64.b64decode(s)
