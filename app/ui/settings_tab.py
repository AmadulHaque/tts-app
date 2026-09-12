"""Tab 4 — Settings."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..models.voice import VOICE_CATALOG
from ..utils import paths
from ..utils.config import Settings


def _voice_combo():
    combo = QComboBox()
    for vid in sorted(VOICE_CATALOG):
        info = VOICE_CATALOG[vid]
        combo.addItem(f"{info.name} ({vid}) · {info.accent}", vid)
    return combo


class SettingsTab(QWidget):
    settings_saved = Signal(Settings)
    theme_changed = Signal(str)
    status_message = Signal(str)

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        root = QVBoxLayout(self)

        # Voices
        voice_group = QGroupBox("Voices")
        vf = QFormLayout(voice_group)
        self.voice_a = _voice_combo()
        self.voice_b = _voice_combo()
        self.speed_a = QDoubleSpinBox(); self.speed_a.setRange(0.5, 1.5); self.speed_a.setSingleStep(0.05)
        self.speed_b = QDoubleSpinBox(); self.speed_b.setRange(0.5, 1.5); self.speed_b.setSingleStep(0.05)
        vf.addRow("Default Speaker A:", self.voice_a)
        vf.addRow("Default Speaker B:", self.voice_b)
        vf.addRow("Default speed A:", self.speed_a)
        vf.addRow("Default speed B:", self.speed_b)
        root.addWidget(voice_group)

        # Output
        out_group = QGroupBox("Output")
        of = QFormLayout(out_group)
        self.format_combo = QComboBox(); self.format_combo.addItems(["WAV", "MP3", "FLAC", "OGG"])
        self.sr_combo = QComboBox(); self.sr_combo.addItems(["24000", "44100", "48000"])
        dir_row = QHBoxLayout()
        self.output_dir = QLineEdit()
        self.output_dir.setPlaceholderText(str(paths.default_output_dir()))
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_output_dir)
        dir_row.addWidget(self.output_dir, 1)
        dir_row.addWidget(browse_btn)
        of.addRow("Format:", self.format_combo)
        of.addRow("Sample rate:", self.sr_combo)
        of.addRow("Output directory:", dir_row)
        root.addWidget(out_group)

        # Normalization
        norm_group = QGroupBox("Normalization")
        nf = QFormLayout(norm_group)
        self.normalize_combo = QComboBox()
        self.normalize_combo.addItems(["Off", "Peak", "LUFS"])
        self.peak_target = QDoubleSpinBox(); self.peak_target.setRange(-12.0, 0.0); self.peak_target.setSuffix(" dBFS")
        self.lufs_target = QDoubleSpinBox(); self.lufs_target.setRange(-40.0, -5.0); self.lufs_target.setSuffix(" LUFS")
        nf.addRow("Mode:", self.normalize_combo)
        nf.addRow("Peak target:", self.peak_target)
        nf.addRow("LUFS target:", self.lufs_target)
        root.addWidget(norm_group)

        # Model / device / appearance
        misc_group = QGroupBox("Model & Appearance")
        mf = QFormLayout(misc_group)
        self.model_repo = QLineEdit()
        self.device_combo = QComboBox()
        self.device_combo.addItems(["auto", "cpu", "mps"])
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["dark", "light", "system"])
        self.log_combo = QComboBox()
        self.log_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        mf.addRow("Model repo:", self.model_repo)
        mf.addRow("Device:", self.device_combo)
        mf.addRow("Theme:", self.theme_combo)
        mf.addRow("Log level:", self.log_combo)
        root.addWidget(misc_group)

        # Buttons
        btns = QHBoxLayout()
        self.save_btn = QPushButton("💾 Save Changes")
        self.save_btn.setObjectName("primaryButton")
        self.defaults_btn = QPushButton("Restore Defaults")
        btns.addStretch(1)
        btns.addWidget(self.defaults_btn)
        btns.addWidget(self.save_btn)
        root.addLayout(btns)
        root.addStretch(1)

        self.save_btn.clicked.connect(self._save)
        self.defaults_btn.clicked.connect(self._restore_defaults)

        self.load_settings(settings)

    # -- load / save ----------------------------------------------------------

    def load_settings(self, settings: Settings) -> None:
        self._settings = settings
        self._set_combo_by_data(self.voice_a, settings.default_voice_a)
        self._set_combo_by_data(self.voice_b, settings.default_voice_b)
        self.speed_a.setValue(settings.default_speed_a)
        self.speed_b.setValue(settings.default_speed_b)
        self.format_combo.setCurrentText(settings.output_format.upper())
        self.sr_combo.setCurrentText(str(settings.sample_rate))
        self.output_dir.setText(settings.output_dir)
        self.normalize_combo.setCurrentText(settings.normalize.capitalize())
        self.peak_target.setValue(settings.peak_target_db)
        self.lufs_target.setValue(settings.lufs_target)
        self.model_repo.setText(settings.model_repo_id)
        self.device_combo.setCurrentText(settings.device)
        self.theme_combo.setCurrentText(settings.theme)
        self.log_combo.setCurrentText(settings.log_level.upper())

    def build_settings(self) -> Settings:
        s = Settings()
        s.default_voice_a = self.voice_a.currentData() or s.default_voice_a
        s.default_voice_b = self.voice_b.currentData() or s.default_voice_b
        s.default_speed_a = self.speed_a.value()
        s.default_speed_b = self.speed_b.value()
        s.output_format = self.format_combo.currentText()
        s.sample_rate = int(self.sr_combo.currentText())
        s.output_dir = self.output_dir.text().strip()
        s.normalize = self.normalize_combo.currentText().lower()
        s.peak_target_db = self.peak_target.value()
        s.lufs_target = self.lufs_target.value()
        s.model_repo_id = self.model_repo.text().strip() or "hexgrad/Kokoro-82M"
        s.device = self.device_combo.currentText()
        s.theme = self.theme_combo.currentText()
        s.log_level = self.log_combo.currentText()
        s.pause_between_lines = self._settings.pause_between_lines
        s.pause_between_speakers = self._settings.pause_between_speakers
        return s

    def _save(self) -> None:
        from ..utils.config import save_settings
        s = self.build_settings()
        save_settings(s)
        self.theme_changed.emit(s.theme)
        self.settings_saved.emit(s)
        self.status_message.emit("Settings saved")  # type: ignore[attr-defined]

    def _restore_defaults(self) -> None:
        self.load_settings(Settings())

    def _browse_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose output directory",
                                                  self.output_dir.text() or str(Path.home()))
        if folder:
            self.output_dir.setText(folder)

    def _set_combo_by_data(self, combo: QComboBox, data_value: str) -> None:
        idx = combo.findData(data_value)
        combo.setCurrentIndex(max(0, idx))
        if idx < 0:
            # fall back to first
            combo.setCurrentIndex(0)
