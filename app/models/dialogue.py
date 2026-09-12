"""Data model for dialogue lines and speaker profiles."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict


# Rough average speaking rate for synthetic speech: words per second at speed=1.
_WORDS_PER_SECOND = 2.6


@dataclass
class DialogueLine:
    """A single spoken line in a conversation."""

    speaker: str
    text: str = ""
    pause_after: float = 0.0          # seconds, 0.0 => use global between-lines pause
    speed: float | None = None        # override speaker-level speed
    pitch: float | None = None        # override speaker-level pitch (semitones)


    @property
    def word_count(self) -> int:
        return len(_words(self.text))


    def estimated_duration(self, speed: float, pause_after: float | None = None) -> float:
        """Rough estimate in seconds: speaking time + trailing pause."""
        wps = _WORDS_PER_SECOND / max(speed, 0.1)
        speaking = max(0.5, self.word_count / wps)
        return speaking + (self.pause_after if pause_after is None else pause_after)


def _words(text: str) -> list[str]:
    return re.findall(r"\S+", text or "")


@dataclass
class SpeakerProfile:
    """Voice settings attached to a named speaker in a project."""

    name: str
    voice_id: str = "af_heart"
    speed: float = 1.0
    pitch: float = 0.0


    def to_dict(self) -> dict:
        return asdict(self)


    @classmethod
    def from_dict(cls, d: dict) -> "SpeakerProfile":
        return cls(name=d.get("name", ""), voice_id=d.get("voice_id", "af_heart"),
                   speed=float(d.get("speed", 1.0)), pitch=float(d.get("pitch", 0.0)))


def default_speakers() -> list[SpeakerProfile]:
    return [SpeakerProfile(name="Speaker A", voice_id="am_michael"),
            SpeakerProfile(name="Speaker B", voice_id="af_heart")]


# Convenience: text-words counter used by the editor for real-time stats.
def count_words(text: str) -> int:
    return len(_words(text))


def estimate_speech_time(text: str, speed: float = 1.0) -> float:
    """Speaking time only (no trailing pause)."""
    wps = _WORDS_PER_SECOND / max(speed, 0.1)
    return max(0.5, count_words(text) / wps)
