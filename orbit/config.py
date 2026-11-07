"""
ORBIT Configuration Loader.

Loads ~/.orbit/config.yaml, falling back to the bundled default.
Exposes a typed Config class with a reload() method for live updates.
"""

from __future__ import annotations

import copy
import logging
import shutil
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("orbit.config")

CONFIG_DIR = Path.home() / ".orbit"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
DEFAULT_CONFIG_FILE = Path(__file__).parent / "config" / "default.yaml"


class ConfigError(Exception):
    """Raised when required configuration fields are missing or invalid."""
    pass


def _ensure_config_file() -> Path:
    """Ensure the config file exists; copy default if not."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        logger.info("No config found at %s — copying default", CONFIG_FILE)
        shutil.copy2(DEFAULT_CONFIG_FILE, CONFIG_FILE)
    return CONFIG_FILE


def _require(data: dict, *keys: str) -> Any:
    """Walk nested keys; raise ConfigError if any are missing."""
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise ConfigError(
                f"Missing required config field: {'.'.join(keys)}"
            )
        current = current[key]
    return current


class Config:
    """Typed configuration for all ORBIT subsystems."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw
        self._validate()
        self._parse()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def _validate(self) -> None:
        r = self._raw
        _require(r, "presence", "lock_timeout_sec")
        _require(r, "vision", "camera_index")
        _require(r, "phone", "websocket_port")
        _require(r, "security", "intruder_action")
        _require(r, "health", "daily_report_time")
        _require(r, "dashboard", "host")
        _require(r, "dashboard", "port")
        _require(r, "modes", "work")
        _require(r, "gestures")
        _require(r, "notifications")

    # ------------------------------------------------------------------
    # Parsing into typed attributes
    # ------------------------------------------------------------------
    def _parse(self) -> None:
        r = self._raw

        # presence
        self.presence_lock_timeout_sec: int = int(r["presence"]["lock_timeout_sec"])
        self.presence_keep_alive_interval_sec: int = int(r["presence"]["keep_alive_interval_sec"])
        self.presence_face_recognition_threshold: float = float(r["presence"]["face_recognition_threshold"])
        self.presence_ble_grace_period_sec: int = int(r["presence"]["ble_grace_period_sec"])

        # vision
        self.vision_frame_skip: int = int(r["vision"]["frame_skip"])
        self.vision_gesture_debounce_frames: int = int(r["vision"]["gesture_debounce_frames"])
        self.vision_emotion_stability_sec: float = float(r["vision"]["emotion_stability_sec"])
        self.vision_posture_alert_threshold_sec: float = float(r["vision"]["posture_alert_threshold_sec"])
        self.vision_multi_person_min_count: int = int(r["vision"]["multi_person_min_count"])
        self.vision_camera_index: int = int(r["vision"]["camera_index"])
        self.vision_background_interval_sec: float = float(r.get("vision", {}).get("background_interval_sec", 15.0))

        # phone
        self.phone_websocket_port: int = int(r["phone"]["websocket_port"])
        self.phone_ble_broadcast_interval_sec: int = int(r["phone"]["ble_broadcast_interval_sec"])
        self.phone_geo_fence_radius_m: int = int(r["phone"]["geo_fence_radius_m"])
        self.phone_geo_lock_delay_min: int = int(r["phone"]["geo_lock_delay_min"])
        self.phone_approval_timeout_sec: int = int(r["phone"]["approval_timeout_sec"])

        # security
        self.security_intruder_action: str = str(r["security"]["intruder_action"])
        self.security_record_on_intruder: bool = bool(r["security"]["record_on_intruder"])
        self.security_record_duration_sec: int = int(r["security"]["record_duration_sec"])
        self.security_snapshot_dir: Path = Path(r["security"]["snapshot_dir"]).expanduser()
        self.security_recording_dir: Path = Path(r["security"]["recording_dir"]).expanduser()
        self.security_webhook_url: str | None = r.get("security", {}).get("webhook_url", None)

        # health
        self.health_posture_alert_cooldown_min: int = int(r["health"]["posture_alert_cooldown_min"])
        self.health_screen_break_interval_min: int = int(r["health"]["screen_break_interval_min"])
        self.health_stress_threshold_min: int = int(r["health"]["stress_threshold_min"])
        self.health_ambient_light_threshold: int = int(r["health"]["ambient_light_threshold"])
        self.health_daily_report_time: str = str(r["health"]["daily_report_time"])

        # modes
        self.modes: dict[str, dict[str, Any]] = copy.deepcopy(r["modes"])

        # gestures
        self.gestures: dict[str, str] = dict(r["gestures"])

        # dashboard
        self.dashboard_host: str = str(r["dashboard"]["host"])
        self.dashboard_port: int = int(r["dashboard"]["port"])

        # notifications
        self.notifications: dict[str, bool] = {
            k: bool(v) for k, v in r["notifications"].items()
        }

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------
    def get_mode_config(self, mode: str) -> dict[str, Any]:
        if mode not in self.modes:
            raise ConfigError(f"Unknown mode: {mode}")
        return self.modes[mode]

    def get_notification_enabled(self, ntype: str) -> bool:
        return self.notifications.get(ntype, True)

    # ------------------------------------------------------------------
    # Reload
    # ------------------------------------------------------------------
    def reload(self) -> None:
        """Re-read the YAML file and re-parse in place."""
        raw = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
        if raw is None:
            raise ConfigError("Config file is empty")
        self._raw = raw
        self._validate()
        self._parse()
        logger.info("Configuration reloaded")

    @property
    def raw(self) -> dict[str, Any]:
        return copy.deepcopy(self._raw)


def load_config() -> Config:
    """Load (or create) the config file and return a Config instance."""
    path = _ensure_config_file()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raise ConfigError(f"Config file {path} is empty")
    return Config(raw)
