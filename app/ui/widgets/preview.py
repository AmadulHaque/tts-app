"""Minimal audio playback: play numpy audio / files via QMediaPlayer, with an
``afplay`` fallback when QtMultimedia is unavailable."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from ...core.audio_processor import DEFAULT_SR


class AudioPreviewer:
    def __init__(self):
        self._temp_dir = tempfile.TemporaryDirectory(prefix="kokoro_preview_")
        self._current_path: Path | None = None
        self._proc: subprocess.Popen | None = None
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            self._QUrl = QUrl
            self._player = QMediaPlayer()
            self._audio_output = QAudioOutput()
            self._player.setAudioOutput(self._audio_output)
            self._audio_output.setVolume(1.0)
        except Exception:  # noqa: BLE001
            self._player = None

    def play_array(self, audio: np.ndarray, sr: int = DEFAULT_SR) -> bool:
        if len(audio) == 0:
            return False
        path = Path(self._temp_dir.name) / "preview.wav"
        sf.write(str(path), np.clip(audio, -1.0, 1.0).astype(np.float32), sr)
        return self.play_file(path)

    def play_file(self, path: str | Path) -> bool:
        self.stop()
        self._current_path = Path(path)
        if self._player is not None:
            self._player.setSource(self._QUrl.fromLocalFile(str(path)))
            self._player.play()
            return True
        if sys.platform == "darwin":
            self._proc = subprocess.Popen(["afplay", str(path)],
                                          stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL)
            return True
        return False

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()
        if self._proc is not None:
            self._proc.terminate()
            self._proc = None

    def playing(self) -> bool:
        if self._player is not None:
            from PySide6.QtMultimedia import QMediaPlayer
            return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        return self._proc is not None and self._proc.poll() is None
