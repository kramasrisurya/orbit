"""
ORBIT — Universal Control Engine.

Enables seamless cursor leap and keyboard input forwarding between PC and mobile.
When the user moves the mouse cursor to the edge of the laptop screen,
it leaps directly onto the mobile phone companion in real time.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from typing import Any

from core.event_bus import EventBus, OrbitEvent

logger = logging.getLogger("orbit.productivity.universal_control")

IS_WINDOWS = ctypes.windll is not None if hasattr(ctypes, "windll") else False


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class UniversalControl:
    """
    Monitors mouse cursor position and streams cursor/keyboard events to
    mobile phone when the cursor reaches the laptop screen boundary.
    """

    def __init__(self, bus: EventBus, enabled: bool = True) -> None:
        self._bus = bus
        self._enabled = enabled
        self._running = False
        self._thread: threading.Thread | None = None

        self._leaped = False
        self._phone_x = 0.5
        self._phone_y = 0.5
        self._last_edge_hit = 0.0
        self._anchor_x = 0
        self._anchor_y = 0
        self._left_down_prev = False
        self._right_down_prev = False
        self._down_keys: set[int] = set()

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> bool:
        self._enabled = enabled
        logger.info("Universal Control set_enabled: %s", enabled)
        return self._enabled

    def is_leaped(self) -> bool:
        return False

    def start(self) -> None:
        self._running = False
        logger.info("UniversalControl disabled")

    def stop(self) -> None:
        self._running = False
        logger.info("UniversalControl stopped")

    def _exit_leap(self) -> None:
        if not self._leaped:
            return
        self._leaped = False
        try:
            from utils.windows import ensure_input_desktop
            ensure_input_desktop()
            sh = ctypes.windll.user32.GetSystemMetrics(1)
            ret_y = int(self._phone_y * sh)
            ctypes.windll.user32.SetCursorPos(35, max(50, min(sh - 50, ret_y)))
        except Exception:
            pass

        self._bus.publish(OrbitEvent(
            type="UNIVERSAL_CONTROL_EVENT",
            source="universal_control",
            payload={"action": "cursor_exit"},
        ))
        logger.info("Universal Control: cursor returned to laptop screen")

    def _monitor_loop(self) -> None:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

        user32 = ctypes.windll.user32
        pt = POINT()
        adb_bin = r"C:\Users\hp\AppData\Local\Android\Sdk\platform-tools\adb.exe"

        while self._running:
            time.sleep(0.02)  # 50 Hz poll rate
            if not self._enabled:
                time.sleep(0.2)
                continue

            try:
                from utils.windows import ensure_input_desktop
                ensure_input_desktop()
                sw = user32.GetSystemMetrics(0)
                sh = user32.GetSystemMetrics(1)
                user32.GetCursorPos(ctypes.byref(pt))
                cx, cy = pt.x, pt.y

                # Check if user pressed ESC to return from mobile
                # VK_ESCAPE = 0x1B
                if self._leaped:
                    if user32.GetAsyncKeyState(0x1B) & 0x8000:
                        self._exit_leap()
                        time.sleep(0.25)
                        continue

                # STRICT TRIGGER: Peak left of laptop screen ONLY (cx <= 3)
                is_peak_left = (cx <= 3)

                if not self._leaped:
                    if is_peak_left:
                        now = time.time()
                        if self._last_edge_hit == 0.0:
                            self._last_edge_hit = now
                        elif now - self._last_edge_hit >= 0.02:  # ultra-responsive 20ms leap
                            # Leap onto mobile screen from right boundary
                            self._leaped = True
                            self._phone_x = 0.95
                            self._phone_y = max(0.05, min(0.95, cy / max(1, sh)))
                            # Anchor at offset from left edge so mouse has room to move left/right/up/down
                            self._anchor_x = 60
                            self._anchor_y = max(50, min(sh - 50, cy))
                            user32.SetCursorPos(self._anchor_x, self._anchor_y)
                            self._down_keys.clear()
                            self._bus.publish(OrbitEvent(
                                type="UNIVERSAL_CONTROL_EVENT",
                                source="universal_control",
                                payload={
                                    "action": "cursor_enter",
                                    "x": round(self._phone_x, 4),
                                    "y": round(self._phone_y, 4),
                                },
                            ))
                            logger.info("Universal Control: cursor leaped onto mobile screen from PEAK LEFT!")
                            self._last_edge_hit = 0.0
                    else:
                        self._last_edge_hit = 0.0

                else:
                    # Currently leaped onto mobile: calculate delta from anchor
                    dx = cx - self._anchor_x
                    dy = cy - self._anchor_y

                    # Return to laptop when moving back off the right edge of phone screen
                    if self._phone_x >= 0.99 and dx > 15:
                        self._exit_leap()
                        time.sleep(0.2)
                        continue

                    # Update virtual phone coordinates smoothly
                    if dx != 0 or dy != 0:
                        self._phone_x = max(0.01, min(0.99, self._phone_x + (dx / 320.0)))
                        self._phone_y = max(0.01, min(0.99, self._phone_y + (dy / 380.0)))
                        # Re-anchor cursor so next frame can measure fresh deltas
                        user32.SetCursorPos(self._anchor_x, self._anchor_y)

                    # Check mouse clicks: VK_LBUTTON = 0x01, VK_RBUTTON = 0x02
                    l_down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
                    r_down = bool(user32.GetAsyncKeyState(0x02) & 0x8000)

                    click_event = None
                    if l_down and not self._left_down_prev:
                        click_event = "click"
                        # Execute ADB tap across ANY app on Android (screen 1272 x 2800)
                        try:
                            import subprocess
                            px = int(self._phone_x * 1272)
                            py = int(self._phone_y * 2800)
                            subprocess.Popen([adb_bin, "shell", "input", "tap", str(px), str(py)])
                        except Exception:
                            pass
                    elif r_down and not self._right_down_prev:
                        click_event = "right_click"
                        # Android Back key
                        try:
                            import subprocess
                            subprocess.Popen([adb_bin, "shell", "input", "keyevent", "4"])
                        except Exception:
                            pass

                    self._left_down_prev = l_down
                    self._right_down_prev = r_down

                    # Publish cursor motion / click
                    if dx != 0 or dy != 0 or click_event:
                        self._bus.publish(OrbitEvent(
                            type="UNIVERSAL_CONTROL_EVENT",
                            source="universal_control",
                            payload={
                                "action": "cursor_move",
                                "x": round(self._phone_x, 4),
                                "y": round(self._phone_y, 4),
                                "click": click_event,
                            },
                        ))

                    # Capture keyboard typing to forward to mobile
                    shift = bool(user32.GetAsyncKeyState(0x10) & 0x8000)
                    caps = bool(user32.GetKeyState(0x14) & 1)

                    KEYS_TO_SCAN = [
                        (0x08, "Backspace", ""),
                        (0x09, "Tab", "\t"),
                        (0x0D, "Enter", "\n"),
                        (0x20, "Space", " "),
                        (0x2E, "Delete", ""),
                    ]
                    # Digits 0-9
                    shift_digits = {
                        0x30: ")", 0x31: "!", 0x32: "@", 0x33: "#", 0x34: "$",
                        0x35: "%", 0x36: "^", 0x37: "&", 0x38: "*", 0x39: "(",
                    }
                    for vk in range(0x30, 0x3A):
                        char = shift_digits[vk] if shift else chr(vk)
                        KEYS_TO_SCAN.append((vk, char, char))
                    # Letters A-Z
                    for vk in range(0x41, 0x5B):
                        upper = shift ^ caps
                        c = chr(vk) if upper else chr(vk + 32)
                        KEYS_TO_SCAN.append((vk, c, c))

                    for vk, key_name, char in KEYS_TO_SCAN:
                        is_down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
                        if is_down and vk not in self._down_keys:
                            self._down_keys.add(vk)
                            # Forward keystroke to phone via ADB across ANY active app
                            try:
                                import subprocess
                                if key_name == "Backspace":
                                    subprocess.Popen([adb_bin, "shell", "input", "keyevent", "67"])
                                elif key_name == "Enter":
                                    subprocess.Popen([adb_bin, "shell", "input", "keyevent", "66"])
                                elif key_name == "Space":
                                    subprocess.Popen([adb_bin, "shell", "input", "keyevent", "62"])
                                elif key_name == "Tab":
                                    subprocess.Popen([adb_bin, "shell", "input", "keyevent", "61"])
                                elif char:
                                    safe_text = char.replace(" ", "%s").replace("&", "\\&").replace("<", "\\<").replace(">", "\\>")
                                    subprocess.Popen([adb_bin, "shell", "input", "text", safe_text])
                            except Exception:
                                pass

                            self._bus.publish(OrbitEvent(
                                type="UNIVERSAL_CONTROL_EVENT",
                                source="universal_control",
                                payload={
                                    "action": "type",
                                    "key": key_name,
                                    "char": char,
                                },
                            ))
                        elif not is_down and vk in self._down_keys:
                            self._down_keys.discard(vk)

            except Exception:
                time.sleep(0.1)

            except Exception:
                time.sleep(0.1)
