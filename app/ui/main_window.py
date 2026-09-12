"""Main window: tab shell, menus, engine lifecycle, generation orchestration."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QAction, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QMainWindow, QMenu, QMessageBox,
    QTabWidget,
)

from .. import APP_NAME, __version__
from ..core.batch_runner import EngineLoader, GenerationWorker, PreviewRunner, run_worker_thread
from ..core.project import Project
from ..core.tts_engine import TTSEngine
from ..models.dialogue import SpeakerProfile
from ..models.voice import VOICE_CATALOG
from ..utils import paths  # noqa: F401
from ..utils.config import Settings, add_recent_file, load_recent_files, load_settings
from ..utils.logger import get_logger, setup_logger
from .about_tab import AboutTab
from .batch_generator import BatchGeneratorTab
from .dialogue_editor import DialogueEditorTab
from .settings_tab import SettingsTab
from .voice_library import VoiceLibraryTab
from .widgets.preview import AudioPreviewer

log = get_logger("main_window")

PREVIEW_TEXT = "Hi there! This is a quick preview of my voice."

# Threads that outlive their window (close during a blocking run): kept here so
# the wrapper is never GC'd while running; each thread's finished handler
# discards it. Destroying a running QThread is SIGABRT.
_ORPHAN_THREADS: set = set()


def _shutdown_thread(thread, timeout_ms: int) -> None:
    """Ask *thread* to quit and wait. Stash survivors in _ORPHAN_THREADS."""
    if thread is None:
        return
    thread.quit()
    try:
        done = thread.wait(timeout_ms)
    except RuntimeError:
        return  # already deleted
    try:
        alive = thread.isRunning()
    except RuntimeError:
        return
    if not done and alive:
        _ORPHAN_THREADS.add(thread)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self._settings = settings or load_settings()
        setup_logger(self._settings.log_level)
        self.current_project = self._default_project()
        self._current_file: str | None = None
        self._gen_worker: GenerationWorker | None = None
        self._gen_thread: QThread | None = None
        self._engine_thread: QThread | None = None
        self._engine_loader = None  # EngineLoader; held: dead receivers silently disconnect
        self._preview_workers: set = set()
        self._preview_threads: set[QThread] = set()
        self._previewer = AudioPreviewer()

        # Engine (lazy: loads in a background thread at startup)
        self._engine = TTSEngine(model_repo_id=self._settings.model_repo_id,
                                 device=self._settings.device)

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1280, 820)

        self._build_tabs()
        self._build_menus()
        self._build_statusbar()
        self._wire_signals()
        self._apply_theme(self._settings.theme)
        self._show_status(f"Ready — engine loading…")

        self._init_engine_thread()

    # ------------------------------------------------------------------ setup

    def _default_project(self) -> Project:
        s = self._settings
        p = Project(title="Untitled Project")
        p.speakers = [
            SpeakerProfile("Speaker A", s.default_voice_a, s.default_speed_a),
            SpeakerProfile("Speaker B", s.default_voice_b, s.default_speed_b),
        ]
        p.pause_between_lines = s.pause_between_lines
        p.pause_between_speakers = s.pause_between_speakers
        p.output_format = s.output_format
        p.sample_rate = s.sample_rate
        p.normalize = s.normalize
        p.peak_target_db = s.peak_target_db
        p.lufs_target = s.lufs_target
        p.output_dir = s.output_dir
        return p

    def _build_tabs(self) -> None:
        from ..core.batch_runner import BatchRunner
        self._batch_runner = BatchRunner(self._engine)

        self.tabs = QTabWidget()
        self.editor = DialogueEditorTab()
        self.library = VoiceLibraryTab()
        self.batch_tab = BatchGeneratorTab(self._batch_runner)
        self.settings_tab = SettingsTab(self._settings)
        self.about = AboutTab()

        self.tabs.addTab(self.editor, "📝 Dialogue Editor")
        self.tabs.addTab(self.library, "🎙️ Voice Library")
        self.tabs.addTab(self.batch_tab, "📦 Batch Generator")
        self.tabs.addTab(self.settings_tab, "⚙️ Settings")
        self.tabs.addTab(self.about, "ℹ️ About")
        self.setCentralWidget(self.tabs)

    # ------------------------------------------------------------------ menus

    def _build_menus(self) -> None:
        mb = self.menuBar()

        file_menu = mb.addMenu("&File")
        self.act_new = self._action("&New Project", "Ctrl+N", self.new_project, file_menu)
        self.act_open = self._action("&Open…", "Ctrl+O", self.open_project, file_menu)
        self.act_save = self._action("&Save", "Ctrl+S", self.save_project, file_menu)
        self.act_save_as = self._action("Save &As…", "Ctrl+Shift+S", self.save_project_as, file_menu)
        self.recent_menu = QMenu("Recent Files", self)
        file_menu.addMenu(self.recent_menu)
        file_menu.addSeparator()
        self._action("E&xit", "Ctrl+Q", self.close, file_menu)

        edit_menu = mb.addMenu("&Edit")
        self._action("Undo", "Ctrl+Z", self.editor.undo, edit_menu)
        self._action("Redo", "Ctrl+Shift+Z", self.editor.redo, edit_menu)
        edit_menu.addSeparator()
        self._action("Add Line", "Ctrl+Enter", self.editor.add_line, edit_menu)
        self._action("Duplicate Line", None, self.editor.duplicate_selected, edit_menu)
        self._action("Delete Line", None, self.editor.delete_selected, edit_menu)
        edit_menu.addSeparator()
        self._action("Import Dialogue…", None, self.editor.import_dialog, edit_menu)
        self._action("Export Dialogue…", None, self.editor.export_dialog, edit_menu)

        voices_menu = mb.addMenu("&Voices")
        self._action("Show Voice Library", "Ctrl+L", lambda: self.tabs.setCurrentWidget(self.library), voices_menu)
        self._action("Set Speaker A voice…", None, lambda: self._pick_speaker_voice("A"), voices_menu)
        self._action("Set Speaker B voice…", None, lambda: self._pick_speaker_voice("B"), voices_menu)
        voices_menu.addSeparator()
        self.rebuild_voices_action = self._action("Rebuild Default Voices", "Ctrl+R", self._rebuild_default_voices, voices_menu)

        batch_menu = mb.addMenu("&Batch")
        self._action("Open Batch Mode", "Ctrl+B", lambda: self.tabs.setCurrentWidget(self.batch_tab), batch_menu)
        self._action("Generate All", "Ctrl+G", self.batch_tab.gen_all_btn.click,
                     batch_menu)

        help_menu = mb.addMenu("&Help")
        self._action("Keyboard Shortcuts…", None, self._show_shortcuts, help_menu)
        self._action(f"About {APP_NAME}…", None, lambda: self.tabs.setCurrentWidget(self.about), help_menu)

        self.rebuild_recent_menu()

    def _action(self, text: str, shortcut: str | None, slot, menu: QMenu) -> QAction:
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    # ------------------------------------------------------------- status bar

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self._sb_msg = QLabel("Ready")
        self._sb_len = QLabel("Audio length: 00:00")
        self._sb_gpu = QLabel("GPU: —")
        sb.addWidget(self._sb_msg, 1)
        sb.addPermanentWidget(self._sb_len)
        sb.addPermanentWidget(self._sb_gpu)

    def _show_status(self, message: str, timeout: int = 0) -> None:
        self._sb_msg.setText(message)
        if timeout:
            self.statusBar().showMessage("", timeout)

    def _set_audio_length(self, seconds: float) -> None:
        m, s = divmod(int(seconds), 60)
        self._sb_len.setText(f"Audio length: {m}:{s:02d}")

    # ----------------------------------------------------------------- signals

    def _wire_signals(self) -> None:
        e = self.editor
        e.generate_requested.connect(self._on_generate)
        e.cancel_requested.connect(self._cancel_generation)
        e.save_requested.connect(self.save_project)
        e.preview_line.connect(self._preview_line)
        e.status_message.connect(self._show_status)
        e.preview_sample.connect(self._preview_sample)
        e.project_modified.connect(lambda: self._sb_msg.setText("Project modified"))

        self.library.preview_requested.connect(self._preview_voice)
        self.library.set_default_requested.connect(self._on_set_default_voice)
        self.library.status_message.connect(self._show_status)
        self.batch_tab.status_message.connect(self._show_status)
        self.settings_tab.settings_saved.connect(self._on_settings_saved)
        self.settings_tab.theme_changed.connect(self._apply_theme)
        self.settings_tab.status_message.connect(self._show_status)

    # ------------------------------------------------------------- engine init

    def _init_engine_thread(self) -> None:
        # The thread must be held on self: a collected-while-running QThread
        # is a hard abort (SIGABRT in QThread::~QThread). Locals die with this
        # frame, so never store the loader thread in a local.
        if self._engine_thread is not None:
            return
        loader = EngineLoader(self._engine)
        thread = QThread()
        self._engine_thread = thread
        self._engine_loader = loader
        loader.moveToThread(thread)
        thread.started.connect(loader.run)
        loader.ready.connect(self._on_engine_ready)
        loader.ready.connect(thread.quit)
        loader.ready.connect(loader.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_engine_thread)
        thread.finished.connect(lambda t=thread: _ORPHAN_THREADS.discard(t))
        thread.start()

    def _clear_engine_thread(self) -> None:
        self._engine_thread = None
        self._engine_loader = None

    def _on_engine_ready(self, ok: bool, message: str) -> None:
        if ok:
            self._sb_gpu.setText(f"GPU: {message}")
            self._show_status(f"Ready — engine running on {message}")
        else:
            self._sb_gpu.setText("GPU: —")
            self._show_status(f"Engine failed to start: {message}")

    def _maybe_offer_recovery(self) -> None:
        """Offer to restore the newest autosave (crash recovery, spec F5)."""
        try:
            autosaves = sorted(paths.autosave_dir().glob("*.autosave.kstudio"),
                               key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return
        if not autosaves:
            return
        newest = autosaves[0]
        ret = QMessageBox.question(
            self, "Recover autosave?",
            f"Found an autosave from a previous session:\n{newest.name}\n\nRestore it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ret == QMessageBox.StandardButton.Yes:
            self._load_project(str(newest))

    # -------------------------------------------------------------- generation

    def _on_generate(self, project: Project) -> None:
        if not self._engine.ready:
            self._show_status("Kokoro is still loading — wait a moment then try again.")
            self.editor.generation_finished()
            return
        out = project.default_output_path()
        srt = out.with_suffix(".srt")
        worker = GenerationWorker(project, self._engine, str(out), srt_path=str(srt))
        thread = run_worker_thread(worker)
        self._gen_worker, self._gen_thread = worker, thread

        worker.progress.connect(self.editor.set_generation_progress)
        worker.line_done.connect(self._on_line_done)
        worker.error.connect(lambda msg: (self._show_status(f"Generation failed: {msg}"),
                                          QMessageBox.warning(self, "Generation failed", msg)))
        worker.finished.connect(self._on_generation_finished)
        worker.cancelled.connect(self._on_generation_cancelled)

    def _on_line_done(self, _index: int, speaker: str) -> None:
        self._show_status(f"Generated line for {speaker}…")

    def _on_generation_finished(self, path: str) -> None:
        self.editor.generation_finished()
        if not path:
            return
        p = Path(path)
        try:
            import soundfile as sf
            info = sf.info(str(p))
            self._set_audio_length(info.frames / info.samplerate)
            self._previewer.play_file(p)
        except Exception:  # noqa: BLE001
            pass
        self._show_status(f"Saved to {p.name}  ·  SRT written alongside")

    def _on_generation_cancelled(self) -> None:
        self.editor.generation_finished()
        self._show_status("Generation cancelled")

    def _cancel_generation(self) -> None:
        if self._gen_worker is not None:
            self._gen_worker.cancel()

    # --------------------------------------------------------------- preview

    def _preview_line(self, row: int) -> None:
        if not self._engine.ready:
            self._show_status("Engine still loading — try again in a moment.")
            return
        project = self.editor.snapshot_project()
        if row < 0 or row >= len(project.lines):
            return
        line = project.lines[row]
        prof = project.speaker(line.speaker)
        if prof is None:
            prof = project.add_speaker_if_missing(line.speaker)
        speed = line.speed if line.speed is not None else prof.speed
        pitch = line.pitch if line.pitch is not None else prof.pitch
        self._spawn_preview(line.text, prof.voice_id, speed, pitch)

    def _preview_sample(self, voice_id: str, text: str, speed: float, pitch: float) -> None:
        if not self._engine.ready:
            self._show_status("Engine still loading — try again in a moment.")
            return
        self._spawn_preview(text or PREVIEW_TEXT, voice_id, speed, pitch)

    def _preview_voice(self, voice_id: str) -> None:
        if not self._engine.ready:
            self._show_status("Engine still loading — try again in a moment.")
            return
        self._spawn_preview(PREVIEW_TEXT, voice_id, 1.0, 0.0)

    def _spawn_preview(self, text: str, voice_id: str, speed: float, pitch: float) -> None:
        self._previewer.stop()
        worker = PreviewRunner(self._engine, text, voice_id, speed, pitch)
        thread = QThread()
        self._preview_threads.add(thread)  # see _init_engine_thread: never GC a running QThread
        self._preview_workers.add(worker)  # dead receivers silently disconnect: never GC a queued worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._on_preview_audio)
        worker.failed.connect(lambda e: self._show_status(f"Preview failed: {e}"))
        for sig in (worker.completed, worker.failed):
            sig.connect(thread.quit)
            sig.connect(worker.deleteLater)
        worker.completed.connect(lambda _audio: self._preview_workers.discard(worker))
        worker.failed.connect(lambda _err: self._preview_workers.discard(worker))
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._preview_threads.discard(t))
        thread.finished.connect(lambda t=thread: _ORPHAN_THREADS.discard(t))
        thread.start()

    def _on_preview_audio(self, audio) -> None:
        self._previewer.play_array(audio)
        self._set_audio_length(len(audio) / 24000.0)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._previewer.stop()
        if self._gen_worker is not None:
            self._gen_worker.cancel()
        _shutdown_thread(self._gen_thread, 5000)
        for t in list(self._preview_threads):
            _shutdown_thread(t, 2000)
        self._preview_threads.clear()
        self._preview_workers.clear()
        _shutdown_thread(self._engine_thread, 5000)
        self._engine_thread = None
        self._engine_loader = None
        super().closeEvent(event)

    # -------------------------------------------------------- project actions

    def new_project(self) -> None:
        if self._confirm_discard():
            self.current_project = self._default_project()
            self._current_file = None
            self.editor.set_project(self.current_project)
            self.setWindowTitle(f"{APP_NAME} {__version__} — Untitled Project")
            self._show_status("New project")

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", str(Path.home()), "Kokoro Studio projects (*.kstudio)")
        if path:
            self._load_project(path)

    def _load_project(self, path: str) -> None:
        try:
            project = Project.load(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Open failed", str(e))
            return
        self.current_project = project
        self._current_file = path
        self.editor.set_project(project)
        self.setWindowTitle(f"{APP_NAME} {__version__} — {project.title}")
        add_recent_file(path)
        self.rebuild_recent_menu()
        self._show_status(f"Opened {Path(path).name}")

    def save_project(self) -> None:
        if self._current_file:
            self._do_save(self._current_file)
        else:
            self.save_project_as()

    def save_project_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project", str(Path.home() / "Untitled Project.kstudio"),
            "Kokoro Studio projects (*.kstudio)")
        if path:
            self._do_save(path)

    def _do_save(self, path: str) -> None:
        project = self.editor.snapshot_project()
        project.save(path)
        self._current_file = str(path)
        self.current_project = project
        self.setWindowTitle(f"{APP_NAME} {__version__} — {project.title}")
        add_recent_file(path)
        self.rebuild_recent_menu()
        self._show_status(f"Saved {Path(path).name}")

    def rebuild_recent_menu(self) -> None:
        self.recent_menu.clear()
        for p in load_recent_files()[:8]:
            act = QAction(p, self)
            act.triggered.connect(lambda _=False, path=p: self._load_project(path))
            self.recent_menu.addAction(act)
        if not self.recent_menu.actions():
            self.recent_menu.addAction("(no recent files)").setEnabled(False)

    def export_srt(self) -> None:
        """SRT is written alongside generated audio (see _on_generate)."""
        self._show_status("SRT subtitles are written next to each generated audio file.")

    def _confirm_discard(self) -> bool:
        try:
            lines = self.editor.snapshot_project().lines
        except Exception:  # noqa: BLE001
            lines = self.current_project.lines
        if not any(line.text.strip() for line in lines):
            return True
        ret = QMessageBox.question(
            self, "New project",
            "Discard the current dialogue and start a new project?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return ret == QMessageBox.StandardButton.Yes

    # ------------------------------------------------------------- voices menu

    def _pick_speaker_voice(self, which: str) -> None:
        from PySide6.QtWidgets import QInputDialog
        choices = sorted(VOICE_CATALOG)
        voice_id, ok = QInputDialog.getItem(self, f"Set Speaker {which} voice",
                                            "Voice:", choices, 0, False)
        if ok and voice_id:
            self._on_set_default_voice(voice_id, which)

    def _on_set_default_voice(self, voice_id: str, which: str) -> None:
        s = self._settings
        if which == "A":
            s.default_voice_a = voice_id
        else:
            s.default_voice_b = voice_id
        s.save()
        # Push into the current editor panel.
        a, b = self.editor.voice_panel.profiles()
        if which == "A":
            a = SpeakerProfile(a.name, voice_id, a.speed, a.pitch)
        else:
            b = SpeakerProfile(b.name, voice_id, b.speed, b.pitch)
        self.editor.voice_panel.set_profiles(a, b)
        self.current_project.speakers = [a, b]
        self._show_status(f"Speaker {which} default voice set to {voice_id}")

    def _rebuild_default_voices(self) -> None:
        s = self._settings
        a, b = self.editor.voice_panel.profiles()
        s.default_voice_a = a.voice_id
        s.default_voice_b = b.voice_id
        s.default_speed_a = a.speed
        s.default_speed_b = b.speed
        s.save()
        self._show_status("Default voices updated from current panel")

    # --------------------------------------------------------- settings hooks

    def _on_settings_saved(self, settings: Settings) -> None:
        old = self._settings
        self._settings = settings
        recreate = (settings.model_repo_id != old.model_repo_id or settings.device != old.device)
        if recreate:
            from ..core.tts_engine import set_engine
            set_engine(None)
            self._engine = TTSEngine(model_repo_id=settings.model_repo_id,
                                     device=settings.device)
            self._batch_runner.set_engine(self._engine)
        self._init_engine_thread()
        from PySide6.QtCore import QTimer as _QTimer
        _QTimer.singleShot(0, self._maybe_offer_recovery)
        self._apply_theme(settings.theme)
        self._show_status("Settings saved")

    # --------------------------------------------------------------- theming

    def _apply_theme(self, theme: str) -> None:
        theme = theme or "dark"
        if theme == "system":
            theme = self._detect_system_theme()
        resource = "dark" if theme == "dark" else "light"
        qss = _load_qss(resource)
        if qss:
            QApplication.instance().setStyleSheet(qss)
        self._current_theme = theme

    def _detect_system_theme(self) -> str:
        try:
            from PySide6.QtGui import QColor
            w = QApplication.instance().palette().color(QPalette.ColorRole.Window)
            return "dark" if w.lightness() < 128 else "light"
        except Exception:  # noqa: BLE001
            return "dark"

    def _show_shortcuts(self) -> None:
        QMessageBox.information(self, "Keyboard shortcuts",
            "Ctrl+N  New project\n"
            "Ctrl+O  Open project\n"
            "Ctrl+S  Save\n"
            "Ctrl+Shift+S  Save As\n"
            "Ctrl+G  Generate (Batch: Generate All)\n"
            "Ctrl+L  Voice Library\n"
            "Ctrl+B  Batch mode\n"
            "Ctrl+Enter  Add line\n"
            "Space  Preview selected line\n"
            "Ctrl+Z / Ctrl+Shift+Z  Undo / Redo\n"
            "Ctrl+Q  Quit")


def _load_qss(kind: str) -> str:
    path = Path(__file__).parent / ".." / "assets" / "styles" / f"app_{kind}.qss"
    try:
        return path.resolve().read_text(encoding="utf-8")
    except OSError:
        return ""
