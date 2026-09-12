"""Preview audio playback helper.

Writes numpy audio to a temporary WAV and plays it with QMediaPlayer so the UI
never blocks. On platforms where QtMultimedia is unavailable it degrades to
playing via the platform tool (``afplay`` on macOS)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from ...core.audio_processor import DEFAULT_SR


class AudioPreviewer:
    def __init__(self):
        self._player = None
        self._audio_output = None
        self._temp_dir = tempfile.TemporaryDirectory(prefix="kokoro_preview_")
        self._current_path: Path | None = None
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PySide6.QtCore import QUrl
            self._QUrl = QUrl
            self._player = QMediaPlayer()
            self._audio_output = QAudioOutput()
            self._player.setAudioOutput(self._audio_output)
            self._audio_output.setVolume(1.0)
        except Exception:  # noqa: BLE001
            self._player = None

    def play_array(self, audio: np.ndarray, sr: int = DEFAULT_SR) -> bool:
        """Stop current playback and play *audio*. Returns False if no backend."""
        if len(audio) == 0 or not np.any(np.abs(audio) > 1e-6):
            return False
        path = Path(self._temp_dir.name) / "preview.wav"
        sf.write(str(path), np.clip(audio, -1.0, 1.0).astype(np.float32), sr)
        return self.play_file(path)

    def play_file(self, path: str | Path) -> bool:
        self.stop()
        if self._player is not None:
            self._player.setSource(self._QUrl.fromLocalFile(str(path)))
            self._player.play()
            return True
        # Fallback: platform player.
        if sys.platform == "darwin":
            subprocess.Popen(["afplay", str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        return False

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()

    def playing(self) -> bool:
        if self._player is not None:
            from PySide6.QtMultimedia import QMediaPlayer
            state = self._player.playbackState()
            return state == QMediaPlayer.PlaybackState.PlayingState
        return False
