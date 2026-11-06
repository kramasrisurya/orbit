"""
Windows-specific system utilities.

All functions are guarded so they degrade gracefully on non-Windows
platforms (useful for development on Linux/macOS).
"""

from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("orbit.utils.windows")

IS_WINDOWS = sys.platform == "win32"

# ---------------------------------------------------------------------------
# ctypes structures for SendInput
#
# The constants and ctypes structures are defined UNCONDITIONALLY so that
# module-level references (e.g. function default-argument values like
# `flags: int = MOUSEEVENTF_MOVE`) don't raise NameError on non-Windows
# platforms. The Win32 DLL handles (user32/kernel32) are only bound on
# Windows; every public function already guards with `if not IS_WINDOWS`.
# ---------------------------------------------------------------------------
user32 = ctypes.windll.user32 if IS_WINDOWS else None
kernel32 = ctypes.windll.kernel32 if IS_WINDOWS else None

# Virtual-key constants
VK_TABLE: dict[str, int] = {
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
    "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
    "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
    "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
    "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59,
    "z": 0x5A,
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "space": 0x20,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
    "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
    "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "alt": 0x12, "ctrl": 0x11, "shift": 0x10, "win": 0x5B,
    "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "backspace": 0x08,
}

KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]

class INPUTUNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT),
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", INPUTUNION),
    ]

INPUT_KEYBOARD = 1
INPUT_MOUSE = 0


def _send_input(inputs: list[INPUT]) -> int:
    """Send a batch of INPUT structures to Windows."""
    if not IS_WINDOWS:
        return 0
    arr = (INPUT * len(inputs))(*inputs)
    return user32.SendInput(len(inputs), ctypes.byref(arr), ctypes.sizeof(INPUT))


def _key_input(vk: int, key_up: bool = False) -> INPUT:
    """Build a single keyboard INPUT structure."""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk
    inp.union.ki.dwFlags = KEYEVENTF_KEYUP if key_up else 0
    return inp


def _mouse_input(dx: int = 0, dy: int = 0, flags: int = MOUSEEVENTF_MOVE) -> INPUT:
    """Build a mouse INPUT structure with the given event flags."""
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dx = dx
    inp.union.mi.dy = dy
    inp.union.mi.dwFlags = flags
    return inp


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lock_workstation() -> None:
    """Lock the Windows workstation."""
    if not IS_WINDOWS:
        logger.debug("lock_workstation: not on Windows, skipping")
        return
    try:
        user32.LockWorkStation()
        logger.info("Workstation locked")
    except Exception as e:
        logger.error("Failed to lock workstation: %s", e)


def send_input_event(key: str) -> None:
    """
    Synthesize an input event.
    Accepts:
      - Compound keys: "alt+tab", "win+d", "ctrl+c"
      - Mouse actions: "click" (left click at current position)
      - Volume: "volume_up", "volume_down" (via numpad or media keys)
    """
    if not IS_WINDOWS:
        logger.debug("send_input_event(%s): not on Windows, skipping", key)
        return
    try:
        k = key.lower().strip()

        # Mouse click
        if k == "click":
            inputs = [
                _mouse_input(0, 0, MOUSEEVENTF_LEFTDOWN),
                _mouse_input(0, 0, MOUSEEVENTF_LEFTUP),
            ]
            _send_input(inputs)
            logger.info("Sent mouse click")
            return

        # Volume up (media key VK_VOLUME_UP = 0xAF)
        if k == "volume_up":
            inputs = [_key_input(0xAF)]
            _send_input(inputs)
            logger.info("Sent volume up")
            return

        # Volume down (media key VK_VOLUME_DOWN = 0xAE)
        if k == "volume_down":
            inputs = [_key_input(0xAE)]
            _send_input(inputs)
            logger.info("Sent volume down")
            return

        # Standard keyboard combo
        parts = k.split("+")
        vks = []
        for p in parts:
            vk = VK_TABLE.get(p)
            if vk is None:
                logger.warning("Unknown key: %s", p)
                return
            vks.append(vk)

        inputs: list[INPUT] = []
        for vk in vks:
            inputs.append(_key_input(vk, key_up=False))
        for vk in reversed(vks):
            inputs.append(_key_input(vk, key_up=True))

        _send_input(inputs)
        logger.info("Sent input event: %s", key)
    except Exception as e:
        logger.error("Failed to send input event '%s': %s", key, e)


def simulate_activity() -> None:
    """Send a zero-pixel mouse move to reset the idle timer."""
    if not IS_WINDOWS:
        return
    try:
        _send_input([_mouse_input(0, 0)])
    except Exception as e:
        logger.debug("simulate_activity failed: %s", e)


def get_clipboard() -> str:
    """Read the Windows clipboard as text."""
    if not IS_WINDOWS:
        return ""
    try:
        user32.OpenClipboard(0)
        try:
            CF_UNICODETEXT = 13
            h = user32.GetClipboardData(CF_UNICODETEXT)
            if not h:
                return ""
            ptr = ctypes.cast(h, ctypes.c_wchar_p)
            return ptr.value or ""
        finally:
            user32.CloseClipboard()
    except Exception as e:
        logger.error("Failed to read clipboard: %s", e)
        return ""


def set_clipboard(text: str) -> None:
    """Write text to the Windows clipboard."""
    if not IS_WINDOWS:
        return
    try:
        user32.OpenClipboard(0)
        try:
            user32.EmptyClipboard()
            CF_UNICODETEXT = 13
            buf = ctypes.create_unicode_buffer(text, len(text) + 1)
            h = kernel32.GlobalAlloc(0x0042, ctypes.sizeof(buf))  # GMEM_MOVEABLE
            ctypes.memmove(h, buf, ctypes.sizeof(buf))
            kernel32.GlobalLock = kernel32.GlobalLock
            user32.SetClipboardData(CF_UNICODETEXT, h)
        finally:
            user32.CloseClipboard()
    except Exception as e:
        logger.error("Failed to set clipboard: %s", e)


def change_wallpaper(path: str) -> bool:
    """Change the desktop wallpaper via SystemParametersInfoW."""
    if not IS_WINDOWS:
        logger.debug("change_wallpaper: not on Windows, skipping")
        return False
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            logger.warning("Wallpaper file not found: %s", p)
            return False
        SPI_SETDESKWALLPAPER = 0x0014
        SPIF_UPDATEINIFILE = 0x01
        SPIF_SENDCHANGE = 0x02
        result = user32.SystemParametersInfoW(
            SPI_SETDESKWALLPAPER, 0, str(p),
            SPIF_UPDATEINIFILE | SPIF_SENDCHANGE,
        )
        if result:
            logger.info("Wallpaper changed to: %s", p)
            return True
        logger.warning("SystemParametersInfoW failed for wallpaper")
        return False
    except Exception as e:
        logger.error("Failed to change wallpaper: %s", e)
        return False


def show_toast(title: str, message: str) -> None:
    """Show a Windows toast notification."""
    if not IS_WINDOWS:
        logger.debug("show_toast: not on Windows, skipping")
        return
    try:
        from win10toast import ToastNotifier
        toaster = ToastNotifier()
        toaster.show_toast(title, message, duration=5, threaded=True)
    except ImportError:
        logger.warning("win10toast not installed; falling back to logging")
        logger.info("TOAST: %s — %s", title, message)
    except Exception as e:
        logger.error("Failed to show toast: %s", e)


def get_screen_size() -> tuple[int, int]:
    """Return (width, height) of the primary screen."""
    if not IS_WINDOWS:
        return (1920, 1080)
    try:
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        return (w, h)
    except Exception:
        return (1920, 1080)
