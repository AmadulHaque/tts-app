"""Application settings: a typed dataclass persisted as JSON in the user's
app-data directory."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, fields

from ..utils import paths


@dataclass
class Settings:
    # Default voices for new projects' Speaker A and Speaker B.
    default_voice_a: str = "am_michael"
    default_voice_b: str = "af_heart"
    default_speed_a: float = 1.0
    default_speed_b: float = 1.0

    # Global audio timing.
    pause_between_lines: float = 0.5    # same speaker consecutive
    pause_between_speakers: float = 0.8 # speaker changes
    speed: float = 1.0

    # Output.
    output_dir: str = ""                # "" => default (~/KokoroStudio Output)
    output_format: str = "WAV"          # WAV | MP3 | FLAC | OGG
    sample_rate: int = 24000

    # Normalization: "off" | "peak" | "lufs".
    normalize: str = "peak"
    peak_target_db: float = -1.0
    lufs_target: float = -16.0

    # Model / device.
    model_repo_id: str = "hexgrad/Kokoro-82M"
    device: str = "auto"                # auto | cpu | mps

    # Appearance.
    theme: str = "dark"                 # light | dark | system

    # Logging.
    log_level: str = "INFO"


    def to_dict(self) -> dict:
        return asdict(self)


    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        known = {f.name: f for f in fields(cls)}
        kwargs: dict = {}
        for k, v in (d or {}).items():
            if k not in known:
                continue
            field_type = known[k].type
            vv = _coerce(v, field_type)
            if vv is not None:
                kwargs[k] = vv
        return cls(**kwargs)


    def load(self) -> "Settings":
        return load_settings()


    def save(self) -> None:
        save_settings(self)


def _coerce(value, type_name: str):
    """Best-effort coercion for JSON-loaded settings."""
    if value is None:
        return None
    if type_name == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if type_name == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if type_name == "str":
        return str(value)
    return value


def load_settings() -> Settings:
    p = paths.config_path()
    if not p.exists():
        return Settings()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return Settings.from_dict(raw)
    except (json.JSONDecodeError, OSError):
        return Settings()


def save_settings(settings: Settings) -> None:
    p = paths.config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")


# --- Favorites + presets (small JSON stores) ---

def load_json_store(filename: str, default) -> list | dict:
    p = paths.ensure_data_dir() / filename
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def save_json_store(filename: str, data) -> None:
    p = paths.ensure_data_dir() / filename
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_favorites() -> list[str]:
    return [str(v) for v in load_json_store("favorites.json", [])]


def save_favorites(voice_ids: list[str]) -> None:
    save_json_store("favorites.json", list(voice_ids))


def load_recent_files() -> list[str]:
    return [str(v) for v in load_json_store("recent.json", [])]


def add_recent_file(path: str, max_entries: int = 10) -> None:
    recent = load_recent_files()
    if path in recent:
        recent.remove(path)
    recent.insert(0, path)
    save_json_store("recent.json", recent[:max_entries])


def load_voice_presets() -> dict:
    return dict(load_json_store("voice_presets.json", {}))


def save_voice_presets(presets: dict) -> None:
    save_json_store("voice_presets.json", presets)
