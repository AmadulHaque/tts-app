"""Kokoro Studio — simple, robust text-to-speech window.

Type or drop text, pick a voice, generate (with progress + cancel), listen,
then save. Model preloads at startup; failures are logged and retryable.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QThread, Qt, Signal, Slot
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from ..core import audio_processor
from ..core.tts_engine import TTSEngine
from ..models.dialogue import estimate_speech_time
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

    progress = Signal(int, int)      # (chunks done, chunks total)
    finished_audio = Signal(object)  # np.ndarray float32 @24k
    failed = Signal(str)

    def __init__(self, engine: TTSEngine, text: str, voice_id: str,
                 speed: float = 1.0, pitch: float = 0.0,
                 cancel_event: threading.Event | None = None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self._engine = engine
        self._text = text
        self._voice_id = voice_id
        self._speed = speed
        self._pitch = pitch
        self._cancel = cancel_event

    @Slot()
    def run(self) -> None:
        try:
            audio = self._engine.synthesize(
                self._text, self._voice_id, speed=self._speed,
                cancel_event=self._cancel,
                on_chunk=lambda i, n: self.progress.emit(i + 1, n))
            if self._cancel is not None and self._cancel.is_set():
                self.failed.emit("__cancelled__")
                return
            if self._pitch:
                audio = audio_processor.pitch_shift(audio, self._pitch)
            self.finished_audio.emit(audio_processor.peak_normalize(audio))
        except InterruptedError:
            self.failed.emit("__cancelled__")
        except Exception as e:  # noqa: BLE001
            log.exception("Synthesis failed")
            self.failed.emit(str(e))


class EngineLoader(QObject):
    """Background initializer: torch import + model weights."""

    ready = Signal(bool, str)   # (ok, message)

    def __init__(self, engine: TTSEngine, parent: QObject | None = None):
        super().__init__(parent)
        self._engine = engine

    @Slot()
    def run(self) -> None:
        try:
            self._engine.initialize()
            self.ready.emit(True, self._engine.device.upper())
        except Exception as e:  # noqa: BLE001
            log.exception("Engine init failed")
            self.ready.emit(False, str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        setup_logger("INFO")
        self._engine = TTSEngine()
        self._worker: SynthWorker | None = None
        self._thread: QThread | None = None
        self._loader_thread: QThread | None = None
        self._cancel_event: threading.Event | None = None
        self._pending_audio = None
        self._last_params: tuple[str, str, float, float] | None = None
        self._previewer = AudioPreviewer()
        self._settings = QSettings("KokoroStudio", "KokoroStudio")

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(760, 560)
        self.setAcceptDrops(True)

        central = QWidget()
        layout = QVBoxLayout(central)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "Paste your script here (or drop a .txt file), pick a voice, "
            "then click Generate Audio.")
        self.text_edit.textChanged.connect(self._update_stats)
        layout.addWidget(self.text_edit, 1)

        self.stats_label = QLabel("0 words · 0 chars · ~0:00")
        layout.addWidget(self.stats_label)

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

        gen_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.cancel_btn = QPushButton("✕ Cancel")
        self.cancel_btn.setVisible(False)
        gen_row.addWidget(self.progress, 1)
        gen_row.addWidget(self.cancel_btn)
        row_layout.addLayout(gen_row)

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

        self._status = QLabel("Loading speech model…")
        self.statusBar().addWidget(self._status, 1)
        self._gpu_label = QLabel("Engine: loading…")
        self.statusBar().addPermanentWidget(self._gpu_label)

        self.generate_btn.clicked.connect(self._on_generate)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.play_btn.clicked.connect(self._on_play)
        self.stop_btn.clicked.connect(self._previewer.stop)
        self.save_btn.clicked.connect(self._on_save)

        self._apply_qss("dark")
        self._start_engine_loader()

    # -- engine preload -------------------------------------------------------

    def _start_engine_loader(self) -> None:
        if self._loader_thread is not None:
            return
        loader = EngineLoader(self._engine)
        thread = QThread()
        self._loader_thread = thread
        self._loader = loader
        loader.moveToThread(thread)
        thread.started.connect(loader.run)
        loader.ready.connect(self._on_engine_ready)
        loader.ready.connect(thread.quit)
        loader.ready.connect(loader.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_loader_thread)
        thread.start()

    def _clear_loader_thread(self) -> None:
        self._loader_thread = None
        self._loader = None

    def _on_engine_ready(self, ok: bool, message: str) -> None:
        if ok:
            self._gpu_label.setText(f"Engine: {message}")
            self._status.setText("Ready — type text and generate.")
        else:
            self._gpu_label.setText("Engine: failed")
            self._status.setText(f"Model failed to load: {message}")

    # -- generation ---------------------------------------------------------

    def _on_generate(self) -> None:
        text = self.text_edit.toPlainText().strip()
        if not text:
            self._status.setText("Type some text first.")
            return
        if self._thread is not None:
            self._status.setText("Already generating — one moment.")
            return
        if not self._engine.ready:
            self._status.setText("Model still loading — try again in a moment.")
            return
        voice_id = self.voice_combo.currentData() or "af_heart"
        speed = float(self.speed_spin.value())
        pitch = float(self.pitch_spin.value())
        self._start_generation(text, voice_id, speed, pitch)

    def _start_generation(self, text: str, voice_id: str,
                          speed: float, pitch: float) -> None:
        self._last_params = (text, voice_id, speed, pitch)
        set_busy(self.generate_btn, "⏳ Generating")
        self._previewer.stop()
        self._pending_audio = None
        self.play_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self._cancel_event = threading.Event()
        self.cancel_btn.setVisible(True)
        self.progress.setRange(0, 0)   # indeterminate until chunk count known
        self.progress.setVisible(True)
        self._status.setText("Generating audio…")

        worker = SynthWorker(self._engine, text, voice_id, speed, pitch,
                             cancel_event=self._cancel_event)
        thread = QThread()
        self._worker, self._thread = worker, thread
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_chunk_progress)
        worker.finished_audio.connect(self._on_audio)
        worker.failed.connect(self._on_failed)
        for sig in (worker.finished_audio, worker.failed):
            sig.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_thread)
        thread.start()

    def _on_chunk_progress(self, done: int, total: int) -> None:
        if total > 1:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            self._status.setText(f"Generating — part {done}/{total}…")

    def _on_cancel(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
            self._status.setText("Cancelling…")

    def _on_audio(self, audio) -> None:
        clear_busy(self.generate_btn)
        self._generation_ui_reset()
        self._pending_audio = audio
        self.play_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        seconds = audio_processor.duration_seconds(audio)
        self._status.setText(f"Generated {seconds:.1f}s — playing. Click Save Audio to keep it.")
        self._previewer.play_array(audio)

    def _on_failed(self, error: str) -> None:
        clear_busy(self.generate_btn)
        self._generation_ui_reset()
        if error == "__cancelled__":
            self._status.setText("Cancelled.")
            return
        self._status.setText(f"Generation failed: {error}")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Generation failed")
        box.setText(error)
        retry = box.addButton("Retry", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is retry and self._last_params is not None:
            self._start_generation(*self._last_params)

    def _generation_ui_reset(self) -> None:
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)
        self._cancel_event = None

    def _on_play(self) -> None:
        if self._pending_audio is not None:
            self._previewer.play_array(self._pending_audio)

    def _on_save(self) -> None:
        if self._pending_audio is None:
            return
        last_dir = str(self._settings.value("last_save_dir", ""))
        out_dir = Path(last_dir) if last_dir else paths.resolve_output_dir("")
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
            log.exception("Save failed")
            QMessageBox.warning(self, "Save failed", str(e))
            self._status.setText("Save failed.")
            return
        self._settings.setValue("last_save_dir", str(target.parent))
        seconds = audio_processor.duration_seconds(self._pending_audio)
        self._status.setText(f"Saved {target.name}  ·  {seconds:.1f}s")

    # -- input helpers --------------------------------------------------------

    def _update_stats(self) -> None:
        text = self.text_edit.toPlainText()
        words = len([w for w in text.split() if w])
        seconds = estimate_speech_time(text, float(self.speed_spin.value()))
        m, s = divmod(int(seconds), 60)
        self.stats_label.setText(f"{words} words · {len(text)} chars · ~{m}:{s:02d}")

    def _suggest_name(self) -> str:
        words = [w for w in self.text_edit.toPlainText().split() if w][:4]
        stem = " ".join(words) if words else "speech"
        keep = "".join(c for c in stem if c.isalnum() or c in " _-").strip() or "speech"
        return f"{keep}.wav"

    # -- drag & drop ----------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime.hasUrls() and all(
                u.isLocalFile() and u.toLocalFile().lower().endswith(".txt")
                for u in mime.urls()):
            event.acceptProposedAction()
        elif mime.hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime.hasUrls():
            path = mime.urls()[0].toLocalFile()
            try:
                text = Path(path).read_text(encoding="utf-8-sig")
            except OSError as e:
                self._status.setText(f"Could not read {Path(path).name}: {e}")
                return
            self.text_edit.setPlainText(text)
            self._status.setText(f"Loaded {Path(path).name}")
        elif mime.hasText():
            self.text_edit.setPlainText(mime.text())
        event.acceptProposedAction()

    # -- lifecycle --------------------------------------------------------------

    def _clear_thread(self) -> None:
        self._worker = None
        self._thread = None

    def closeEvent(self, event) -> None:  # noqa: N802
        self._previewer.stop()
        if self._cancel_event is not None:
            self._cancel_event.set()
        if self._thread is not None:
            self._thread.quit()
            if not self._thread.wait(3000):
                _ORPHAN_THREADS.add(self._thread)
        self._thread = None
        self._worker = None
        if self._loader_thread is not None:
            self._loader_thread.quit()
            if not self._loader_thread.wait(5000):
                _ORPHAN_THREADS.add(self._loader_thread)
        self._loader_thread = None
        super().closeEvent(event)

    # -- appearance -----------------------------------------------------------

    def _apply_qss(self, kind: str) -> None:
        path = Path(__file__).parent / ".." / "assets" / "styles" / f"app_{kind}.qss"
        try:
            QApplication.instance().setStyleSheet(path.resolve().read_text(encoding="utf-8"))
        except OSError:
            pass
