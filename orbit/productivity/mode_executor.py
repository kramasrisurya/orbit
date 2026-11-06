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

from command.apps import AppManager
from command.wallpaper import WallpaperManager
from command import windows_api

logger = logging.getLogger("orbit.productivity.mode_executor")


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

        # 2. Launch apps
        apps = mcfg.get("apps_to_open", [])
        if apps:
            try:
                self._apps.launch(apps)
            except Exception:
                logger.exception("Failed to launch apps for mode %s", mode)

        # 3. Notification level
        notif = mcfg.get("notifications", "normal")
        if notif == "muted":
            windows_api.mute_system()
        elif notif == "critical_only":
            # Mute non-critical; for simplicity, mute system audio
            windows_api.mute_system()
        # "normal" → ensure unmuted
        else:
            windows_api.unmute_system()

        # 4. Minimize other apps (clean workspace)
        try:
            self._apps.minimize_all_except(mcfg.get("apps_to_open", []))
        except Exception:
            logger.exception("Failed to minimize apps for mode %s", mode)

        logger.info("Mode %s executed", mode)
