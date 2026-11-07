"""
Mode executor.

Given a mode name, applies the configured environment changes:
  - Wallpaper
  - Launch the mode's apps
  - Adjust notification level (mute / critical-only / normal)
  - Minimize other apps

Called by ModeManager.switch_mode() after a valid transition.
"""

from __future__ import annotations

import asyncio
import logging
import sys

try:
    from orbit.command.apps import AppManager
    from orbit.command.wallpaper import WallpaperManager
    from orbit.command import windows_api
except ImportError:
    from command.apps import AppManager
    from command.wallpaper import WallpaperManager
    from command import windows_api

logger = logging.getLogger("orbit.productivity.mode_executor")


AUMS_URL = (
    "https://aumsam.amrita.edu/cas/login?service=https%3A%2F%2Faumsam.amrita.edu"
    "%2Faums%2FJsp%2FAttendance%2FAttendanceReportStudent.jsp%3Faction%3DUMS-ATD"
    "_INIT_ATDREPORTSTUD_SCREEN%26isMenu%3Dtrue%26pagePostSerialID%3D1"
)


class ModeExecutor:
    """
    Executes the side-effects of a mode change.
    """

    def __init__(self, config) -> None:
        self._config = config
        self._apps = AppManager()
        self._wallpaper = WallpaperManager()

    def execute(self, mode: str) -> None:
        """Apply all environment changes for the given mode."""
        try:
            mcfg = self._config.get_mode_config(mode)
        except Exception:
            logger.warning("No config for mode: %s", mode)
            return

        logger.info("Executing mode: %s", mode)

        # 1. Wallpaper
        wallpaper = mcfg.get("wallpaper")
        if wallpaper:
            try:
                self._wallpaper.set(wallpaper)
            except Exception:
                logger.exception("Failed to set wallpaper for mode %s", mode)

        # 2. Launch apps (student modes use specialized dedicated execution below)
        if mode not in ("entertainment", "study", "coding", "exam"):
            apps = mcfg.get("apps_to_open", [])
            if apps:
                try:
                    self._apps.launch(apps)
                except Exception:
                    logger.exception("Failed to launch apps for mode %s", mode)

        # 3. Notification level & Volume adjustment
        notif = mcfg.get("notifications", "normal")
        vol_scalar = mcfg.get("volume")

        # Specific student modes behavior
        if mode == "entertainment":
            self._execute_entertainment()
        elif mode == "study":
            self._execute_study()
        elif mode == "coding":
            self._execute_coding()
        elif mode == "exam":
            self._execute_exam()
        else:
            if notif == "muted":
                windows_api.mute_system()
            elif notif == "critical_only":
                windows_api.mute_system()
            else:
                windows_api.unmute_system()

            if vol_scalar is not None:
                self._set_volume(float(vol_scalar), mute=(vol_scalar == 0.0))

        # 4. Minimize other apps if explicitly configured
        if mcfg.get("minimize_others", False):
            try:
                self._apps.minimize_all_except(mcfg.get("apps_to_open", []))
            except Exception:
                logger.exception("Failed to minimize apps for mode %s", mode)

        logger.info("Mode %s executed", mode)

    def _set_volume(self, scalar: float, mute: bool = False) -> None:
        """Set Windows master volume level and mute state via pycaw."""
        try:
            from pycaw.pycaw import AudioUtilities
            speakers = AudioUtilities.GetSpeakers()
            if speakers and hasattr(speakers, "EndpointVolume"):
                ep = speakers.EndpointVolume
                ep.SetMute(1 if mute else 0, None)
                if not mute:
                    ep.SetMasterVolumeLevelScalar(max(0.0, min(1.0, scalar)), None)
                logger.info("Master volume set: scalar=%.2f, mute=%s", scalar, mute)
        except Exception as e:
            logger.warning("Could not set master volume via pycaw: %s", e)

    def _open_url_or_browser(self, url: str, prefer_brave: bool = False) -> None:
        """Open a URL, preferring Brave Browser if requested and installed, and bringing it to foreground."""
        import subprocess
        import webbrowser
        from pathlib import Path
        import time
        import ctypes

        opened_brave = False
        if prefer_brave:
            brave_candidates = [
                Path(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"),
                Path(r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe"),
            ]
            for candidate in brave_candidates:
                if candidate.exists():
                    try:
                        subprocess.Popen([str(candidate), url])
                        logger.info("Opened %s in Brave Browser", url)
                        opened_brave = True
                        break
                    except Exception as e:
                        logger.warning("Failed to open Brave via Popen: %s", e)

        if not opened_brave:
            if sys.platform == "win32":
                try:
                    res = ctypes.windll.shell32.ShellExecuteW(None, "open", url, None, None, 1)
                    if res > 32:
                        logger.info("Opened %s via Windows ShellExecuteW", url)
                        opened_brave = True
                except Exception:
                    pass
            if not opened_brave:
                try:
                    webbrowser.open(url)
                    logger.info("Opened %s in default browser", url)
                except Exception as e:
                    logger.error("Failed to open URL %s: %s", url, e)

        # Force foreground activation on Windows
        if sys.platform == "win32":
            time.sleep(0.35)
            try:
                user32 = ctypes.windll.user32
                hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
                if hdesk:
                    user32.SetThreadDesktop(hdesk)

                WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                def _focus_cb(hwnd, _):
                    if user32.IsWindowVisible(hwnd):
                        length = user32.GetWindowTextLengthW(hwnd)
                        if length > 0:
                            buff = ctypes.create_unicode_buffer(length + 1)
                            user32.GetWindowTextW(hwnd, buff, length + 1)
                            t = buff.value.lower()
                            if any(k in t for k in ("brave", "youtube", "amrita")):
                                if user32.IsIconic(hwnd):
                                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                                user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE (keep full screen)
                                user32.SetForegroundWindow(hwnd)
                                user32.SwitchToThisWindow(hwnd, True)
                                return False
                    return True

                user32.EnumWindows(WNDENUMPROC(_focus_cb), 0)
            except Exception as e:
                logger.warning("Failed to bring window to foreground: %s", e)

    def _execute_entertainment(self) -> None:
        """Entertainment: Open Brave to YouTube and set Full Volume (100%)."""
        windows_api.unmute_system()
        self._set_volume(1.0, mute=False)
        self._open_url_or_browser("https://www.youtube.com", prefer_brave=True)

    def _execute_study(self) -> None:
        """Study Mode: Open Amrita AUMS portal and MUTE laptop audio."""
        windows_api.mute_system()
        self._set_volume(0.0, mute=True)
        self._open_url_or_browser(AUMS_URL, prefer_brave=True)

    def _execute_coding(self) -> None:
        """Coding Mode: Set ambient volume to 25% and launch VS Code."""
        windows_api.unmute_system()
        self._set_volume(0.25, mute=False)
        import subprocess
        try:
            subprocess.Popen(["code", "."], shell=True)
        except Exception:
            pass

    def _execute_exam(self) -> None:
        """Exam Mode: Lockdown sound (0% MUTE) and launch AUMS."""
        windows_api.mute_system()
        self._set_volume(0.0, mute=True)
        self._open_url_or_browser(AUMS_URL, prefer_brave=True)
