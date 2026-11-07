# ORBIT — Personal Ambient Awareness System

ORBIT is a **local-first** presence, security, and control system that runs on a
Windows laptop and an Android phone. The laptop's webcam and the phone's sensors
(BLE, accelerometer, NFC, Wi-Fi, GPS) feed into a central Python engine on the PC.

That engine knows when you're present, verifies it's *you*, auto-locks the PC on
absence, detects intruders, controls the desktop via hand gestures and phone
commands, switches environment modes via NFC tags, monitors posture and stress,
syncs your clipboard, and exposes a live dashboard at `localhost`.

Everything runs on your own hardware. No cloud. No telemetry. No accounts.

---

## What it does

**Presence & Security**
- Detects when you're at the PC (webcam + phone proximity)
- Recognizes the enrolled user by face
- Auto-locks the workstation when you leave
- Detects a second person (intruder) → snapshot, recording, phone alert, lock
- Gates sensitive actions (lock, launch) behind phone approval + biometrics

**Control**
- Hand gestures (open palm, fist, point, wave) drive desktop actions
- Shake the phone (1/2/3×) for screenshot / lock / next-app
- Full remote-control panel on the phone (lock, volume, mute, media)
- NFC tags switch environment modes (work, meeting, away, off)

**Health**
- Posture monitoring (hunched, too-close, tilted) with nudges
- Screen-break reminders
- Stress detection from sustained facial expression
- Daily health/usage report to your phone

**Productivity**
- Focus sessions (phone is the source of truth for the timer)
- Two-way clipboard sync (phone ↔ PC)
- Environment modes: wallpaper, apps, notification level, minimized workspace

**Dashboard**
- Live React-free dashboard at `http://localhost:8080`
- Real-time presence, mode, focus, camera feed, event log
- Quick actions: start/stop focus, switch mode, pair phone

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        ANDROID PHONE                          │
│  BLE broadcast · Accelerometer (shake) · NFC · Geofence      │
│  WebSocket (AES-256-GCM) · FCM push · Biometric approval     │
└───────────────▲─────────────────────────────────▲────────────┘
                │ ws:// (encrypted)               │ BLE / NFC
┌───────────────┴─────────────────────────────────┴────────────┐
│                     PC HUB (Python 3.11)                      │
│                                                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │  Vision  │  │   Phone  │  │  Command │  │   Security   │  │
│  │  Engine  │  │  Modules │  │  Engine  │  │  (intruder)  │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘  │
│       └──────────────┴──────┬──────┴───────────────┘          │
│                              ▼                                 │
│                     ┌──────────────┐                          │
│                     │  EVENT BUS   │  (thread-safe pub/sub)   │
│                     └──────┬───────┘                          │
│        ┌───────────────────┼────────────────────┐             │
│        ▼                   ▼                    ▼             │
│  ┌───────────┐      ┌───────────┐        ┌──────────────┐     │
│  │ Presence  │      │   Modes   │        │  Health /    │     │
│  │   Core    │      │  Manager  │        │ Productivity │     │
│  └───────────┘      └───────────┘        └──────────────┘     │
│                              │                                 │
│              ┌───────────────┼───────────────┐                 │
│              ▼               ▼               ▼                 │
│        ┌──────────┐    ┌──────────┐    ┌──────────┐           │
│        │  SQLite  │    │ Dashboard│    │  REST +  │           │
│        │  (WAL)   │    │  (aiohttp)│   │  WebSocket│           │
│        └──────────┘    └──────────┘    └──────────┘           │
└────────────────────────────────────────────────────────────────┘
```

**The Event Bus** is the spine. Every subsystem publishes typed events
(`PRESENCE_CHANGED`, `GESTURE_RECOGNIZED`, `INTRUDER_ALERT`, …) and subscribes
to the ones it cares about. Nothing talks to anything else directly — which is
what keeps 30+ modules from turning into spaghetti.

---

## Project structure

```
Orbit/
├── requirements.txt            # PC hub Python dependencies
├── .gitignore
├── orbit/                      # PC HUB (Python)
│   ├── main.py                 # Entry point — wires & runs everything
│   ├── config.py               # Typed config loader (~/.orbit/config.yaml)
│   ├── config/default.yaml     # Bundled default configuration
│   ├── core/
│   │   ├── event_bus.py        # Thread-safe pub/sub + event constants
│   │   ├── presence.py         # Presence state machine (face + phone + BLE)
│   │   └── modes.py            # Mode state machine + transitions
│   ├── vision/
│   │   ├── engine.py           # Camera thread, orchestrates sub-processors
│   │   ├── face_detect.py      # MediaPipe face detection
│   │   ├── face_recognize.py   # Face encoding + matching
│   │   ├── gaze.py             # Gaze / attention estimation
│   │   ├── gestures.py         # Hand-gesture recognition
│   │   ├── emotion.py          # Emotion classification
│   │   └── posture.py          # Posture (head pose) analysis
│   ├── phone/
│   │   ├── websocket_server.py # Encrypted WS server + AES handshake
│   │   ├── ble_listener.py     # BLE proximity scanning
│   │   ├── notifications.py    # WS + FCM push delivery
│   │   └── pairing.py          # QR-code pairing (256-bit key)
│   ├── command/
│   │   ├── engine.py           # Maps events → actions (with approval gate)
│   │   ├── windows_api.py      # Screenshot, app launch, volume, input
│   │   ├── apps.py             # Batch launch/close/minimize
│   │   └── wallpaper.py        # Wallpaper changes
│   ├── security/
│   │   ├── intruder.py         # Intruder detection + response
│   │   ├── snapshots.py        # Timestamped JPEG snapshots
│   │   ├── recording.py        # Background MP4 recording
│   │   └── approval.py         # Phone-approval gate (timeout = deny)
│   ├── health/
│   │   ├── posture_monitor.py  # Posture nudges
│   │   ├── break_reminder.py   # Screen-break reminders
│   │   ├── stress.py           # Sustained-stress detection
│   │   └── daily_report.py     # Daily summary to phone
│   ├── productivity/
│   │   ├── focus.py            # Focus session tracking
│   │   ├── clipboard_sync.py   # Two-way clipboard sync
│   │   └── mode_executor.py    # Applies mode side-effects
│   ├── dashboard/
│   │   ├── server.py           # aiohttp REST + static + WS routes
│   │   ├── websocket.py        # Real-time event bridge to browser
│   │   └── static/index.html   # The dashboard UI
│   ├── db/
│   │   ├── database.py         # Thread-safe SQLite (WAL)
│   │   └── repositories.py     # Typed per-table repositories
│   └── utils/
│       ├── logger.py           # Central logging setup
│       ├── crypto.py           # Key generation / persistence
│       └── windows.py          # Win32 input, lock, wallpaper, clipboard
└── orbit-phone/                # ANDROID APP (Kotlin + Jetpack Compose)
    ├── settings.gradle
    ├── build.gradle
    ├── gradle.properties
    └── app/
        ├── build.gradle
        ├── proguard-rules.pro
        └── src/main/
            ├── AndroidManifest.xml
            ├── res/values/themes.xml
            └── java/com/orbit/app/
                ├── OrbitApp.kt              # Application + service bootstrap
                ├── data/
                │   ├── Models.kt            # WS message data classes
                │   ├── Prefs.kt             # Typed SharedPreferences
                │   └── PcConnection.kt      # Connection state (StateFlow)
                ├── service/
                │   ├── BleService.kt        # BLE broadcast (foreground)
                │   ├── WebSocketService.kt  # Encrypted WS (foreground)
                │   ├── GeoFenceService.kt   # Home geofence (foreground)
                │   ├── ShakeDetector.kt     # Accelerometer shake counting
                │   └── NotificationService.kt # FCM receiver
                ├── ui/
                │   ├── MainActivity.kt      # Dashboard + NFC
                │   ├── RemotePanel.kt       # 8-button remote control
                │   ├── TimerPanel.kt        # Focus timer (source of truth)
                │   ├── MusicPanel.kt        # Media controls
                │   ├── ApprovalScreen.kt    # Biometric approval (full-screen)
                │   └── SettingsScreen.kt    # All settings
                └── util/
                    ├── Constants.kt         # UUIDs, ports, thresholds
                    └── Crypto.kt            # AES-256-GCM
```

---

## Getting started

### Prerequisites

- **Windows 10/11** laptop with a webcam
- **Python 3.11+**
- **Android phone** (API 26+ / Android 8.0+)
- An NFC tag (for mode switching — optional)
- Android Studio (to build the phone app)

### 1. Set up the PC hub

```bash
cd Orbit
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

> `dlib` and `face-recognition` need a C++ compiler (Visual Studio Build
> Tools) to install from source. `mediapipe` and `opencv-python` are
> prebuilt wheels.

### 2. Configure

On first run, ORBIT copies `orbit/config/default.yaml` to `~/.orbit/config.yaml`.
Edit that file to set your camera index, ports, presence thresholds, gesture
mappings, and mode definitions.

```yaml
# ~/.orbit/config.yaml  (excerpt)
vision:
  camera_index: 0
  fps: 15
phone:
  websocket_port: 8765
presence:
  lock_timeout_sec: 120
  require_face: true
```

### 3. Enroll your face

Run the enrollment helper (see below) and look at the camera. Your face
encoding is stored in the local SQLite database.

### 4. Run the hub

```bash
python orbit/main.py
```

You'll see:

```
=== ORBIT starting ===
Dashboard: http://localhost:8080
Phone WS:  ws://0.0.0.0:8765
=== ORBIT running ===
```

### 5. Build & pair the phone app

1. Open `orbit-phone/` in Android Studio.
2. Build and install the app on your phone.
3. Open the dashboard → **Pair Phone** → scan the QR code with the app.
4. The phone connects, completes the AES handshake, and you're paired.

### 6. Open the dashboard

Navigate to `http://localhost:8080` for the live view.

### 7. Deploy to Vercel (Cloud Web Hub)

You can deploy the ORBIT Web Dashboard globally to Vercel in 1 click:

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Fkramasrisurya%2Forbit)

- **Instant Cloud Showcase**: Fully interactive ambient telemetry, biometric radar demo, workspace mode controls, and focus timer in your browser.
- **Link to Laptop Hub**: Click **Hub** in the header to enter your local machine's LAN IP or tunnel URL (`ngrok` / `cloudflared` / Tailscale) to stream hardware optical feeds and trigger Windows desktop modes remotely.
- **1-Tap APK Download**: Mobile visitors can download the latest Android companion APK artifact directly from the web interface.

---

## Configuration reference

All settings live in `~/.orbit/config.yaml`. The full schema (with defaults)
is in `orbit/config/default.yaml`. Key sections:

| Section | What it controls |
|---------|------------------|
| `vision` | Camera index, FPS, detection thresholds |
| `phone` | WebSocket port, BLE UUID, approval timeout |
| `presence` | Lock timeout, face requirement, signal weights |
| `gestures` | Gesture → action mapping |
| `modes` | Per-mode wallpaper, apps, notification level |
| `security` | Intruder action, recording, snapshot dirs |
| `health` | Break interval, stress threshold, report time |
| `dashboard` | Port for the web dashboard |

Call `config.reload()` (or restart) to pick up changes.

---

## Security model

ORBIT is **local-first**, but it's not naive about security:

- **Transport** — phone↔PC WebSocket is encrypted with **AES-256-GCM**. A
  256-bit pairing key is generated on the PC and delivered to the phone via a
  one-time QR code. A per-session key is derived during the handshake.
- **Approval** — sensitive actions (locking, launching apps) require an
  explicit **phone approval + biometric** (fingerprint/face). If the phone
  doesn't respond within the timeout, the action is **denied by default**.
- **Intruder response** — a second face triggers snapshot + recording + phone
  alert, and (if configured) an immediate workstation lock.
- **Data** — everything (events, stats, face encodings, alerts) stays in a
  local SQLite database. Nothing leaves your machine except to *your* phone.

> This is a personal system for your own apartment/office. It is not
> hardened against a determined network attacker on your LAN — run it on a
> trusted network.

---

## The event bus

Every cross-module interaction goes through the `EventBus`
(`orbit/core/event_bus.py`). It's a thread-safe publish/subscribe with typed
event constants. A wildcard `"__all__"` subscription receives every event
(used by the dashboard bridge and the event logger).

Representative events:

```
PRESENCE_CHANGED      FACE_DETECTED / FACE_NOT_DETECTED
USER_RECOGNIZED       UNKNOWN_FACE
GAZE_CHANGED          GESTURE_RECOGNIZED
EMOTION_DETECTED      POSTURE_ALERT
MULTI_PERSON_DETECTED INTRUDER_ALERT
PC_LOCKED             MODE_CHANGED
PHONE_CONNECTED       PHONE_DISCONNECTED
PHONE_SHAKE           PHONE_REMOTE_COMMAND
NFC_MODE_TRIGGERED    APPROVAL_REQUEST / GRANTED / DENIED
FOCUS_SESSION_START   FOCUS_SESSION_END
CLIPBOARD_SYNC        DASHBOARD_UPDATE
```

---

## Extending ORBIT

Because everything is event-driven, adding a feature is usually:

1. **Publish** a new event from a producer (e.g., a new sensor).
2. **Subscribe** a handler in a consumer module.
3. No other module needs to change.

Examples:
- *Add a new gesture* → map it in `config.yaml` `gestures:` and add an action
  branch in `command/engine.py`.
- *Add a new mode* → add it to `modes:` in config and define its
  wallpaper/apps/notifications.
- *Add a new health metric* → subscribe to an existing vision event in a new
  `health/` module.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Camera won't open | Change `vision.camera_index`; close other camera apps |
| `dlib` fails to install | Install Visual Studio Build Tools, then `pip install dlib` |
| Phone can't connect | Same Wi-Fi as PC? Check `phone.websocket_port` and firewall |
| Not recognizing you | Re-enroll your face; improve lighting |
| PC locks too eagerly | Increase `presence.lock_timeout_sec` |
| No FCM push | Add `google-services.json` to the app; otherwise WS notifications still work |

---

## Status

This is a **research prototype** — a complete, working reference
implementation of the full feature set. Treat it as a starting point, not a
polished product. See the inline `TODO`/`FIXME` notes for known rough edges
(notably: the face-recognition pipeline assumes `face-recognition`/dlib, and
the BLE proximity model is a simple RSSI threshold).

---

*Built local-first. Your presence, your data, your machine.*
