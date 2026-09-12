"""Threaded generation.

Single-project generation runs in a dedicated QThread via ``GenerationWorker``.
Batch mode uses a single worker thread that consumes jobs serially — the
Kokoro model is not thread-safe, so inference never overlaps.

The actual synthesis pipeline lives in ``generate_project`` (plain Python so it
is testable without Qt)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..utils.logger import get_logger
from . import audio_processor
from .project import Project
from .tts_engine import TTSEngine

log = get_logger("batch_runner")


# ---------------------------------------------------------------------------
# Core generation (no Qt)
# ---------------------------------------------------------------------------

def generate_project(
    project: Project,
    engine: TTSEngine,
    output_path: str | Path,
    *,
    cancel_event: threading.Event | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
    line_done_cb: Callable[[int, str], None] | None = None,
    srt_path: str | Path | None = None,
) -> dict:
    """Generate a full dialogue audio file for *project*.

    Returns {"path", "duration", "offsets"}. Raises InterruptedError on
    cancellation and RuntimeError/ValueError on failures. ``srt_path`` gets a
    timing-accurate subtitle file written alongside."""

    plan = project.render_plan()
    total = len(plan)
    if total == 0:
        raise ValueError("Project has no non-empty dialogue lines to generate")

    sr = project.sample_rate
    line_audios: list = []
    speakers: list[str] = []
    overrides: list[float | None] = []

    for step, item in enumerate(plan):
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Generation cancelled")
        audio = engine.synthesize(item["text"], item["voice_id"], item["speed"],
                                  cancel_event=cancel_event)
        if item.get("pitch"):
            audio = audio_processor.pitch_shift(audio, float(item["pitch"]), sr=sr)
        line_audios.append(audio)
        speakers.append(item["speaker"])
        overrides.append(item.get("pause_after"))
        if progress_cb:
            progress_cb(step + 1, total)
        if line_done_cb:
            line_done_cb(step, item["speaker"])

    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError("Generation cancelled")

    audio, offsets = audio_processor.build_audio(
        line_audios, speakers,
        pause_between_lines=project.pause_between_lines,
        pause_between_speakers=project.pause_between_speakers,
        line_pause_overrides=overrides,
        sr=sr,
    )
    audio = audio_processor.normalize(
        audio, project.normalize,
        sr=sr, peak_target_db=project.peak_target_db, lufs_target=project.lufs_target)

    out = audio_processor.export(audio, output_path, project.output_format, sr=sr)

    if srt_path:
        timed = [(start, end, plan[i]["speaker"], plan[i]["text"])
                 for i, (start, end) in enumerate(offsets)]
        project.export_srt(timed, srt_path)

    duration = audio_processor.duration_seconds(audio, sr)
    return {"path": str(out), "duration": duration, "offsets": offsets}


# ---------------------------------------------------------------------------
# Single-project worker in a QThread
# ---------------------------------------------------------------------------

class GenerationWorker(QObject):
    progress = Signal(int, int)        # (done, total)
    line_done = Signal(int, str)       # (index, speaker)
    status = Signal(str)
    error = Signal(str)
    finished = Signal(str)             # output path
    cancelled = Signal()

    def __init__(self, project: Project, engine: TTSEngine, output_path: str,
                 srt_path: str | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._project = project
        self._engine = engine
        self._output_path = output_path
        self._srt_path = srt_path
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        try:
            self.status.emit("Initializing…")
            result = generate_project(
                self._project, self._engine, self._output_path,
                cancel_event=self._cancel,
                progress_cb=lambda d, t: self.progress.emit(d, t),
                line_done_cb=lambda i, s: self.line_done.emit(i, s),
                srt_path=self._srt_path,
            )
            if self._cancel.is_set():
                self.cancelled.emit()
                return
            self.status.emit(f"Done — {result['duration']:.1f}s")
            self.finished.emit(result["path"])
        except InterruptedError:
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001
            log.exception("Generation failed")
            self.error.emit(str(e))
            self.finished.emit("")


def run_worker_thread(worker: GenerationWorker) -> QThread:
    """Move *worker* onto a fresh QThread, start it, and return the thread."""
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.cancelled.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    worker.cancelled.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread


class PreviewRunner(QObject):
    """One-shot worker for preview synthesis; moved to a fresh QThread."""

    completed = Signal(object)   # numpy array (float32 @24k)
    failed = Signal(str)

    def __init__(self, engine: TTSEngine, text: str, voice_id: str,
                 speed: float = 1.0, pitch: float = 0.0, parent: QObject | None = None):
        super().__init__(parent)
        self._engine = engine
        self._text = text
        self._voice_id = voice_id
        self._speed = speed
        self._pitch = pitch

    @Slot()
    def run(self) -> None:
        try:
            audio = self._engine.synthesize(self._text, self._voice_id, self._speed)
            if self._pitch:
                audio = audio_processor.pitch_shift(audio, self._pitch)
            self.completed.emit(audio)
        except Exception as e:  # noqa: BLE001
            log.warning("Preview failed: %s", e)
            self.failed.emit(str(e))


class EngineLoader(QObject):
    """Background initializer for the TTS engine (torch import + weights)."""

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


# ---------------------------------------------------------------------------
# Batch queue: serial job runner with pause/resume/cancel
# ---------------------------------------------------------------------------

@dataclass
class BatchItem:
    name: str
    project: Project
    output_path: str
    status: str = "Queued"            # Queued|Running|Done|Failed|Skipped|Cancelled
    progress: int = 0
    total: int = 0
    duration: float = 0.0
    error: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event)


class BatchRunner(QObject):
    """Serial job queue. A persistent worker thread consumes jobs one at a time
    (the Kokoro model is single-inference); the runner object stays on the main
    thread, so its Qt signals auto-queue to the UI."""

    item_progress = Signal(str, int, int)     # (name, done, total)
    item_status = Signal(str, str, str)       # (name, status, message)
    queue_finished = Signal()

    def __init__(self, engine: TTSEngine, parent: QObject | None = None):
        super().__init__(parent)
        self._engine = engine
        self._items: list[BatchItem] = []
        self._worker: threading.Thread | None = None
        self._running = threading.Event()
        self._paused = threading.Event()
        self._stop = threading.Event()
        self._current_lock = threading.Lock()
        self._current: BatchItem | None = None

    def set_engine(self, engine: TTSEngine) -> None:
        self._engine = engine

    # -- public API (main thread) ----------------------------------------

    def add_item(self, item: BatchItem) -> None:
        self._items.append(item)

    def set_items(self, items: list[BatchItem]) -> None:
        self._items = list(items)

    def find_item(self, name: str) -> BatchItem | None:
        return next((i for i in self._items if i.name == name), None)

    def remove_item(self, item: BatchItem) -> None:
        if item in self._items:
            self._items.remove(item)

    @property
    def items(self) -> list[BatchItem]:
        return list(self._items)

    def clear(self) -> None:
        self._items.clear()

    def start(self) -> None:
        if self.is_running():
            return
        self._paused.clear()
        self._stop.clear()
        self._running.set()
        self._worker = threading.Thread(target=self._process_queue, daemon=True,
                                        name="kokoro-batch")
        self._worker.start()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def cancel_current(self) -> None:
        with self._current_lock:
            if self._current is not None:
                self._current.cancel_event.set()

    def stop(self) -> None:
        self.cancel_current()
        self._paused.clear()
        self._stop.set()
        self._running.clear()

    def is_running(self) -> bool:
        return self._running.is_set()

    # -- worker thread ----------------------------------------------------

    def _process_queue(self) -> None:
        try:
            for item in list(self._items):
                if self._stop.is_set():
                    break
                while self._paused.is_set() and not self._stop.is_set():  # blocking pause
                    if not item.cancel_event.wait(0.2):
                        continue
                    break
                if self._stop.is_set():
                    break
                item.status = "Running"
                item.progress, item.total = 0, 0
                self.item_status.emit(item.name, item.status, "")
                self._run_item(item)
        except Exception as e:  # noqa: BLE001
            log.exception("Batch loop crashed: %s", e)
        finally:
            self._running.clear()
            self.queue_finished.emit()

    def _run_item(self, item: BatchItem) -> None:
        with self._current_lock:
            self._current = item
        try:
            srt_path = str(Path(item.output_path).with_suffix(".srt"))
            result = generate_project(
                item.project, self._engine, item.output_path,
                cancel_event=item.cancel_event,
                progress_cb=lambda d, t: self._emit_progress(item, d, t),
                srt_path=srt_path,
            )
            if item.cancel_event.is_set():
                item.status = "Cancelled"
                self.item_status.emit(item.name, item.status, "Cancelled")
            else:
                item.status = "Done"
                item.duration = result["duration"]
                self.item_status.emit(item.name, item.status, f"{item.duration:.1f}s")
        except InterruptedError:
            item.status = "Cancelled"
            self.item_status.emit(item.name, item.status, "Cancelled")
        except Exception as e:  # noqa: BLE001
            log.exception("Batch item %s failed", item.name)
            item.status = "Failed"
            item.error = str(e)
            self.item_status.emit(item.name, item.status, str(e))
        finally:
            with self._current_lock:
                self._current = None
            item.cancel_event.clear()

    def _emit_progress(self, item: BatchItem, done: int, total: int) -> None:
        item.progress, item.total = done, total
        self.item_progress.emit(item.name, done, total)


# ---------------------------------------------------------------------------
# Batch report
# ---------------------------------------------------------------------------

def write_batch_report(items: list[BatchItem], path: str | Path) -> Path:
    """CSV summary of a completed batch."""
    import csv

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Project", "Status", "Duration (s)", "Output", "Error"])
        for it in items:
            writer.writerow([it.name, it.status, f"{it.duration:.2f}" if it.duration else "",
                             it.output_path, it.error])
    return target
