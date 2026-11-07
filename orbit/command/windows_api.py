"""
Thin wrapper around utils/windows.py with higher-level actions.

Adds screenshot capture, app launch/resolve, and volume control.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from utils import windows

logger = logging.getLogger("orbit.command.windows_api")

SCREENSHOT_DIR = Path.home() / "ORBIT" / "screenshots"

def find_brave() -> str | None:
    """Find Brave Browser executable across standard Windows installation paths."""
    if sys.platform != "win32":
        return shutil.which("brave") or shutil.which("brave-browser")
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return shutil.which("brave")


# Common app name → executable/command resolution
APP_ALIASES: dict[str, str] = {
    "code": "code",
    "firefox": "firefox",
    "chrome": "chrome",
    "brave": find_brave() or "brave",
    "youtube": "https://www.youtube.com",
    "aums": "https://aumsam.amrita.edu/cas/login?service=https%3A%2F%2Faumsam.amrita.edu%2Faums%2FJsp%2FAttendance%2FAttendanceReportStudent.jsp%3Faction%3DUMS-ATD_INIT_ATDREPORTSTUD_SCREEN%26isMenu%3Dtrue%26pagePostSerialID%3D1",
    "terminal": "wt" if sys.platform == "win32" else "xterm",
    "powershell": "powershell",
    "cmd": "cmd",
    "notepad": "notepad",
    "zoom": "zoom",
    "spotify": "spotify",
    "vscode": "code",
    "explorer": "explorer",
    "calc": "calc",
}


def take_screenshot() -> Path | None:
    """Capture the screen via Win32 GDI, save to ~/ORBIT/screenshots and ~/Downloads."""
    try:
        from PIL import Image
        import ctypes
        from ctypes import wintypes
        import shutil

        day = datetime.now().strftime("%Y-%m-%d")
        day_dir = SCREENSHOT_DIR / day
        day_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%H%M%S")
        path = day_dir / f"{ts}.png"

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        # Attach to input desktop
        hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)

        width = user32.GetSystemMetrics(0)
        height = user32.GetSystemMetrics(1)

        hdc_screen = user32.GetDC(0)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        hbitmap = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
        gdi32.SelectObject(hdc_mem, hbitmap)

        gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, 0, 0, 0x00CC0020)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ('biSize', wintypes.DWORD),
                ('biWidth', wintypes.LONG),
                ('biHeight', wintypes.LONG),
                ('biPlanes', wintypes.WORD),
                ('biBitCount', wintypes.WORD),
                ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD),
                ('biXPelsPerMeter', wintypes.LONG),
                ('biYPelsPerMeter', wintypes.LONG),
                ('biClrUsed', wintypes.DWORD),
                ('biClrImportant', wintypes.DWORD),
            ]

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = width
        bmi.biHeight = -height
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0

        buf = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(hdc_mem, hbitmap, 0, height, buf, ctypes.byref(bmi), 0)

        img = Image.frombuffer('RGBA', (width, height), buf, 'raw', 'BGRA', 0, 1)
        img.save(path)

        # Also copy to Downloads folder for instant access
        downloads_dir = Path.home() / "Downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, downloads_dir / f"screenshot_{ts}.png")

        gdi32.DeleteObject(hbitmap)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)

        logger.info("Screenshot saved: %s (and in Downloads)", path)
        return path
    except Exception:
        logger.exception("Screenshot failed")
        return None


def launch_app(app_name: str) -> bool:
    """
    Resolve an app name to an executable or URL and launch it (detached).
    Returns True on success.
    """
    cmd = APP_ALIASES.get(app_name.lower(), app_name)

    # Handle web URL shortcuts
    if cmd.startswith("http://") or cmd.startswith("https://"):
        try:
            brave_path = find_brave()
            if brave_path and Path(brave_path).exists() and sys.platform == "win32":
                import ctypes
                ctypes.windll.shell32.ShellExecuteW(None, "open", str(brave_path), cmd, None, 1)
                logger.info("Opened URL %s in Brave via ShellExecuteW", cmd)
                return True
            import webbrowser
            webbrowser.open(cmd)
            logger.info("Opened URL %s in default browser", cmd)
            return True
        except Exception:
            logger.exception("Failed to open URL shortcut: %s", cmd)
            return False

    # Check direct executable file path
    if Path(cmd).exists():
        resolved = cmd
    else:
        # Check if it's on PATH
        resolved = shutil.which(cmd)
        if resolved is None:
            # Try common Windows locations
            if sys.platform == "win32":
                program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
                local = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
                for base in (program_files, local):
                    candidate = Path(base) / cmd
                    if candidate.exists() or (candidate.with_suffix(".exe")).exists():
                        resolved = str(candidate)
                        break
            if resolved is None:
                logger.warning("Cannot resolve app: %s (as '%s')", app_name, cmd)
                return False

    try:
        if sys.platform == "win32":
            import ctypes
            # Use ShellExecuteW for GUI apps to guarantee proper foreground focus
            res = ctypes.windll.shell32.ShellExecuteW(None, "open", str(resolved), None, None, 1)
            if res <= 32:
                # Fallback to subprocess if ShellExecute returns error
                subprocess.Popen(
                    [resolved],
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        else:
            subprocess.Popen(
                [resolved],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        logger.info("Launched app: %s → %s", app_name, resolved)
        return True
    except Exception:
        logger.exception("Failed to launch app: %s", app_name)
        return False


def close_app(app_name: str) -> bool:
    """Force-kill an app by image name (taskkill on Windows)."""
    exe = f"{app_name}.exe" if not app_name.lower().endswith(".exe") else app_name
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/IM", exe, "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.run(
                ["pkill", "-f", app_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        logger.info("Closed app: %s", app_name)
        return True
    except Exception:
        logger.exception("Failed to close app: %s", app_name)
        return False


def minimize_all() -> None:
    """Show desktop (Win+D), then toggle back is a second press.
    We press once to minimize everything to the desktop."""
    windows.send_input_event("win+d")
    time.sleep(0.3)
    logger.info("Minimized all windows (showed desktop)")


def mute_system() -> None:
    """Mute the system volume using standard Windows virtual key events."""
    if windows.IS_WINDOWS and windows.user32:
        # VK_VOLUME_MUTE = 0xAD
        windows.user32.keybd_event(0xAD, 0, 0, 0)
        windows.user32.keybd_event(0xAD, 0, 2, 0)
    logger.info("Volume mute toggled")


def unmute_system() -> None:
    """Unmute the system volume using Windows volume-up key event."""
    if windows.IS_WINDOWS and windows.user32:
        # Volume Up (0xAF) automatically unmutes audio on Windows
        windows.user32.keybd_event(0xAF, 0, 0, 0)
        windows.user32.keybd_event(0xAF, 0, 2, 0)
        windows.user32.keybd_event(0xAE, 0, 0, 0)
        windows.user32.keybd_event(0xAE, 0, 2, 0)
    logger.info("Volume unmuted")
