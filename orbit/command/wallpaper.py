"""
Wallpaper manager.

Validates the file exists before setting, and logs the change.
"""

from __future__ import annotations

import logging
from pathlib import Path

from utils import windows

logger = logging.getLogger("orbit.command.wallpaper")


class WallpaperManager:
    """Sets the desktop wallpaper, validating the file first."""

    def set(self, path: str) -> bool:
        """
        Set the wallpaper to the given path.
        Returns True on success.
        """
        p = Path(path).expanduser()
        if not p.exists():
            logger.warning("Wallpaper file not found, skipping: %s", p)
            return False
        ok = windows.change_wallpaper(str(p))
        if ok:
            logger.info("Wallpaper set: %s", p)
        return ok
