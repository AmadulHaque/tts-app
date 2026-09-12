"""Project data model: dialogue + speakers + output settings, persisted as
JSON (``.kstudio``). Also produces the generation plan for workers and the
timing data for SRT export."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..models.dialogue import DialogueLine, SpeakerProfile, default_speakers, estimate_speech_time
from ..utils import import_export, paths

PROJECT_VERSION = 1

TIMED_LINE = tuple[float, float, str, str]  # start_s, end_s, speaker, text


@dataclass
class Project:
    title: str = "Untitled Project"
    lines: list[DialogueLine] = field(default_factory=list)
    speakers: list[SpeakerProfile] = field(default_factory=default_speakers)

    pause_between_lines: float = 0.5
    pause_between_speakers: float = 0.8
    speed: float = 1.0
    pitch: float = 0.0

    output_format: str = "WAV"
    sample_rate: int = 24000
    output_dir: str = ""
    normalize: str = "peak"
    peak_target_db: float = -1.0
    lufs_target: float = -16.0

    version: int = PROJECT_VERSION


    # -- accessors ---------------------------------------------------------

    def speaker(self, name: str) -> SpeakerProfile | None:
        for s in self.speakers:
            if s.name == name:
                return s
        return None


    def add_speaker_if_missing(self, name: str) -> SpeakerProfile:
        existing = self.speaker(name)
        if existing:
            return existing
        profile = SpeakerProfile(name=name)
        self.speakers.append(profile)
        return profile


    def line_profile(self, line: DialogueLine) -> tuple[SpeakerProfile, float, float]:
        """Resolve (speaker profile, effective speed, effective pitch)."""
        prof = self.add_speaker_if_missing(line.speaker)
        speed = line.speed if line.speed is not None else prof.speed
        pitch = line.pitch if line.pitch is not None else prof.pitch
        if self.pitch and pitch == 0 and not line.pitch:
            pitch = self.pitch
        return prof, speed, pitch


    # -- stats -------------------------------------------------------------

    @property
    def word_count(self) -> int:
        return sum(line.word_count for line in self.lines)


    def estimated_duration(self) -> float:
        total = 0.0
        for i, line in enumerate(self.lines):
            prof, speed, _pitch = self.line_profile(line)
            pause = self.pause_between_lines
            if i + 1 < len(self.lines):
                pause = self.pause_between_speakers if line.speaker != self.lines[i + 1].speaker \
                    else self.pause_between_lines
            pause = line.pause_after if line.pause_after else pause
            total += estimate_speech_time(line.text, speed) + pause
        return total


    # -- generation plan ---------------------------------------------------

    def render_plan(self) -> list[dict]:
        """Per-line (index, text, speaker, voice_id, speed, pitch)."""
        plan: list[dict] = []
        for line in self.lines:
            if not line.text.strip():
                continue
            prof, speed, pitch = self.line_profile(line)
            plan.append({
                "index": len(plan),
                "text": line.text,
                "speaker": line.speaker,
                "voice_id": prof.voice_id,
                "speed": speed,
                "pitch": pitch,
                "pause_after": line.pause_after if line.pause_after else None,
            })
        return plan


    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "title": self.title,
            "pause_between_lines": self.pause_between_lines,
            "pause_between_speakers": self.pause_between_speakers,
            "speed": self.speed,
            "pitch": self.pitch,
            "output_format": self.output_format,
            "sample_rate": self.sample_rate,
            "output_dir": self.output_dir,
            "normalize": self.normalize,
            "peak_target_db": self.peak_target_db,
            "lufs_target": self.lufs_target,
            "speakers": [s.to_dict() for s in self.speakers],
            "lines": [
                {"speaker": l.speaker, "text": l.text, "pause_after": l.pause_after,
                 "speed": l.speed, "pitch": l.pitch}
                for l in self.lines
            ],
        }


    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        p = cls()
        p.title = str(d.get("title", "Untitled Project"))
        p.pause_between_lines = float(d.get("pause_between_lines", 0.5))
        p.pause_between_speakers = float(d.get("pause_between_speakers", 0.8))
        p.speed = float(d.get("speed", 1.0))
        p.pitch = float(d.get("pitch", 0.0))
        p.output_format = str(d.get("output_format", "WAV"))
        p.sample_rate = int(d.get("sample_rate", 24000))
        p.output_dir = str(d.get("output_dir", ""))
        p.normalize = str(d.get("normalize", "peak"))
        p.peak_target_db = float(d.get("peak_target_db", -1.0))
        p.lufs_target = float(d.get("lufs_target", -16.0))
        p.speakers = [SpeakerProfile.from_dict(s) for s in d.get("speakers", [])] or default_speakers()
        p.lines = [
            DialogueLine(
                speaker=str(l.get("speaker", "Speaker A")),
                text=str(l.get("text", "")),
                pause_after=float(l.get("pause_after", 0.0) or 0.0),
                speed=_opt(l.get("speed")),
                pitch=_opt(l.get("pitch")),
            )
            for l in d.get("lines", [])
        ]
        return p


    def save(self, path: str | Path) -> Path:
        target = Path(path)
        if target.suffix.lower() != ".kstudio":
            target = target.with_suffix(".kstudio")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return target


    @classmethod
    def load(cls, path: str | Path) -> "Project":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)


    # -- exports -----------------------------------------------------------

    def export_srt(self, timed_lines: list[TIMED_LINE], path: str | Path) -> Path:
        content = import_export.export_srt(timed_lines)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target


    def default_output_path(self, ext: str | None = None) -> Path:
        out_dir = paths.resolve_output_dir(self.output_dir)
        ext = ext or paths.format_ext(self.output_format)
        sanitized = "".join(c for c in self.title if c.isalnum() or c in " _-").strip() or "output"
        return out_dir / f"{sanitized}.{ext}"


def _opt(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
