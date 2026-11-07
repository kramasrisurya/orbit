"""
Dashboard HTTP server.

Serves the static dashboard UI and exposes a few REST endpoints:
  GET /                → index.html
  GET /api/status      → current system status JSON
  GET /api/events      → recent events
  GET /api/stats       → today's stats
  POST /api/command    → execute a command (e.g., start/stop focus)
  GET /api/pairing_qr  → base64 QR code for phone pairing
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from aiohttp import web

from core.event_bus import EventBus, OrbitEvent, FOCUS_SESSION_START, FOCUS_SESSION_END
from core.presence import PresenceCore
from core.modes import ModeManager
from db.repositories import EventRepository, StatsRepository
from phone.pairing import PairingManager
from dashboard.websocket import DashboardWebSocket

logger = logging.getLogger("orbit.dashboard.server")

STATIC_DIR = Path(__file__).parent / "static"
if not (STATIC_DIR / "index.html").exists():
    candidate_public = Path(__file__).resolve().parents[2] / "public"
    if (candidate_public / "index.html").exists():
        STATIC_DIR = candidate_public


class DashboardServer:
    """
    AioHTTP web server for the dashboard UI.
    """

    def __init__(
        self,
        bus: EventBus,
        config,
        presence_core: PresenceCore | None = None,
        mode_manager: ModeManager | None = None,
        event_repo: EventRepository | None = None,
        stats_repo: StatsRepository | None = None,
        pairing_manager: PairingManager | None = None,
        ws: DashboardWebSocket | None = None,
        focus_manager: Any = None,
        vision_engine: Any = None,
        clipboard_sync: Any = None,
        universal_control: Any = None,
        phone_server: Any = None,
    ) -> None:
        self._bus = bus
        self._config = config
        self._presence = presence_core
        self._modes = mode_manager
        self._events = event_repo
        self._stats = stats_repo
        self._pairing = pairing_manager
        self._ws = ws
        self._focus = focus_manager
        self._vision = vision_engine
        self._clipboard_sync = clipboard_sync
        self._universal = universal_control
        self._phone_server = phone_server
        self._pending_enrollment: dict[str, Any] | None = None
        self._bus.subscribe("BIOMETRIC_REENROLL_APPROVED", self._on_biometric_reenroll_approved)

        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    def _on_biometric_reenroll_approved(self, event: OrbitEvent) -> None:
        token = event.payload.get("token")
        if self._pending_enrollment and (not token or self._pending_enrollment.get("token") == token):
            self._pending_enrollment["status"] = "approved"
            logger.info("Biometric enrollment approved via phone event for token %s", token)

    async def start(self) -> None:
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/manifest.json", self._handle_manifest)
        self._app.router.add_get("/api/status", self._handle_status)
        self._app.router.add_get("/api/events", self._handle_events)
        self._app.router.add_get("/api/stats", self._handle_stats)
        self._app.router.add_post("/api/command", self._handle_command)
        self._app.router.add_get("/api/pairing_qr", self._handle_pairing_qr)
        self._app.router.add_post("/api/enroll", self._handle_enroll)
        self._app.router.add_post("/api/enroll/request", self._handle_enroll_request)
        self._app.router.add_post("/api/enroll/approve", self._handle_enroll_approve)
        self._app.router.add_get("/api/enroll/status", self._handle_enroll_status)
        self._app.router.add_get("/api/clipboard", self._handle_get_clipboard)
        self._app.router.add_post("/api/clipboard", self._handle_set_clipboard)
        self._app.router.add_post("/api/clipboard/send_to_phone", self._handle_send_clipboard_to_phone)
        self._app.router.add_post("/api/files/upload", self._handle_file_upload)
        self._app.router.add_post("/api/files/push_to_phone", self._handle_push_file_to_phone)
        self._app.router.add_get("/api/files/list", self._handle_file_list)
        self._app.router.add_get("/api/files/download", self._handle_file_download)
        if self._ws is not None:
            self._app.router.add_get("/ws", self._ws.handle)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", self._config.dashboard_port)
        await self._site.start()
        logger.info("Dashboard server running on http://localhost:%d", self._config.dashboard_port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
        logger.info("Dashboard server stopped")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    async def _handle_index(self, request: web.Request) -> web.Response:
        index = STATIC_DIR / "index.html"
        if index.exists():
            return web.Response(text=index.read_text(encoding="utf-8"), content_type="text/html", charset="utf-8")
        return web.Response(text="<h1>ORBIT Dashboard</h1><p>UI not found.</p>")

    async def _handle_manifest(self, request: web.Request) -> web.Response:
        manifest = STATIC_DIR / "manifest.json"
        if manifest.exists():
            return web.Response(text=manifest.read_text(encoding="utf-8"), content_type="application/manifest+json")
        return web.json_response({})

    async def _handle_status(self, request: web.Request) -> web.Response:
        status = {
            "presence": "unknown",
            "mode": "work",
            "focus_active": False,
            "phones_connected": 0,
        }
        if self._presence:
            status["presence"] = self._presence.get_state().value
        if self._phone_server:
            status["phones_connected"] = len(self._phone_server.connected_phones)
        if self._modes:
            status["mode"] = self._modes.get_current_mode()
        if self._focus:
            status["focus_active"] = self._focus.is_active
        if self._vision:
            status["camera_paused"] = getattr(self._vision, "is_camera_paused", lambda: False)()
            status["eco_mode"] = getattr(self._vision, "is_eco_mode", lambda: False)()
        if self._presence:
            status["stay_awake"] = self._presence.is_stay_awake()
        if self._universal:
            status["universal_control"] = self._universal.is_enabled()
            status["cursor_leaped"] = self._universal.is_leaped()
        if self._clipboard_sync:
            status["clipboard_text"] = self._clipboard_sync.get_current()
        return web.json_response(status)

    async def _handle_events(self, request: web.Request) -> web.Response:
        limit = int(request.query.get("limit", "50"))
        if self._events:
            try:
                events = self._events.query(limit=limit)
                return web.json_response(events)
            except Exception:
                logger.exception("Failed to query events")
        return web.json_response([])

    async def _handle_stats(self, request: web.Request) -> web.Response:
        if self._stats:
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                stats = self._stats.get_daily(today)
                return web.json_response(stats)
            except Exception:
                logger.exception("Failed to get stats")
        return web.json_response({})

    async def _handle_command(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)

        action = data.get("action", "")

        if action == "focus_start":
            self._bus.publish(OrbitEvent(
                type=FOCUS_SESSION_START, source="dashboard", payload={}
            ))
            return web.json_response({"ok": True, "action": action})

        elif action == "focus_end":
            self._bus.publish(OrbitEvent(
                type=FOCUS_SESSION_END, source="dashboard", payload={}
            ))
            return web.json_response({"ok": True, "action": action})

        elif action == "switch_mode":
            mode = data.get("mode", "")
            if self._modes:
                ok = self._modes.switch_mode(mode)
                return web.json_response({"ok": ok, "action": action})
            return web.json_response({"ok": False, "error": "no mode manager"}, status=500)

        elif action == "trigger_intruder_test":
            from core.event_bus import INTRUDER_ALERT, OrbitEvent
            self._bus.publish(OrbitEvent(
                type=INTRUDER_ALERT,
                source="test",
                payload={"reason": "unauthorized_user", "faces": 1}
            ))
            return web.json_response({"ok": True, "action": action})

        elif action == "lock":
            from utils.windows import lock_workstation
            lock_workstation()
            return web.json_response({"ok": True, "action": action})

        elif action in ("pause_camera", "resume_camera", "toggle_camera"):
            paused = data.get("paused")
            if paused is None:
                if action == "pause_camera":
                    paused = True
                elif action == "resume_camera":
                    paused = False
            if self._vision:
                if paused is None:
                    is_p = self._vision.toggle_camera_pause()
                else:
                    is_p = self._vision.set_camera_paused(bool(paused))
                return web.json_response({"ok": True, "action": action, "paused": is_p})
            return web.json_response({"ok": False, "error": "vision engine unavailable"}, status=500)

        elif action == "toggle_eco":
            if self._vision:
                enabled = data.get("enabled")
                if enabled is None:
                    is_eco = self._vision.toggle_eco_mode()
                else:
                    is_eco = self._vision.set_eco_mode(bool(enabled))
                return web.json_response({"ok": True, "action": action, "eco_mode": is_eco})
            return web.json_response({"ok": False, "error": "vision engine unavailable"}, status=500)

        elif action == "take_snapshot":
            if self._vision:
                path = self._vision.capture_snapshot()
                if path:
                    return web.json_response({"ok": True, "action": action, "path": path})
                return web.json_response({"ok": False, "error": "No camera frame to capture (is camera paused?)"}, status=400)
            return web.json_response({"ok": False, "error": "vision engine unavailable"}, status=500)

        elif action == "toggle_stay_awake":
            if self._presence:
                current = self._presence.is_stay_awake()
                if current:
                    self._presence.remove_stay_awake("manual_override")
                else:
                    self._presence.add_stay_awake("manual_override")
                new_state = self._presence.is_stay_awake()
                self._bus.publish(OrbitEvent(
                    type="STAY_AWAKE_CHANGED",
                    source="dashboard",
                    payload={"stay_awake": new_state},
                ))
                return web.json_response({"ok": True, "action": action, "stay_awake": new_state})
            return web.json_response({"ok": False, "error": "presence core unavailable"}, status=500)

        elif action == "toggle_universal_control":
            if self._universal:
                val = self._universal.set_enabled(not self._universal.is_enabled())
                return web.json_response({"ok": True, "action": action, "universal_control": val})
            return web.json_response({"ok": False, "error": "universal control unavailable"}, status=500)

        return web.json_response({"ok": False, "error": f"unknown action: {action}"}, status=400)

    async def _handle_pairing_qr(self, request: web.Request) -> web.Response:
        if self._pairing:
            try:
                qr_b64 = self._pairing.initiate_pairing()
                from phone.pairing import _get_local_ip, crypto
                key_bytes = crypto.load_key() or b""
                import base64
                return web.json_response({
                    "qr": qr_b64,
                    "ip": _get_local_ip(),
                    "port": self._config.phone_websocket_port,
                    "key": base64.b64encode(key_bytes).decode("ascii") if key_bytes else "",
                })
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"error": "pairing not available"}, status=500)

    async def _handle_enroll(self, request: web.Request) -> web.Response:
        """Enroll a face from camera capture or provided image."""
        try:
            try:
                from orbit.enroll import enroll_from_frame
            except (ImportError, ModuleNotFoundError):
                try:
                    from enroll import enroll_from_frame
                except Exception:
                    import sys
                    from pathlib import Path
                    root = Path(__file__).resolve().parent.parent
                    if str(root) not in sys.path:
                        sys.path.insert(0, str(root))
                    import enroll
                    import importlib
                    importlib.reload(enroll)
                    enroll_from_frame = enroll.enroll_from_frame

            data = {}
            if request.can_read_body:
                try:
                    data = await request.json()
                except Exception:
                    pass
            label = data.get("label", "owner")
            b64_img = data.get("image")

            if b64_img:
                import base64
                import numpy as np
                import cv2
                img_bytes = base64.b64decode(b64_img.split(",")[-1])
                nparr = np.frombuffer(img_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if frame is None:
                    return web.json_response({"ok": False, "error": "Invalid image data"}, status=400)
                ok = enroll_from_frame(frame, label=label)
                if ok:
                    self._bus.publish(OrbitEvent(type="FACE_ENROLLED", source="dashboard", payload={"label": label}))
                    return web.json_response({"ok": True, "label": label})
                return web.json_response({"ok": False, "error": "Could not detect face in provided image"}, status=400)
            else:
                # Always retrieve the fresh unannotated frame directly from the running vision engine
                frame = None
                if self._vision is not None and hasattr(self._vision, "get_latest_frame"):
                    frame = self._vision.get_latest_frame()

                if frame is None and self._vision is not None and getattr(self._vision, "_latest_raw_frame", None) is not None:
                    frame = self._vision._latest_raw_frame.copy()

                if frame is None:
                    return web.json_response({
                        "ok": False,
                        "error": "Webcam stream not ready or camera paused. Please unpause camera and try again."
                    }, status=400)

                ok = enroll_from_frame(frame, label=label)
                if ok:
                    self._bus.publish(OrbitEvent(type="FACE_ENROLLED", source="dashboard", payload={"label": label}))
                    return web.json_response({"ok": True, "label": label})
                else:
                    return web.json_response({
                        "ok": False,
                        "error": "Could not detect clear face. Look directly into the camera in a well-lit area."
                    }, status=400)
        except Exception as e:
            logger.exception("Enroll endpoint error")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_enroll_request(self, request: web.Request) -> web.Response:
        """Start a biometric re-enrollment flow requiring phone fingerprint approval."""
        import uuid
        token = uuid.uuid4().hex[:8]
        self._pending_enrollment = {
            "token": token,
            "status": "waiting_phone",
            "created_at": time.time(),
        }
        logger.info("Biometric re-enrollment initiated. Generated token: %s", token)

        # Broadcast to connected mobile phone(s)
        if self._phone_server:
            try:
                asyncio.create_task(
                    self._phone_server.broadcast(
                        "biometric_reenroll_request",
                        {
                            "token": token,
                            "device": "Laptop",
                            "prompt": "Scan fingerprint to authorize face biometrics re-enrollment",
                        }
                    )
                )
            except Exception:
                logger.exception("Failed to broadcast reenroll request to phone")

        return web.json_response({"ok": True, "token": token, "status": "waiting_phone"})

    async def _handle_enroll_approve(self, request: web.Request) -> web.Response:
        """Phone approves biometric re-enrollment via fingerprint verification."""
        try:
            data = await request.json()
        except Exception:
            data = {}
        token = data.get("token", "")
        if self._pending_enrollment and (not token or self._pending_enrollment.get("token") == token):
            self._pending_enrollment["status"] = "approved"
            logger.info("Biometric re-enrollment token %s approved via HTTP endpoint", token)
            return web.json_response({"ok": True})
        return web.json_response({"ok": False, "error": "Invalid or expired token"}, status=400)

    async def _handle_enroll_status(self, request: web.Request) -> web.Response:
        """Poll biometric re-enrollment status. If approved, executes face capture."""
        token = request.query.get("token", "")
        if not self._pending_enrollment or (token and self._pending_enrollment.get("token") != token):
            return web.json_response({"ok": False, "status": "not_found"}, status=404)

        status = self._pending_enrollment.get("status", "waiting_phone")
        if status == "waiting_phone":
            if time.time() - self._pending_enrollment.get("created_at", 0) > 60:
                self._pending_enrollment["status"] = "timed_out"
                return web.json_response({"ok": False, "status": "timed_out"})
            return web.json_response({"ok": True, "status": "waiting_phone"})

        if status == "approved":
            # Fingerprint was verified on phone! Now capture frame and enroll in SQLite
            try:
                try:
                    from orbit.enroll import enroll_from_frame
                except (ImportError, ModuleNotFoundError):
                    from enroll import enroll_from_frame
                frame = None
                if self._vision is not None and hasattr(self._vision, "get_latest_frame"):
                    frame = self._vision.get_latest_frame()
                if frame is None and self._vision is not None and getattr(self._vision, "_latest_raw_frame", None) is not None:
                    frame = self._vision._latest_raw_frame.copy()

                if frame is None:
                    self._pending_enrollment["status"] = "failed"
                    return web.json_response({
                        "ok": False,
                        "status": "failed",
                        "error": "Webcam stream not ready or camera paused. Please unpause camera."
                    })

                ok = enroll_from_frame(frame, label="owner")
                if ok:
                    self._pending_enrollment["status"] = "completed"
                    self._bus.publish(OrbitEvent(type="FACE_ENROLLED", source="dashboard", payload={"label": "owner"}))
                    logger.info("Biometric re-enrollment COMPLETED successfully after fingerprint verification")
                    return web.json_response({"ok": True, "status": "completed", "message": "Biometrics stored"})
                else:
                    self._pending_enrollment["status"] = "failed"
                    return web.json_response({
                        "ok": False,
                        "status": "failed",
                        "error": "Could not detect clear face. Please look directly at the webcam."
                    })
            except Exception as e:
                logger.exception("Enroll execution error")
                self._pending_enrollment["status"] = "failed"
                return web.json_response({"ok": False, "status": "failed", "error": str(e)})

        return web.json_response({"ok": True, "status": status})

    # ------------------------------------------------------------------
    # Universal Clipboard & AirDrop / QuickShare
    # ------------------------------------------------------------------
    async def _handle_get_clipboard(self, request: web.Request) -> web.Response:
        """Fetch current Windows clipboard content."""
        from utils.windows import get_clipboard
        return web.json_response({"ok": True, "text": get_clipboard()})

    async def _handle_set_clipboard(self, request: web.Request) -> web.Response:
        """Set Windows clipboard from mobile phone."""
        text = ""
        try:
            data = await request.json()
            if isinstance(data, dict):
                text = data.get("text", "")
        except Exception:
            pass

        if not text:
            try:
                raw = (await request.text()).strip()
                import json
                try:
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        text = data.get("text", "")
                    else:
                        text = raw
                except Exception:
                    clean = raw.replace('\\"', '"')
                    try:
                        data = json.loads(clean)
                        if isinstance(data, dict):
                            text = data.get("text", "")
                    except Exception:
                        text = raw
            except Exception:
                pass

        if text:
            from utils.windows import set_clipboard
            set_clipboard(text)
            if self._clipboard_sync and hasattr(self._clipboard_sync, "_last_pushed"):
                self._clipboard_sync._last_pushed = text
            self._bus.publish(OrbitEvent(
                type="CLIPBOARD_UPDATED",
                source="dashboard",
                payload={"text": text},
            ))
            logger.info("Synced mobile clipboard to Windows (%d chars)", len(text))
            return web.json_response({"ok": True, "length": len(text)})
        return web.json_response({"ok": False, "error": "empty text"}, status=400)

    async def _handle_send_clipboard_to_phone(self, request: web.Request) -> web.Response:
        """Send text directly from Web Dashboard to Mobile Phone clipboard."""
        text = ""
        try:
            data = await request.json()
            if isinstance(data, dict):
                text = data.get("text", "")
        except Exception:
            pass

        if not text:
            try:
                raw = (await request.text()).strip()
                import json
                try:
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        text = data.get("text", "")
                    else:
                        text = raw
                except Exception:
                    clean = raw.replace('\\"', '"')
                    try:
                        data = json.loads(clean)
                        if isinstance(data, dict):
                            text = data.get("text", "")
                    except Exception:
                        text = raw
            except Exception:
                pass

        if text:
            from utils.windows import set_clipboard
            set_clipboard(text)
            if self._clipboard_sync and hasattr(self._clipboard_sync, "_last_pushed"):
                self._clipboard_sync._last_pushed = text
            if self._phone_server:
                await self._phone_server.broadcast("clipboard", {"text": text})
            logger.info("Pushed clipboard directly to mobile phone (%d chars)", len(text))
            return web.json_response({"ok": True, "message": "Sent to mobile successfully!"})
        return web.json_response({"ok": False, "error": "empty text"}, status=400)

    async def _handle_file_upload(self, request: web.Request) -> web.Response:
        """Receive file from mobile and save directly into laptop Downloads folder."""
        try:
            reader = await request.multipart()
            downloads_dir = Path.home() / "Downloads"
            downloads_dir.mkdir(parents=True, exist_ok=True)

            uploaded_files = []
            while True:
                field = await reader.next()
                if field is None:
                    break
                if field.filename:
                    raw_name = Path(field.filename).name
                    target = downloads_dir / raw_name
                    if target.exists():
                        target = downloads_dir / f"{target.stem}_{int(time.time())}{target.suffix}"

                    size = 0
                    with target.open("wb") as f:
                        while True:
                            chunk = await field.read_chunk()
                            if not chunk:
                                break
                            size += len(chunk)
                            f.write(chunk)

                    logger.info("Saved mobile upload to laptop Downloads: %s (%d bytes)", target, size)
                    uploaded_files.append({"filename": target.name, "path": str(target), "size": size})

                    # If destination is mobile phone or user requested push to phone
                    target_param = request.query.get("target", "")
                    if target_param == "mobile" or request.query.get("push", "") == "true":
                        # Push directly via ADB to phone's Download folder for instant delivery
                        try:
                            import shutil
                            adb_path = shutil.which("adb")
                            if not adb_path:
                                local_app = os.environ.get("LOCALAPPDATA", "")
                                candidate = Path(local_app) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
                                if candidate.exists():
                                    adb_path = str(candidate)
                            if adb_path and Path(adb_path).exists():
                                subprocess.Popen([adb_path, "push", str(target), f"/sdcard/Download/{target.name}"])
                                logger.info("ADB direct pushed %s to /sdcard/Download/%s", target, target.name)
                        except Exception:
                            logger.exception("ADB push failed")

                        if self._phone_server:
                            try:
                                from phone.pairing import _get_local_ip
                                import urllib.parse
                                local_ip = _get_local_ip()
                                download_url = f"http://{local_ip}:8080/api/files/download?file={urllib.parse.quote(target.name)}"
                                asyncio.create_task(
                                    self._phone_server.broadcast(
                                        "file_incoming",
                                        {
                                            "filename": target.name,
                                            "url": download_url,
                                            "size": size,
                                        }
                                    )
                                )
                                logger.info("Pushed file notification to mobile: %s", target.name)
                            except Exception:
                                logger.exception("Failed to push file to mobile")

                    # Broadcast ecosystem event
                    self._bus.publish(OrbitEvent(
                        type="FILE_TRANSFERRED",
                        source="dashboard",
                        payload={
                            "direction": "laptop_to_mobile" if target_param == "mobile" else "mobile_to_laptop",
                            "filename": target.name,
                            "path": str(target),
                            "size": size,
                        },
                    ))

            if uploaded_files:
                return web.json_response({"ok": True, "files": uploaded_files})
            return web.json_response({"ok": False, "error": "No file received"}, status=400)
        except Exception as e:
            logger.exception("File upload error")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_push_file_to_phone(self, request: web.Request) -> web.Response:
        """Push any file in laptop Downloads directly to connected phone."""
        try:
            data = await request.json()
            filename = data.get("filename", "")
            if not filename:
                return web.json_response({"ok": False, "error": "filename required"}, status=400)
            target = Path.home() / "Downloads" / Path(filename).name
            if not target.exists():
                return web.json_response({"ok": False, "error": "file not found"}, status=404)

            if self._phone_server:
                from phone.pairing import _get_local_ip
                import urllib.parse
                local_ip = _get_local_ip()
                download_url = f"http://{local_ip}:8080/api/files/download?file={urllib.parse.quote(target.name)}"
                await self._phone_server.broadcast(
                    "file_incoming",
                    {
                        "filename": target.name,
                        "url": download_url,
                        "size": target.stat().st_size,
                    }
                )
                self._bus.publish(OrbitEvent(
                    type="FILE_TRANSFERRED",
                    source="dashboard",
                    payload={
                        "direction": "laptop_to_mobile",
                        "filename": target.name,
                        "path": str(target),
                        "size": target.stat().st_size,
                    },
                ))
                return web.json_response({"ok": True, "filename": target.name})
            return web.json_response({"ok": False, "error": "Phone server not ready"}, status=500)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_file_list(self, request: web.Request) -> web.Response:
        """List files available in laptop Downloads folder for mobile download."""
        try:
            downloads_dir = Path.home() / "Downloads"
            if not downloads_dir.exists():
                return web.json_response([])
            files = []
            for p in sorted(downloads_dir.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)[:25]:
                if p.is_file():
                    files.append({
                        "name": p.name,
                        "size": p.stat().st_size,
                        "modified": p.stat().st_mtime,
                    })
            return web.json_response(files)
        except Exception as e:
            logger.exception("File list error")
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_file_download(self, request: web.Request) -> web.Response:
        """Stream requested laptop file to mobile phone."""
        fname = request.query.get("file", "")
        if not fname:
            return web.json_response({"error": "file parameter required"}, status=400)
        safe_name = Path(fname).name
        target = Path.home() / "Downloads" / safe_name
        if target.exists() and target.is_file():
            return web.FileResponse(target)
        return web.json_response({"error": "File not found"}, status=404)

