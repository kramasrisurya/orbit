"""
App manager.

Batch launch/close/minimize operations used by the ModeExecutor on
mode changes.
"""

from __future__ import annotations

import logging

try:
    from orbit.command import windows_api
except ImportError:
    from command import windows_api

logger = logging.getLogger("orbit.command.apps")


class AppManager:
    """Launches, closes, and minimizes groups of applications."""

    def launch(self, apps: list[str]) -> list[str]:
        """
        Launch all apps in the list (fire-and-forget).
        Returns the list of apps that launched successfully.
        """
        launched = []
        for app in apps:
            try:
                if windows_api.launch_app(app):
                    launched.append(app)
            except Exception:
                logger.exception("Failed to launch app: %s", app)
        if launched:
            logger.info("Launched apps: %s", launched)
        return launched

    def close(self, apps: list[str]) -> list[str]:
        """
        Kill all apps in the list.
        Returns the list of apps that were closed.
        """
        closed = []
        for app in apps:
            try:
                if windows_api.close_app(app):
                    closed.append(app)
            except Exception:
                logger.exception("Failed to close app: %s", app)
        if closed:
            logger.info("Closed apps: %s", closed)
        return closed

    def minimize_all_except(self, keep: list[str]) -> None:
        """
        Minimize everything except the listed apps.

        Implementation: show the desktop (Win+D), which minimizes all
        non-foreground windows. True per-app exclusion would require
        enumerating windows (win32gui); for a personal system, showing
        the desktop is a reasonable approximation. The `keep` list is
        logged for clarity.
        """
        if keep:
            logger.info("Minimizing all except: %s", keep)
        windows_api.minimize_all()
