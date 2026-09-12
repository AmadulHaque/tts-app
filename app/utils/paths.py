"""Filesystem paths for config, autosaves, recent files and output."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _data_dir() -> Path:
    """Per-user app-data directory (created lazily)."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "KokoroStudio"


def ensure_data_dir() -> Path:
    d = _data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return ensure_data_dir() / "config.json"


def favorites_path() -> Path:
    return ensure_data_dir() / "favorites.json"


def presets_path() -> Path:
    return ensure_data_dir() / "voice_presets.json"


def recent_path() -> Path:
    return ensure_data_dir() / "recent.json"


def autosave_dir() -> Path:
    d = ensure_data_dir() / "autosave"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_path() -> Path:
    return ensure_data_dir() / "kokoro-studio.log"


def default_output_dir() -> Path:
    return Path.home() / "KokoroStudio Output"


def resolve_output_dir(custom: str | None) -> Path:
    if custom:
        p = Path(os.path.expanduser(custom))
    else:
        p = default_output_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p


def format_ext(fmt: str) -> str:
    return {"WAV": "wav", "MP3": "mp3", "FLAC": "flac", "OGG": "ogg"}.get(fmt.upper(), "wav")
