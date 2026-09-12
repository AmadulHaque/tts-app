"""Audio post-processing: silence insertion, concatenation, normalization,
pitch shifting (via ffmpeg) and file export. Pure numpy/soundfile."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from ..utils.logger import get_logger

log = get_logger("audio_processor")

DEFAULT_SR = 24000


# ---------------------------------------------------------------------------
# Time-domain helpers
# ---------------------------------------------------------------------------

def silence(seconds: float, sr: int = DEFAULT_SR) -> np.ndarray:
    return np.zeros(int(round(seconds * sr)), dtype=np.float32)


def insert_silence(audio: np.ndarray, seconds: float, sr: int = DEFAULT_SR) -> np.ndarray:
    if seconds <= 0:
        return audio
    return np.concatenate([audio, silence(seconds, sr)]) if len(audio) else silence(seconds, sr)


def concatenate(audios: list[np.ndarray]) -> np.ndarray:
    return np.concatenate([a.astype(np.float32) for a in audios if len(a)])


def duration_seconds(audio: np.ndarray, sr: int = DEFAULT_SR) -> float:
    return len(audio) / float(sr)


# ---------------------------------------------------------------------------
# Dialogue assembly
# ---------------------------------------------------------------------------

def build_audio(
    line_audios: list[np.ndarray],
    speakers: list[str],
    pause_between_lines: float = 0.5,
    pause_between_speakers: float = 0.8,
    line_pause_overrides: list[float | None] | None = None,
    sr: int = DEFAULT_SR,
) -> tuple[np.ndarray, list[tuple[float, float]]]:
    """Concatenate per-line audios inserting pauses.

    Pause between two consecutive lines is ``pause_between_speakers`` when the
    speaker changes, else ``pause_between_lines`` — unless a per-line override
    is given (``line_pause_overrides[i]`` applied after line ``i``).

    Returns ``(audio, offsets)`` where ``offsets[i]`` = absolute
    ``(start_seconds, end_seconds)`` of the spoken part of line *i*.
    """
    if not line_audios:
        return np.zeros(0, dtype=np.float32), []
    if line_pause_overrides is None:
        line_pause_overrides = [None] * len(line_audios)

    pieces: list[np.ndarray] = [np.asarray(line_audios[0], dtype=np.float32)]
    offsets: list[tuple[float, float]] = []
    cursor = 0.0
    first_len = len(line_audios[0])
    offsets.append((cursor, cursor + first_len / sr))
    cursor += first_len / sr

    for i in range(1, len(line_audios)):
        pause = _pause_between(speakers[i - 1], speakers[i],
                               pause_between_lines, pause_between_speakers)
        override = line_pause_overrides[i - 1]
        if override is not None:
            pause = max(0.0, min(60.0, override))
        pause = max(0.0, pause)
        pieces.append(silence(pause, sr))
        cursor += pause

        seg = np.asarray(line_audios[i], dtype=np.float32)
        pieces.append(seg)
        offsets.append((cursor, cursor + len(seg) / sr))
        cursor += len(seg) / sr

    return concatenate(pieces), offsets


def _pause_between(prev_speaker: str, next_speaker: str,
                   same: float, different: float) -> float:
    return different if prev_speaker != next_speaker else same


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize(audio: np.ndarray, mode: str = "peak", *, sr: int = DEFAULT_SR,
              peak_target_db: float = -1.0, lufs_target: float = -16.0) -> np.ndarray:
    mode = (mode or "off").lower()
    if mode == "off":
        return audio
    if mode == "peak":
        return peak_normalize(audio, peak_target_db)
    if mode == "lufs":
        try:
            return lufs_normalize(audio, sr, lufs_target)
        except Exception as e:  # noqa: BLE001
            log.warning("LUFS normalization failed (%s); falling back to peak", e)
            return peak_normalize(audio, peak_target_db)
    return audio


def peak_normalize(audio: np.ndarray, target_db: float = -1.0) -> np.ndarray:
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak <= 1e-9:
        return audio
    target = 10 ** (target_db / 20.0)
    return np.clip(audio * (target / peak), -1.0, 1.0).astype(np.float32)


def lufs_normalize(audio: np.ndarray, sr: int, target_lufs: float = -16.0) -> np.ndarray:
    import pyloudnorm as pyln  # optional dependency

    meter = pyln.Meter(sr)
    loudness = meter.integrated_loudness(audio.astype(np.float32))
    if not np.isfinite(loudness) or loudness == 0:
        return audio.astype(np.float32)
    return pyln.normalize.loudness(audio.astype(np.float32), loudness, target_lufs)


# ---------------------------------------------------------------------------
# Pitch shifting via ffmpeg (Kokoro has no native pitch control)
# ---------------------------------------------------------------------------

def pitch_shift(audio: np.ndarray, semitones: float, sr: int = DEFAULT_SR,
                ffmpeg_bin: str | None = None) -> np.ndarray:
    """Pitch-shift *audio* by *semitones* (-2..+2), preserving duration.

    Uses ffmpeg: ``asetrate=sr*factor`` + ``aresample=sr`` + ``atempo=1/factor``.
    """
    if not semitones or not len(audio):
        return audio.astype(np.float32, copy=True)
    factor = 2.0 ** (float(semitones) / 12.0)
    if abs(factor - 1.0) < 1e-6:
        return audio.astype(np.float32, copy=True)

    binary = ffmpeg_bin or _find_ffmpeg()
    if not binary:
        log.warning("ffmpeg not found; pitch shift skipped")
        return audio.astype(np.float32, copy=True)

    data = audio.astype(np.float32)
    # Clip just inside [-1, 1] so we don't produce NaNs at the wav headroom.
    data = np.clip(data, -0.9999, 0.9999)

    with tempfile.TemporaryDirectory(prefix="kokoro_pitch_") as tmp:
        fin = Path(tmp) / "in.wav"
        fout = Path(tmp) / "out.wav"
        sf.write(fin, data, sr, subtype="PCM_32")
        atempo = 1.0 / factor
        expr = f"asetrate={sr}*{factor},aresample={sr},atempo={atempo}"
        cmd = [binary, "-y", "-v", "error", "-i", str(fin), "-af", expr, str(fout)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not fout.exists():
            log.warning("pitch shift failed: %s", proc.stderr.strip())
            return data
        out, _ = sf.read(fout, dtype="float32")
        # Trim to original duration in case atempo drifts sample count.
        n = min(len(data), len(out))
        return np.ascontiguousarray(out[:n], dtype=np.float32)


def _find_ffmpeg() -> str | None:
    path = shutil.which("ffmpeg")
    return path or os.environ.get("FFMPEG_BINARY")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export(audio: np.ndarray, path: str | Path, fmt: str = "WAV",
           sr: int = DEFAULT_SR, bitrate: int = 192) -> Path:
    """Write *audio* to *path*. WAV/FLAC/OGG via soundfile; MP3 via pydub."""
    fmt = (fmt or "WAV").lower()
    audio = np.clip(audio, -1.0, 1.0).astype(np.float32) if len(audio) else audio
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "mp3":
        _export_mp3(audio, target, sr, bitrate)
    else:
        sf_format = {"wav": "WAV", "flac": "FLAC", "ogg": "OGG"}.get(fmt, "WAV")
        subtype = "PCM_16"
        if fmt == "ogg":
            subtype = "VORBIS"
        sf.write(str(target), audio, sr, format=sf_format, subtype=subtype)
    return target


def _export_mp3(audio: np.ndarray, target: Path, sr: int, bitrate: int) -> None:
    try:
        from pydub import AudioSegment
    except ImportError as e:  # noqa: BLE001
        raise RuntimeError("pydub is required for MP3 export") from e
    pcm16 = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
    seg = AudioSegment(
        pcm16.tobytes(),
        frame_rate=sr,
        sample_width=2,
        channels=1,
    )
    seg.export(str(target), format="mp3", bitrate=f"{bitrate}k")
