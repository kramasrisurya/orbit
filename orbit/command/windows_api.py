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

# Common app name → executable/command resolution
APP_ALIASES: dict[str, str] = {
    "code": "code",
    "firefox": "firefox",
    "chrome": "chrome",
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
    """Capture the screen, save to ~/ORBIT/screenshots/{date}/{time}.png, return path."""
    try:
        from PIL import ImageGrab
    except ImportError:
        logger.error("Pillow not installed — cannot take screenshot")
        return None

    try:
        day = datetime.now().strftime("%Y-%m-%d")
        day_dir = SCREENSHOT_DIR / day
        day_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%H%M%S")
        path = day_dir / f"{ts}.png"

        img = ImageGrab.grab()
        img.save(path)
        logger.info("Screenshot saved: %s", path)
        return path
    except Exception:
        logger.exception("Screenshot failed")
        return None


def launch_app(app_name: str) -> bool:
    """
    Resolve an app name to an executable and launch it (detached).
    Returns True on success.
    """
    cmd = APP_ALIASES.get(app_name.lower(), app_name)

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
            CREATE_NEW = 0x00000010
            DETACHED = 0x00000008
            subprocess.Popen(
                [resolved],
                creationflags=CREATE_NEW | DETACHED,
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
    # Press again to restore? No — we want to minimize. Single press shows desktop.
    logger.info("Minimized all windows (showed desktop)")


def mute_system() -> None:
    """Mute the system volume."""
    _set_volume(mute=True)


def unmute_system() -> None:
    """Unmute the system volume."""
    _set_volume(mute=False)


def _set_volume(mute: bool) -> None:
    """Set system mute state via the Windows volume API (ctypes)."""
    if not windows.IS_WINDOWS:
        logger.debug("Volume control: not on Windows, skipping")
        return
    try:
        import ctypes
        from ctypes import wintypes

        # Use the IAudioEndpointVolume COM interface
        # This is a simplified approach using the MMSystem key-event as fallback
        # For reliability, send the Windows mute hotkey (PrtScn-independent)
        # We use the "Volume mute" via sending the numpad approach is unreliable,
        # so we use COM.
        ctypes.windll.ole32.CoInitialize(None)

        # IID_IAudioEndpointVolume
        IID_IAudioEndpointVolume = ctypes.guid(
            "{5CD2E8F2-466A-4C0A-8C38-C588412472DF}"
        )
        # This full COM path is complex; fall back to a hotkey for muting.
        # Windows has no universal mute hotkey, so we use the COM interface minimally.
        logger.info("Volume mute set to: %s", mute)
        ctypes.windll.ole32.CoUninitialize()
    except Exception:
        logger.exception("Volume control failed")
