"""
ORBIT — Vercel Serverless Edge API.

Serves as the cloud relay and discovery API for ORBIT when deployed on Vercel.
Supports status telemetry, health checks, APK download routing, and cloud demo simulation.
"""

from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
from datetime import datetime

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._add_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip('/')

        if path in ('/api/health', '/api/ping'):
            self._send_json(200, {
                "status": "healthy",
                "service": "ORBIT Cloud Edge",
                "version": "1.0.0",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "docs": "https://github.com/kramasrisurya/orbit"
            })
        elif path == '/api/status':
            self._send_json(200, {
                "presence": "present_high",
                "mode": "work",
                "focus_active": False,
                "phones_connected": 1,
                "cloud_mode": True,
                "hub": "Vercel Edge Cloud",
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })
        elif path == '/api/events':
            self._send_json(200, [
                {
                    "type": "PRESENCE_CHANGED",
                    "source": "cloud_edge",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "payload": {"state": "present_high", "confidence": 0.98}
                },
                {
                    "type": "MODE_CHANGED",
                    "source": "cloud_edge",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "payload": {"mode": "work"}
                }
            ])
        elif path == '/api/stats':
            today = datetime.utcnow().strftime("%Y-%m-%d")
            self._send_json(200, {
                "date": today,
                "focus_minutes": 145,
                "screen_time_min": 280,
                "breaks_taken": 6,
                "posture_alerts": 3,
                "stress_minutes": 12,
                "intruder_alerts": 0,
                "pc_locks": 2
            })
        elif path in ('/api/download-apk', '/api/apk'):
            # Direct redirect to the latest GitHub release / Action artifact
            self.send_response(302)
            self.send_header('Location', 'https://github.com/kramasrisurya/orbit/actions')
            self._add_cors_headers()
            self.end_headers()
        elif path in ('/api/pairing_qr', '/api/pairing-qr'):
            hub_host = self.headers.get('Host', 'orbit-system-eight.vercel.app')
            qr_data = json.dumps({
                "hub": f"wss://{hub_host}/ws",
                "name": "ORBIT Cloud Edge",
                "version": "1.0.0"
            })
            qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={urllib.parse.quote(qr_data)}"
            self._send_json(200, {
                "ok": True,
                "ip": hub_host,
                "port": "443 (SSL/TLS)",
                "token": "cloud-verified",
                "qr_url": qr_url,
                "download_apk": "https://github.com/kramasrisurya/orbit/actions"
            })
        elif path.startswith('/api/enroll'):
            self._send_json(200, {
                "ok": True,
                "status": "completed",
                "token": "verified",
                "message": "Biometric identity verified via companion phone satellite"
            })
        elif path == '/api/clipboard':
            self._send_json(200, {
                "text": "ORBIT Ambient Awareness System deployed on Vercel"
            })
        else:
            self._send_json(200, {
                "name": "ORBIT — Ambient Awareness System",
                "version": "1.0.0",
                "repository": "https://github.com/kramasrisurya/orbit",
                "apk_download": "https://github.com/kramasrisurya/orbit/actions",
                "deployment": "Vercel Serverless"
            })

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip('/')

        content_length = int(self.headers.get('Content-Length', 0))
        body = {}
        if content_length > 0:
            try:
                raw_body = self.rfile.read(content_length)
                body = json.loads(raw_body.decode('utf-8'))
            except Exception:
                pass

        if path == '/api/command':
            action = body.get('action', 'unknown')
            self._send_json(200, {
                "ok": True,
                "action": action,
                "status": "simulated_on_cloud",
                "message": f"Command '{action}' acknowledged by Vercel Cloud Hub. Connect your local PC Hub to trigger desktop actions.",
                "eco_mode": body.get('enabled', False) if action == 'toggle_eco' else False,
                "paused": body.get('paused', False) if 'camera' in action else False
            })
        elif path in ('/api/clipboard', '/api/clipboard/send_to_phone'):
            self._send_json(200, {
                "ok": True,
                "message": "Text delivered to phone clipboard buffer",
                "length": len(body.get('text', ''))
            })
        elif path.startswith('/api/files'):
            self._send_json(200, {
                "ok": True,
                "message": "File received by ORBIT AirDrop Bridge"
            })
        elif path.startswith('/api/enroll'):
            self._send_json(200, {
                "ok": True,
                "token": "verified_cloud_token",
                "message": "Biometric verification authorized"
            })
        else:
            self._send_json(200, {
                "ok": True,
                "status": "acknowledged",
                "path": path
            })

    def _send_json(self, status: int, data: dict | list):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode('utf-8'))

    def _add_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
