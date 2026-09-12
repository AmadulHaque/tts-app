"""Tab 3 — Batch Generator.

A serial queue of projects rendered one at a time by the shared BatchRunner,
with per-row progress, pause/resume/cancel and a CSV report."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QHeaderView, QMessageBox, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.batch_runner import BatchItem, BatchRunner, write_batch_report
from ..core.project import Project
from ..utils import paths as app_paths
from ..utils import import_export
from .widgets.busy import clear_busy, set_busy

STATUS_COLORS = {
    "Queued": Qt.GlobalColor.gray,
    "Running": Qt.GlobalColor.blue,
    "Cancel": Qt.GlobalColor.gray,
    "Cancelled": Qt.GlobalColor.darkYellow,
    "Done": Qt.GlobalColor.darkGreen,
    "Failed": Qt.GlobalColor.red,
    "Skipped": Qt.GlobalColor.gray,
}


class BatchGeneratorTab(QWidget):
    status_message = Signal(str)

    def __init__(self, runner: BatchRunner, parent=None):
        super().__init__(parent)
        self._runner = runner
        self._row_by_name: dict[str, int] = {}

        root = QVBoxLayout(self)

        # Buttons
        bar = QHBoxLayout()
        self.add_btn = QPushButton("＋ Add Project")
        self.folder_btn = QPushButton("📂 Load Folder")
        self.remove_btn = QPushButton("🗑 Remove")
        self.gen_all_btn = QPushButton("▶ Generate All")
        self.gen_sel_btn = QPushButton("▶ Generate Selected")
        self.pause_btn = QPushButton("⏸ Pause")
        self.resume_btn = QPushButton("▶ Resume")
        self.cancel_btn = QPushButton("✕ Cancel")
        self.report_btn = QPushButton("📄 Export Report")
        for b in (self.add_btn, self.folder_btn, self.remove_btn, self.gen_all_btn,
                  self.gen_sel_btn, self.pause_btn, self.resume_btn, self.cancel_btn,
                  self.report_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Project", "Status", "Progress", "Duration", "Output"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(2, 160)
        root.addWidget(self.table, 1)

        # Wiring
        self.add_btn.clicked.connect(self._add_project)
        self.folder_btn.clicked.connect(self._load_folder)
        self.remove_btn.clicked.connect(self._remove_selected)
        self.gen_all_btn.clicked.connect(lambda: self._start(selected_only=False))
        self.gen_sel_btn.clicked.connect(lambda: self._start(selected_only=True))
        self.pause_btn.clicked.connect(self._pause)
        self.resume_btn.clicked.connect(self._resume)
        self.cancel_btn.clicked.connect(self._cancel_batch)
        self.report_btn.clicked.connect(self._export_report)

        self._runner.item_progress.connect(self._on_progress)
        self._runner.item_status.connect(self._on_status)
        self._runner.paused_changed.connect(self._on_paused_changed)
        self._runner.queue_finished.connect(self._on_queue_finished)

        self._refresh_buttons()

    def _on_queue_finished(self) -> None:
        self.status_message.emit("Batch finished")
        self._refresh_buttons()

    def _pause(self) -> None:
        if self._runner.is_running():
            self._runner.pause()
            self.status_message.emit("Batch paused (finishes current line, then holds)")

    def _resume(self) -> None:
        if self._runner.is_running():
            self._runner.resume()
            self.status_message.emit("Batch resumed")

    def _cancel_batch(self) -> None:
        if not self._runner.is_running():
            return
        self._runner.stop()
        self.status_message.emit("Batch stopped — remaining projects stay queued")

    def _on_paused_changed(self, paused: bool) -> None:
        self._refresh_buttons()

    # -- adding items --------------------------------------------------------

    def _add_project(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add project(s)", str(Path.home()),
            "Kokoro Studio projects (*.kstudio);;Scripts (*.txt);;All files (*)")
        for p in paths:
            self._add_path(p)
        self._rebuild_table()

    def _load_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Load project folder", str(Path.home()))
        if not folder:
            return
        found = sorted(Path(folder).rglob("*.kstudio"))
        if not found:
            self.status_message.emit("No .kstudio projects found in that folder")
            return
        for p in found:
            self._add_path(p)
        self._rebuild_table()
        self.status_message.emit(f"Added {len(found)} projects from {Path(folder).name}")

    def _add_path(self, path: str | Path) -> None:
        p = Path(path)
        if p.suffix.lower() == ".txt":
            project = Project(title=p.stem)
            project.lines = import_export.parse_txt(p.read_text(encoding="utf-8-sig"))
            for l in project.lines:
                project.add_speaker_if_missing(l.speaker)
        else:
            try:
                project = Project.load(p)
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "Could not load project", f"{p.name}: {e}")
                return
        existing = {i.project.title for i in self._runner.items}
        if project.title in existing:
            project.title = f"{project.title} ({p.stem})"
        out = project.default_output_path()
        item = BatchItem(name=project.title, project=project, output_path=str(out))
        self._runner.add_item(item)

    # -- table ------------------------------------------------------------

    def _rebuild_table(self) -> None:
        self.table.setRowCount(0)
        self._row_by_name.clear()
        for i, item in enumerate(self._runner.items):
            self._row_by_name[item.name] = i
            self.table.insertRow(i)
            self.table.setItem(i, 0, QTableWidgetItem(item.name))
            self.table.setItem(i, 1, self._status_item(item))
            self.table.setCellWidget(i, 2, QProgressBar())
            self.table.setItem(i, 3, QTableWidgetItem("—"))
            self.table.setItem(i, 4, QTableWidgetItem(item.output_path))
            self._apply_status_row(i, item)
        self._refresh_buttons()

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        name = self.table.item(row, 0).text()
        item = self._runner.find_item(name)
        if item is not None:
            self._runner.remove_item(item)
        self._rebuild_table()

    def _row(self, item: BatchItem) -> int:
        return self._row_by_name.get(item.name, -1)

    # -- running --------------------------------------------------------------

    def _start(self, selected_only: bool) -> None:
        items = self._runner.items
        if not items:
            self.status_message.emit("Batch is empty — add some projects first")
            return
        run = items
        if selected_only:
            row = self.table.currentRow()
            name_item = self.table.item(row, 0) if row >= 0 else None
            if name_item is None:
                self.status_message.emit("No project selected")
                return
            run = [i for i in items if i.name == name_item.text()]
        self._runner.start(run)
        self.status_message.emit(f"Batch started ({len(run)} project{'s' if len(run) != 1 else ''})")

    def _on_progress(self, name: str, done: int, total: int) -> None:
        item = self._runner.find_item(name)
        if item and (r := self._row(item)) >= 0:
            bar = self.table.cellWidget(r, 2)
            if isinstance(bar, QProgressBar):
                bar.setRange(0, max(total, 1))
                bar.setValue(done)

    def _on_status(self, name: str, status: str, message: str) -> None:
        item = self._runner.find_item(name)
        if not item:
            return
        if (r := self._row(item)) >= 0:
            self.table.item(r, 1).setText(status)
            if status == "Done":
                self.table.item(r, 3).setText(f"{item.duration:.1f}s" if item.duration else "—")
            elif status == "Failed":
                self.table.item(r, 3).setToolTip(item.error)
            self._apply_status_row(r, item)
        self.status_message.emit(f"{name}: {status}{' — ' + message if message else ''}")
        self._refresh_buttons()

    def _apply_status_row(self, row: int, item: BatchItem) -> None:
        color = QBrush(STATUS_COLORS.get(item.status, Qt.GlobalColor.gray))
        for col in (0, 1, 3, 4):
            if self.table.item(row, col):
                self.table.item(row, col).setForeground(color)

    # -- report ---------------------------------------------------------------

    def _export_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export batch report", str(Path.home() / "batch_report.csv"), "CSV (*.csv)")
        if not path:
            return
        write_batch_report(self._runner.items, path)
        self.status_message.emit(f"Report written to {Path(path).name}")

    # -- misc ---------------------------------------------------------------

    def _status_item(self, item: BatchItem) -> QTableWidgetItem:
        it = QTableWidgetItem(item.status)
        return it

    def _refresh_buttons(self) -> None:
        running = self._runner.is_running()
        paused = running and self._runner.is_paused()
        if running:
            set_busy(self.gen_all_btn, "⏳ Generating")
        else:
            clear_busy(self.gen_all_btn)
        self.gen_all_btn.setEnabled(not running)
        self.gen_sel_btn.setEnabled(not running)
        self.pause_btn.setEnabled(running and not paused)
        self.resume_btn.setEnabled(paused)
        self.cancel_btn.setEnabled(running)
