"""Tab 1 — Dialogue Editor.

A table of lines (speaker / text / pause / est.) backed by a QUndoStack, with
the VoicePanel to the right, import/export, autosave and a generate bar."""

from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QUndoStack
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QFileDialog,
    QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox,
    QProgressBar, QPushButton, QSplitter, QStyledItemDelegate, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.project import Project
from ..models.dialogue import DialogueLine, SpeakerProfile, estimate_speech_time
from ..utils import paths
from ..utils.config import load_settings
from ..utils.import_export import import_file
from . import commands as cmds
from .voice_panel import VoicePanel
from .widgets.busy import clear_busy, set_busy

PAUSE_ROLE = Qt.ItemDataRole.UserRole + 1


class _DialogueDelegate(QStyledItemDelegate):
    """Editors + undo-aware commit for the line table."""

    def __init__(self, editor: "DialogueEditorTab", parent=None):
        super().__init__(parent)
        self._editor = editor

    def createEditor(self, parent, option, index):
        if index.column() == 0:  # speaker
            combo = QComboBox(parent)
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.NoInsert)
            combo.addItems(self._editor.speaker_names())
            return combo
        if index.column() == 2:  # pause
            spin = QDoubleSpinBox(parent)
            spin.setRange(0.0, 60.0)
            spin.setSingleStep(0.1)
            spin.setDecimals(1)
            spin.setSuffix(" s")
            spin.setSpecialValueText("Default")
            return spin
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        row = index.row()
        if index.column() == 0:
            editor.setCurrentText(self._editor.project.lines[row].speaker)
        elif index.column() == 2:
            editor.setValue(self._editor.project.lines[row].pause_after)
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        row = index.row()
        old = self._editor.project.lines[row]
        new = DialogueLine(speaker=old.speaker, text=old.text, pause_after=old.pause_after,
                           speed=old.speed, pitch=old.pitch)
        if index.column() == 0:
            new.speaker = str(editor.currentText()).strip()
        elif index.column() == 1:
            new.text = str(editor.text()).strip()
        elif index.column() == 2:
            new.pause_after = float(editor.value())
        if new != old:
            self._editor._push_edit(row, old, new)
        super().setModelData(editor, model, index)


class DialogueEditorTab(QWidget):
    project_modified = Signal()
    generate_requested = Signal(Project)
    save_requested = Signal()
    cancel_requested = Signal()
    preview_line = Signal(int)                        # text row index
    preview_sample = Signal(str, str, float, float)   # voice_id, text, speed, pitch
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = Project()
        self._project_title = "Untitled Project"
        self._syncing = False
        self.undo_stack = QUndoStack(self)

        root = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QHBoxLayout()
        self.add_btn = QPushButton("＋ Add Line")
        self.delete_btn = QPushButton("🗑 Delete")
        self.up_btn = QPushButton("▲ Up")
        self.down_btn = QPushButton("▼ Down")
        self.dup_btn = QPushButton("⧉ Duplicate")
        self.import_btn = QPushButton("📥 Import")
        self.export_btn = QPushButton("📤 Export")
        for b in (self.add_btn, self.delete_btn, self.up_btn, self.down_btn,
                  self.dup_btn, self.import_btn, self.export_btn):
            toolbar.addWidget(b)
        toolbar.addStretch(1)
        left_layout.addLayout(toolbar)

        # Table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Speaker", "Text", "Pause After", "Est."])
        self.table.setItemDelegate(_DialogueDelegate(self))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        left_layout.addWidget(self.table, 1)

        # Bottom bar
        self.stats_label = QLabel("Words: 0  ·  Est. duration: 0:00")
        bottom = QHBoxLayout()
        self.generate_btn = QPushButton("▶ Generate Audio")
        self.generate_btn.setObjectName("primaryButton")
        self.cancel_btn = QPushButton("✕ Cancel")
        self.cancel_btn.setVisible(False)
        self.save_btn = QPushButton("💾 Save Project")
        bottom.addWidget(self.stats_label)
        bottom.addStretch(1)
        bottom.addWidget(self.save_btn)
        bottom.addWidget(self.generate_btn)
        bottom.addWidget(self.cancel_btn)
        left_layout.addLayout(bottom)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)
        left_layout.addWidget(self.progress)

        splitter.addWidget(left)

        self.voice_panel = VoicePanel()
        splitter.addWidget(self.voice_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([760, 380])
        root.addWidget(splitter)

        # Wiring
        self.add_btn.clicked.connect(self.add_line)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.up_btn.clicked.connect(lambda: self.move_selected(-1))
        self.down_btn.clicked.connect(lambda: self.move_selected(1))
        self.dup_btn.clicked.connect(self.duplicate_selected)
        self.import_btn.clicked.connect(self.import_dialog)
        self.export_btn.clicked.connect(self.export_dialog)
        self.generate_btn.clicked.connect(self.request_generate)
        self.cancel_btn.clicked.connect(self.cancel_generation)
        self.save_btn.clicked.connect(self.save_requested)
        self.voice_panel.changed.connect(self._on_audio_changed)
        self.voice_panel.speakers_renamed.connect(self._on_speakers_renamed)
        self.voice_panel.preview_requested.connect(self._on_preview_speaker)
        self.table.cellChanged.connect(lambda r, c: self._on_cell_changed(r, c))
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # Shortcuts
        QTimer.singleShot(0, self._install_shortcuts)

        # Autosave
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self.autosave)
        self._autosave_timer.start(60_000)

        self._refresh_speaker_combo_source()

    # -- setup / shortcuts -------------------------------------------------

    def _install_shortcuts(self) -> None:
        for seq, slot in [
            (QKeySequence("Ctrl+Enter"), self.add_line),
            (QKeySequence("Ctrl+Z"), self.undo),
            (QKeySequence("Ctrl+Shift+Z"), self.redo),
            (QKeySequence("Ctrl+Y"), self.redo),
            (QKeySequence(Qt.Key.Key_Space), self.preview_selected),
            (QKeySequence(Qt.Key.Key_Delete), self.delete_selected),
        ]:
            sc = QShortcut(seq, self.table)
            sc.activated.connect(slot)
            self._shortcuts = getattr(self, "_shortcuts", []) + [sc]

    def focus_table(self) -> None:
        self.table.setFocus()

    # -- speaker names ------------------------------------------------------

    def speaker_names(self) -> list[str]:
        names = {s.name for s in self.project.speakers}
        if self.project.lines:
            names.update(line.speaker for line in self.project.lines)
        return sorted(names) if names else ["Speaker A", "Speaker B"]

    def _refresh_speaker_combo_source(self) -> None:
        self._combo_names = self.speaker_names()

    # -- model ↔ table ------------------------------------------------------

    def set_project(self, project: Project) -> None:
        self.project = project
        self._project_title = project.title
        profile_a = project.speaker(project.speakers[0].name) if project.speakers else None
        a = profile_a or SpeakerProfile("Speaker A", "am_michael")
        b = None
        if len(project.speakers) > 1:
            b = project.speaker(project.speakers[1].name) or project.speakers[1]
        b = b or SpeakerProfile("Speaker B", "af_heart")
        self.voice_panel.set_profiles(a, b)
        self.voice_panel.set_audio_settings(
            project.pause_between_lines, project.pause_between_speakers,
            project.output_format, project.sample_rate)
        self.undo_stack.clear()
        self._syncing = True
        try:
            self.table.setRowCount(0)
            for i, line in enumerate(project.lines):
                self._insert_table_row(i, line)
        finally:
            self._syncing = False
        self._refresh_speaker_combo_source()
        self.update_stats()

    def snapshot_project(self) -> Project:
        """A fresh Project reflecting the current editor UI."""
        p = Project(title=self._project_title)
        p.speakers = list(self.voice_panel.profiles())
        (p.pause_between_lines, p.pause_between_speakers,
         p.output_format, p.sample_rate) = self.voice_panel.audio_settings()
        p.lines = [self._line_from_row(i) for i in range(self.table.rowCount())]
        settings = load_settings()
        p.normalize = settings.normalize
        p.lufs_target = settings.lufs_target
        p.peak_target_db = settings.peak_target_db
        return p

    def _line_from_row(self, row: int) -> DialogueLine:
        def text(col: int, default: str = "") -> str:
            item = self.table.item(row, col)
            return item.text() if item is not None else default

        pause_item = self.table.item(row, 2)
        try:
            pause = float(pause_item.data(PAUSE_ROLE) or 0.0) if pause_item is not None else 0.0
        except (TypeError, ValueError):
            pause = 0.0
        return DialogueLine(
            speaker=text(0, "Speaker A") or "Speaker A",
            text=text(1),
            pause_after=pause,
        )

    # -- row helpers --------------------------------------------------------

    def _insert_table_row(self, row: int, line: DialogueLine) -> None:
        if row >= self.table.rowCount():
            self.table.setRowCount(row + 1)
        else:
            self.table.insertRow(row)
        self._write_row_items(row, line)

    def _write_row_items(self, row: int, line: DialogueLine) -> None:
        speaker_item = QTableWidgetItem(line.speaker)
        text_item = QTableWidgetItem(line.text)
        text_item.setToolTip("Double-click to edit. Ctrl+Enter adds a new line.")
        pause_item = QTableWidgetItem("Default" if line.pause_after <= 0 else f"{line.pause_after:.1f} s")
        est = QTableWidgetItem(self._est_text(row, line))
        est.setFlags(est.flags() & ~Qt.ItemFlag.ItemIsEditable)
        for col, item in enumerate((speaker_item, text_item, pause_item, est)):
            self.table.setItem(row, col, item)
        pause_item.setData(PAUSE_ROLE, float(line.pause_after))

    def _update_table_row(self, row: int) -> None:
        line = self.project.lines[row]
        self.table.item(row, 0).setText(line.speaker)
        self.table.item(row, 1).setText(line.text)
        pause_item = self.table.item(row, 2)
        pause_item.setText("Default" if line.pause_after <= 0 else f"{line.pause_after:.1f} s")
        pause_item.setData(PAUSE_ROLE, float(line.pause_after))
        self.table.item(row, 3).setText(self._est_text(row, line))

    def _est_text(self, row: int, line: DialogueLine) -> str:
        prof = self.project.speaker(line.speaker)
        speed = line.speed if line.speed is not None else (prof.speed if prof else 1.0)
        speaking = estimate_speech_time(line.text, speed)
        pause = line.pause_after if line.pause_after else 0.0
        total = speaking + pause
        return f"{int(total // 60)}:{total % 60:04.1f}"

    def _remove_table_row(self, row: int) -> None:
        self.table.removeRow(row)

    def _resync_rows(self) -> None:
        self._syncing = True
        try:
            self.table.setRowCount(0)
            for i, line in enumerate(self.project.lines):
                self._insert_table_row(i, line)
        finally:
            self._syncing = False

    # -- edits ---------------------------------------------------------------

    def apply_op(self, op: str, row: int, line: DialogueLine | None = None, dst: int | None = None) -> None:
        """Dispatcher used by undo/redo commands and toolbar actions."""
        if op == "add" and line is not None:
            self.project.lines.insert(row, line)
            self.project.add_speaker_if_missing(line.speaker)
            self._syncing = True
            try:
                self._insert_table_row(row, line)
            finally:
                self._syncing = False
        elif op == "remove":
            self.project.lines.pop(row)
            self._syncing = True
            try:
                self._remove_table_row(row)
            finally:
                self._syncing = False
        elif op == "move" and dst is not None:
            line = self.project.lines.pop(row)
            self.project.lines.insert(dst, line)
            self._resync_rows()
        elif op == "edit" and line is not None:
            self.project.lines[row] = line
            self._syncing = True
            try:
                self._update_table_row(row)
            finally:
                self._syncing = False
        elif op == "set_all" and line is not None:
            lines = line if isinstance(line, list) else [line]
            self.project.lines = list(lines)
            self._resync_rows()
        self._refresh_speaker_combo_source()
        self.project_modified.emit()
        self.update_stats()

    def _push_edit(self, row: int, old: DialogueLine, new: DialogueLine) -> None:
        self.undo_stack.push(cmds.EditLineCommand(self.apply_op, row, old, new))
        self.project_modified.emit()
        self.update_stats()

    def _on_cell_changed(self, row: int, _col: int) -> None:
        # Delegate handles project edits; here we only refresh derived stats.
        # Skip while rows are half-written (signals fire per setItem).
        if self._syncing:
            return
        self.update_stats()

    # -- toolbar actions -----------------------------------------------------

    def add_line(self, *, index: int | None = None) -> None:
        row = index if index is not None else self.table.currentRow()
        if row < 0:
            row = 0
        line = DialogueLine(speaker=self._default_speaker(), text="")
        self.undo_stack.push(cmds.AddLineCommand(self.apply_op, row, line))
        self.project.add_speaker_if_missing(line.speaker)
        self.table.setCurrentCell(row, 1)
        self.table.editItem(self.table.item(row, 1))

    def _default_speaker(self) -> str:
        names = self.speaker_names()
        if not names:
            return "Speaker A"
        row = self.table.currentRow()
        if row >= 0 and row < self.table.rowCount():
            cur = self.table.item(row, 0).text() if self.table.item(row, 0) else ""
            if cur in names:
                idx = names.index(cur)
                return names[(idx + 1) % len(names)]
        return "Speaker A"

    def delete_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.project.lines):
            return
        self.undo_stack.push(cmds.RemoveLineCommand(self.apply_op, row, self.project.lines[row]))

    def move_selected(self, delta: int) -> None:
        row = self.table.currentRow()
        dst = row + delta
        if row < 0 or dst < 0 or dst >= len(self.project.lines):
            return
        self.undo_stack.push(cmds.MoveLineCommand(self.apply_op, row, dst))

    def duplicate_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.project.lines):
            return
        import copy
        line = copy.deepcopy(self.project.lines[row])
        self.undo_stack.push(cmds.DuplicateLineCommand(self.apply_op, row, line))

    def undo(self) -> None:
        if self.undo_stack.canUndo():
            self.undo_stack.undo()

    def redo(self) -> None:
        if self.undo_stack.canRedo():
            self.undo_stack.redo()

    def preview_selected(self) -> None:
        row = self.table.currentRow()
        if row >= 0 and row < len(self.project.lines):
            self.preview_line.emit(row)

    def _on_preview_speaker(self, name: str) -> None:
        for prof in self.voice_panel.profiles():
            if prof.name == name:
                self.preview_sample.emit(prof.voice_id, "", prof.speed, prof.pitch)
                return
        self.status_message.emit(f"No speaker named “{name}” to preview")

    # -- import / export ------------------------------------------------------

    def import_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import dialogue", str(Path.home()),
            "Dialogue files (*.txt *.json *.csv *.srt);;All files (*)")
        if not path:
            return
        try:
            lines = import_file(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Import failed", str(e))
            return
        before = self._current_lines()
        self.undo_stack.push(cmds.SetLinesCommand(self.apply_op, before, list(lines)))
        for l in lines:
            self.project.add_speaker_if_missing(l.speaker)
        self._refresh_speaker_combo_source()
        self.status_message.emit(f"Imported {len(lines)} lines from {Path(path).name}")

    def export_dialog(self) -> None:
        from ..utils import import_export
        lines = [self._line_from_row(i) for i in range(self.table.rowCount())]
        path, _ = QFileDialog.getSaveFileName(
            self, "Export dialogue", str(Path.home() / "dialogue.json"),
            "JSON (*.json);;CSV (*.csv);;Text (*.txt);;Subtitles (*.srt)")
        if not path:
            return
        suffix = Path(path).suffix.lower().lstrip(".")
        if suffix == "srt":
            content = import_export.export_srt(self._estimated_timings())
        else:
            content = {"json": import_export.export_json,
                       "csv": import_export.export_csv,
                       "txt": import_export.export_txt}.get(suffix, import_export.export_json)(lines)
        Path(path).write_text(content, encoding="utf-8")
        self.status_message.emit(f"Exported to {Path(path).name}")

    def _estimated_timings(self) -> list[tuple[float, float, str, str]]:
        """Estimate (start, end, speaker, text) per line for SRT export."""
        try:
            project = self.snapshot_project()
        except Exception:  # noqa: BLE001
            return []
        timed: list[tuple[float, float, str, str]] = []
        cursor = 0.0
        lines = [l for l in project.lines if l.text.strip()]
        for i, line in enumerate(lines):
            prof, speed, _pitch = project.line_profile(line)
            speaking = estimate_speech_time(line.text, speed)
            timed.append((cursor, cursor + speaking, line.speaker, line.text))
            cursor += speaking
            if i + 1 < len(lines):
                pause = (project.pause_between_speakers
                         if line.speaker != lines[i + 1].speaker
                         else project.pause_between_lines)
                if line.pause_after:
                    pause = line.pause_after
                cursor += pause
        return timed

    def _current_lines(self) -> list[DialogueLine]:
        return list(self.project.lines)

    # -- generation -------------------------------------------------------------

    def request_generate(self) -> None:
        project = self.snapshot_project()
        if not any(line.text.strip() for line in project.lines):
            self.status_message.emit("Nothing to generate — add some dialogue lines first.")
            return
        self.generate_requested.emit(project)
        set_busy(self.generate_btn, "⏳ Generating")
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.cancel_btn.setVisible(True)

    def set_generation_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)

    def generation_finished(self) -> None:
        clear_busy(self.generate_btn)
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)

    def set_preview_busy(self, busy: bool) -> None:
        self.voice_panel.set_preview_busy(busy)

    def cancel_generation(self) -> None:
        self.cancel_requested.emit()  # type: ignore[attr-defined]

    # -- autosave / stats ---------------------------------------------------------

    def autosave(self) -> None:
        project = self.snapshot_project()
        if not project.lines:
            return
        try:
            path = paths.autosave_dir() / f"{self._safe_title()}.autosave.kstudio"
            project.save(path)
            # Prune old autosaves so crash recovery stays tidy (keep newest 5).
            autosaves = sorted(paths.autosave_dir().glob("*.autosave.kstudio"),
                               key=lambda p: p.stat().st_mtime, reverse=True)
            for stale in autosaves[5:]:
                try:
                    stale.unlink()
                except OSError:
                    pass
        except Exception as e:  # noqa: BLE001
            self.status_message.emit(f"Autosave failed: {e}")

    def _safe_title(self) -> str:
        return "".join(c for c in self._project_title if c.isalnum() or c in " _-").strip() or "untitled"

    def update_stats(self) -> None:
        words = sum(self._line_from_row(i).word_count for i in range(self.table.rowCount()))
        try:
            project = self.snapshot_project()
            est = project.estimated_duration()
        except Exception:  # noqa: BLE001
            est = 0.0
        m, s = divmod(int(est), 60)
        self.stats_label.setText(f"Words: {words}  ·  Est. duration: {m}:{s:02d}")

    # -- voice panel hooks ---------------------------------------------------------

    def _on_audio_changed(self) -> None:
        self._refresh_speaker_combo_source()
        if not self._syncing:
            for row in range(self.table.rowCount()):
                if row < len(self.project.lines):
                    self._update_table_row(row)
        self.project_modified.emit()
        self.update_stats()

    def _on_speakers_renamed(self) -> None:
        self._refresh_speaker_combo_source()
        self._resync_rows()
        self.project_modified.emit()
        self.update_stats()

    # -- context menu ---------------------------------------------------------------

    def _context_menu(self, pos) -> None:
        menu = QMenu(self.table)
        idx = self.table.indexAt(pos)
        if idx.isValid():
            menu.addAction("Insert line above", lambda: self.add_line(index=idx.row()))
            menu.addAction("Duplicate", self.duplicate_selected)
            menu.addAction("Delete", self.delete_selected)
            menu.addSeparator()
        copy_action = menu.addAction("Copy row")
        paste_action = menu.addAction("Paste row")
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action is None:
            return
        if action == copy_action:
            self._copy_row()
        elif action == paste_action:
            self._paste_row()

    def _copy_row(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        line = self._line_from_row(row)
        self._clipboard_line = line

    def _paste_row(self) -> None:
        line = getattr(self, "_clipboard_line", None)
        if line is None:
            return
        row = max(0, self.table.currentRow() + 1)
        import copy
        self.undo_stack.push(cmds.AddLineCommand(self.apply_op, row, copy.deepcopy(line)))
        self.table.setCurrentCell(row, 0)
