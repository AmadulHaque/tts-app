"""Kokoro Studio — simple text-to-speech window.

Type text, pick a voice, hit Generate & Save. Nothing else.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from ..core import audio_processor
from ..core.tts_engine import TTSEngine
from ..models.voice import VOICE_CATALOG
from ..utils import paths
from ..utils.logger import get_logger, setup_logger
from .widgets.busy import clear_busy, set_busy
from .widgets.preview import AudioPreviewer

log = get_logger("main_window")

# Threads that outlive their window: keep a reference so a running QThread is
# never GC'd (that is a hard abort).
_ORPHAN_THREADS: set = set()


class SynthWorker(QObject):
    """Synthesize text on a background thread; emits numpy audio."""

    finished_audio = Signal(object)   # np.ndarray float32 @24k
    failed = Signal(str)

    def __init__(self, engine: TTSEngine, text: str, voice_id: str,
                 speed: float = 1.0, pitch: float = 0.0,
                 parent: QObject | None = None):
        super().__init__(parent)
        self._engine = engine
        self._text = text
        self._voice_id = voice_id
        self._speed = speed
        self._pitch = pitch

    @Slot()
    def run(self) -> None:
        try:
            audio = self._engine.synthesize(self._text, self._voice_id,
                                            speed=self._speed)
            if self._pitch:
                audio = audio_processor.pitch_shift(audio, self._pitch)
            self.finished_audio.emit(audio_processor.peak_normalize(audio))
        except Exception as e:  # noqa: BLE001
            log.exception("Synthesis failed")
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        setup_logger("INFO")
        self._engine = TTSEngine()
        self._worker: SynthWorker | None = None
        self._thread: QThread | None = None
        self._pending_audio = None
        self._previewer = AudioPreviewer()

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(720, 520)

        central = QWidget()
        layout = QVBoxLayout(central)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "Paste your script here, pick a voice, then click Generate & Save Audio.")
        layout.addWidget(self.text_edit, 1)

        row = QWidget()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Voice:"))
        self.voice_combo = QComboBox()
        for vid in sorted(VOICE_CATALOG):
            info = VOICE_CATALOG[vid]
            self.voice_combo.addItem(f"{info.name} ({vid}) · {info.accent}", vid)
        controls.addWidget(self.voice_combo, 2)

        controls.addWidget(QLabel("Speed:"))
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.5, 1.5)
        self.speed_spin.setSingleStep(0.05)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setValue(1.0)
        self.speed_spin.setFixedWidth(70)
        self.speed_spin.setToolTip("Speaking rate (0.5 – 1.5×)")
        controls.addWidget(self.speed_spin)

        controls.addWidget(QLabel("Pitch:"))
        self.pitch_spin = QDoubleSpinBox()
        self.pitch_spin.setRange(-2.0, 2.0)
        self.pitch_spin.setSingleStep(0.1)
        self.pitch_spin.setDecimals(1)
        self.pitch_spin.setValue(0.0)
        self.pitch_spin.setSuffix(" st")
        self.pitch_spin.setFixedWidth(70)
        self.pitch_spin.setToolTip("Pitch shift in semitones (-2 – +2, needs ffmpeg)")
        controls.addWidget(self.pitch_spin)

        controls.addStretch(1)
        row_layout.addLayout(controls)

        self.generate_btn = QPushButton("🔊 Generate Audio")
        self.generate_btn.setObjectName("primaryButton")
        self.generate_btn.setMinimumHeight(40)
        row_layout.addWidget(self.generate_btn)

        play_row = QHBoxLayout()
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.setEnabled(False)
        self.play_btn.setToolTip("Replay the generated audio")
        self.stop_btn = QPushButton("⏹ Stop")
        self.stop_btn.setEnabled(False)
        self.save_btn = QPushButton("💾 Save Audio")
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.setEnabled(False)
        self.save_btn.setMinimumHeight(34)
        play_row.addWidget(self.play_btn)
        play_row.addWidget(self.stop_btn)
        play_row.addStretch(1)
        play_row.addWidget(self.save_btn)
        row_layout.addLayout(play_row)

        layout.addWidget(row)
        self.setCentralWidget(central)

        self._status = QLabel("Ready")
        self.statusBar().addWidget(self._status, 1)

        self.generate_btn.clicked.connect(self._on_generate)
        self.play_btn.clicked.connect(self._on_play)
        self.stop_btn.clicked.connect(self._previewer.stop)
        self.save_btn.clicked.connect(self._on_save)

        self._apply_qss("dark")

    # -- generation ---------------------------------------------------------

    def _on_generate(self) -> None:
        text = self.text_edit.toPlainText().strip()
        if not text:
            self._status.setText("Type some text first.")
            return
        if self._thread is not None:
            self._status.setText("Already generating — one moment.")
            return

        voice_id = self.voice_combo.currentData() or "af_heart"
        speed = float(self.speed_spin.value())
        pitch = float(self.pitch_spin.value())
        set_busy(self.generate_btn, "⏳ Generating")
        self._previewer.stop()
        self._pending_audio = None
        self.play_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self._status.setText("Generating audio (first run loads the model)…")

        worker = SynthWorker(self._engine, text, voice_id, speed, pitch)
        thread = QThread()
        self._worker, self._thread = worker, thread
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished_audio.connect(self._on_audio)
        worker.failed.connect(self._on_failed)
        for sig in (worker.finished_audio, worker.failed):
            sig.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_thread)
        thread.start()

    def _on_audio(self, audio) -> None:
        clear_busy(self.generate_btn)
        self._pending_audio = audio
        self.play_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        seconds = audio_processor.duration_seconds(audio)
        self._status.setText(f"Generated {seconds:.1f}s — playing. Click Save Audio to keep it.")
        self._previewer.play_array(audio)

    def _on_play(self) -> None:
        if self._pending_audio is not None:
            self._previewer.play_array(self._pending_audio)

    def _on_save(self) -> None:
        if self._pending_audio is None:
            return
        out_dir = paths.resolve_output_dir("")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save audio", str(out_dir / self._suggest_name()),
            "WAV (*.wav);;MP3 (*.mp3);;FLAC (*.flac);;OGG (*.ogg)")
        if not path:
            self._status.setText("Save cancelled — audio still available.")
            return
        fmt = Path(path).suffix.lstrip(".").upper() or "WAV"
        try:
            target = audio_processor.export(self._pending_audio, path, fmt)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Save failed", str(e))
            self._status.setText("Save failed.")
            return
        seconds = audio_processor.duration_seconds(self._pending_audio)
        self._status.setText(f"Saved {target.name}  ·  {seconds:.1f}s")

    def _on_failed(self, error: str) -> None:
        clear_busy(self.generate_btn)
        self._status.setText(f"Generation failed: {error}")
        QMessageBox.warning(self, "Generation failed", error)

    def _suggest_name(self) -> str:
        words = [w for w in self.text_edit.toPlainText().split() if w][:4]
        stem = " ".join(words) if words else "speech"
        keep = "".join(c for c in stem if c.isalnum() or c in " _-").strip() or "speech"
        return f"{keep}.wav"

    def _clear_thread(self) -> None:
        self._worker = None
        self._thread = None

    def closeEvent(self, event) -> None:  # noqa: N802
        self._previewer.stop()
        if self._thread is not None:
            self._thread.quit()
            if not self._thread.wait(3000):
                _ORPHAN_THREADS.add(self._thread)
        self._thread = None
        self._worker = None
        super().closeEvent(event)

    # -- appearance -----------------------------------------------------------

    def _apply_qss(self, kind: str) -> None:
        path = Path(__file__).parent / ".." / "assets" / "styles" / f"app_{kind}.qss"
        try:
            QApplication.instance().setStyleSheet(path.resolve().read_text(encoding="utf-8"))
        except OSError:
            pass
