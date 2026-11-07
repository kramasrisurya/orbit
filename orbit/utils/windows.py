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
import time
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

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

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

def ensure_input_desktop() -> None:
    """Ensure the calling thread is attached to the active user's interactive desktop."""
    if not IS_WINDOWS or not user32:
        return
    try:
        hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
    except Exception:
        pass


def lock_workstation() -> None:
    """Lock the Windows workstation."""
    if not IS_WINDOWS:
        logger.debug("lock_workstation: not on Windows, skipping")
        return
    try:
        ensure_input_desktop()
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


def move_cursor(dx: int, dy: int) -> None:
    """Move cursor by (dx, dy) and update position."""
    if not IS_WINDOWS or not user32:
        return
    try:
        ensure_input_desktop()
        pt = POINT()
        if user32.GetCursorPos(ctypes.byref(pt)):
            user32.SetCursorPos(pt.x + dx, pt.y + dy)
        user32.mouse_event(MOUSEEVENTF_MOVE, dx, dy, 0, 0)
    except Exception as e:
        logger.error("Failed to move cursor: %s", e)


def mouse_click(button: str = "left") -> None:
    """Simulate mouse click on active desktop."""
    if not IS_WINDOWS or not user32:
        return
    try:
        ensure_input_desktop()
        if button == "left":
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        elif button in ("double", "double_left"):
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.04)
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        elif button == "right":
            # MOUSEEVENTF_RIGHTDOWN = 0x0008, MOUSEEVENTF_RIGHTUP = 0x0010
            user32.mouse_event(0x0008, 0, 0, 0, 0)
            user32.mouse_event(0x0010, 0, 0, 0, 0)
    except Exception as e:
        logger.error("Failed to click mouse: %s", e)


def mouse_scroll(dy: int) -> None:
    """Simulate mouse wheel scroll."""
    if not IS_WINDOWS or not user32:
        return
    try:
        ensure_input_desktop()
        # MOUSEEVENTF_WHEEL = 0x0800
        user32.mouse_event(0x0800, 0, 0, dy, 0)
    except Exception as e:
        logger.error("Failed to scroll mouse: %s", e)


def get_clipboard() -> str:
    """Read the Windows clipboard as text with robust retries."""
    if not IS_WINDOWS:
        return ""
    import time
    try:
        import win32clipboard, win32con
        for _ in range(8):
            try:
                win32clipboard.OpenClipboard()
                try:
                    if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                        val = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                        return val or ""
                    return ""
                finally:
                    win32clipboard.CloseClipboard()
            except Exception:
                time.sleep(0.02)
    except ImportError:
        pass

    if not user32 or not kernel32:
        return ""
    for _ in range(8):
        if user32.OpenClipboard(0):
            break
        time.sleep(0.02)
    else:
        return ""

    try:
        CF_UNICODETEXT = 13
        user32.GetClipboardData.restype = ctypes.c_void_p
        user32.GetClipboardData.argtypes = [ctypes.c_uint]
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(h)
    except Exception as e:
        logger.error("Failed to read clipboard: %s", e)
        return ""
    finally:
        user32.CloseClipboard()


def set_clipboard(text: str) -> None:
    """Write text to the Windows clipboard with robust retries."""
    if not IS_WINDOWS:
        return
    import time
    ensure_input_desktop()
    try:
        import win32clipboard, win32con
        for _ in range(8):
            try:
                win32clipboard.OpenClipboard()
                try:
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
                    return
                finally:
                    win32clipboard.CloseClipboard()
            except Exception:
                time.sleep(0.02)
    except ImportError:
        pass

    if not user32 or not kernel32:
        return
    for _ in range(8):
        if user32.OpenClipboard(0):
            break
        time.sleep(0.02)
    else:
        return

    try:
        user32.EmptyClipboard()
        CF_UNICODETEXT = 13
        text_bytes = (text + "\0").encode("utf-16-le")

        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

        # GMEM_MOVEABLE = 0x0002
        h = kernel32.GlobalAlloc(0x0002, len(text_bytes))
        if h:
            ptr = kernel32.GlobalLock(h)
            if ptr:
                ctypes.memmove(ptr, text_bytes, len(text_bytes))
                kernel32.GlobalUnlock(h)
                user32.SetClipboardData(CF_UNICODETEXT, h)
    finally:
        user32.CloseClipboard()


def type_text(text: str) -> None:
    """Simulate typing text into the currently active window via SendInput."""
    if not IS_WINDOWS or not user32:
        return
    try:
        ensure_input_desktop()
        KEYEVENTF_UNICODE = 0x0004
        KEYEVENTF_KEYUP = 0x0002
        inputs = []
        for ch in text:
            if ch == "\b":
                d = INPUT()
                d.type = INPUT_KEYBOARD
                d.union.ki.wVk = 0x08  # VK_BACK
                d.union.ki.dwFlags = 0
                inputs.append(d)
                u = INPUT()
                u.type = INPUT_KEYBOARD
                u.union.ki.wVk = 0x08
                u.union.ki.dwFlags = KEYEVENTF_KEYUP
                inputs.append(u)
                continue

            code = ord(ch)
            d = INPUT()
            d.type = INPUT_KEYBOARD
            d.union.ki.wScan = code
            d.union.ki.dwFlags = KEYEVENTF_UNICODE
            inputs.append(d)
            u = INPUT()
            u.type = INPUT_KEYBOARD
            u.union.ki.wScan = code
            u.union.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
            inputs.append(u)
        if inputs:
            arr = (INPUT * len(inputs))(*inputs)
            user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    except Exception as e:
        logger.error("Failed to type text: %s", e)


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
