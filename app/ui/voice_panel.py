"""Voice panel: per-speaker voice/speed/pitch controls plus global audio
settings (pauses, format, sample rate). Shared by the dialogue editor."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from ..models.dialogue import SpeakerProfile
from ..models.voice import VOICE_CATALOG, voice_info
from .widgets.busy import clear_busy, set_busy

VOICE_ROLE = Qt.ItemDataRole.UserRole


def populate_voice_combo(combo: QComboBox) -> None:
    """Flat voice list grouped by accent with separators.

    A tree model does not work in a QComboBox (count() only sees top-level
    rows, so real voices were unreachable and defaults silently fell back).
    Voice ids are stored as item user-data under VOICE_ROLE.
    """
    for accent in ("US", "UK"):
        if combo.count():
            combo.insertSeparator(combo.count())
        for info in sorted(VOICE_CATALOG.values(), key=lambda v: v.name):
            if info.accent != accent:
                continue
            combo.addItem(f"{info.name} ({info.voice_id})  ·  {info.grade}", info.voice_id)


class SpeakerVoicePane(QGroupBox):
    preview_requested = Signal(str)      # speaker name

    def __init__(self, title: str, speaker: SpeakerProfile, parent: QWidget | None = None):
        super().__init__(title, parent)
        self._speaker = speaker
        self._updating = False

        form = QFormLayout(self)

        self.name_edit = QLineEdit(speaker.name)
        self.name_edit.setPlaceholderText("Speaker name")
        self.name_edit.setToolTip("Name shown in the dialogue (also used in subtitles).")
        form.addRow("Name:", self.name_edit)

        self.voice_combo = QComboBox()
        populate_voice_combo(self.voice_combo)
        form.addRow("Voice:", self.voice_combo)

        # Speed 0.5 .. 1.5
        speed_box = QWidget()
        speed_layout = QHBoxLayout(speed_box)
        speed_layout.setContentsMargins(0, 0, 0, 0)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(50, 150)
        self.speed_slider.setSingleStep(1)
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.5, 1.5)
        self.speed_spin.setSingleStep(0.05)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setFixedWidth(64)
        speed_layout.addWidget(self.speed_slider, 1)
        speed_layout.addWidget(self.speed_spin)
        form.addRow("Speed:", speed_box)

        # Pitch -2 .. +2 semitones
        pitch_box = QWidget()
        pitch_layout = QHBoxLayout(pitch_box)
        pitch_layout.setContentsMargins(0, 0, 0, 0)
        self.pitch_slider = QSlider(Qt.Orientation.Horizontal)
        self.pitch_slider.setRange(-20, 20)
        self.pitch_slider.setSingleStep(1)
        self.pitch_spin = QDoubleSpinBox()
        self.pitch_spin.setRange(-2.0, 2.0)
        self.pitch_spin.setSingleStep(0.1)
        self.pitch_spin.setDecimals(1)
        self.pitch_spin.setFixedWidth(64)
        pitch_layout.addWidget(self.pitch_slider, 1)
        pitch_layout.addWidget(self.pitch_spin)
        form.addRow("Pitch:", pitch_box)

        self.preview_btn = QPushButton("🔊 Preview")
        form.addRow(self.preview_btn)

        # ---- wiring ----
        self.speed_slider.valueChanged.connect(self._on_speed_slider)
        self.speed_spin.valueChanged.connect(self._on_speed_spin)
        self.pitch_slider.valueChanged.connect(self._on_pitch_slider)
        self.pitch_spin.valueChanged.connect(self._on_pitch_spin)
        self.voice_combo.currentIndexChanged.connect(lambda _i: self._changed())
        self.preview_btn.clicked.connect(lambda: self.preview_requested.emit(self.name_edit.text().strip() or self._speaker.name))

        self.set_profile(speaker)

    # -- state ------------------------------------------------------------

    def set_profile(self, speaker: SpeakerProfile) -> None:
        self._speaker = speaker
        self._updating = True
        self.name_edit.blockSignals(True)
        self.name_edit.setText(speaker.name)
        self._set_voice(speaker.voice_id)
        self.speed_spin.setValue(speaker.speed)
        self.speed_slider.setValue(round(speaker.speed * 100))
        self.pitch_spin.setValue(speaker.pitch)
        self.pitch_slider.setValue(round(speaker.pitch * 10))
        self._updating = False

    def profile(self) -> SpeakerProfile:
        return SpeakerProfile(
            name=self.name_edit.text().strip() or self._speaker.name,
            voice_id=self.voice_id(),
            speed=float(self.speed_spin.value()),
            pitch=float(self.pitch_spin.value()),
        )

    def voice_id(self) -> str:
        data = self.voice_combo.currentData(VOICE_ROLE)
        return data if data else "af_heart"

    def speaker_name(self) -> str:
        return self.name_edit.text().strip() or self._speaker.name

    def set_preview_busy(self, busy: bool) -> None:
        if busy:
            set_busy(self.preview_btn, "⏳ Previewing")
        else:
            clear_busy(self.preview_btn)

    # -- internals --------------------------------------------------------

    def _set_voice(self, voice_id: str) -> None:
        vid = voice_info(voice_id).voice_id if voice_info(voice_id) else voice_id
        idx = self.voice_combo.findData(vid, VOICE_ROLE)
        if idx < 0:  # unknown id or separator hit: fall back to first real voice
            idx = self.voice_combo.findData("af_heart", VOICE_ROLE)
        self.voice_combo.setCurrentIndex(max(0, idx))

    def _on_speed_slider(self, v: int) -> None:
        if not self._updating:
            self.speed_spin.setValue(v / 100.0)

    def _on_speed_spin(self, v: float) -> None:
        if not self._updating:
            self.speed_slider.setValue(round(v * 100))
            self._changed()

    def _on_pitch_slider(self, v: int) -> None:
        if not self._updating:
            self.pitch_spin.setValue(v / 10.0)

    def _on_pitch_spin(self, v: float) -> None:
        if not self._updating:
            self.pitch_slider.setValue(round(v * 10))
            self._changed()

    def _changed(self) -> None:
        pass  # subclasses/panel connect to a changed signal via profile edits


class VoicePanel(QWidget):
    """Two speaker panes + global audio settings."""

    preview_requested = Signal(str)          # speaker panel name
    changed = Signal()                       # any audio-affecting setting changed
    speakers_renamed = Signal()              # a speaker name changed

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.pane_a = SpeakerVoicePane("Speaker A", SpeakerProfile("Speaker A", "am_michael"))
        self.pane_b = SpeakerVoicePane("Speaker B", SpeakerProfile("Speaker B", "af_heart"))
        layout.addWidget(self.pane_a)
        layout.addWidget(self.pane_b)

        # Global settings
        self.global_group = QGroupBox("Global Settings")
        gform = QFormLayout(self.global_group)
        self.pause_lines = QDoubleSpinBox()
        self.pause_lines.setRange(0.0, 5.0)
        self.pause_lines.setSingleStep(0.1)
        self.pause_lines.setDecimals(2)
        self.pause_lines.setSuffix(" s")
        self.pause_speakers = QDoubleSpinBox()
        self.pause_speakers.setRange(0.0, 5.0)
        self.pause_speakers.setSingleStep(0.1)
        self.pause_speakers.setDecimals(2)
        self.pause_speakers.setSuffix(" s")
        gform.addRow("Pause between lines:", self.pause_lines)
        gform.addRow("Pause between speakers:", self.pause_speakers)

        self.format_combo = QComboBox()
        self.format_combo.addItems(["WAV", "MP3", "FLAC", "OGG"])
        gform.addRow("Output format:", self.format_combo)

        self.sr_combo = QComboBox()
        self.sr_combo.addItems(["24000", "44100", "48000"])
        gform.addRow("Sample rate:", self.sr_combo)

        layout.addWidget(self.global_group)
        layout.addStretch(1)

        # Wiring
        self.pane_a.preview_requested.connect(self.preview_requested)
        self.pane_b.preview_requested.connect(self.preview_requested)
        self.pane_a.name_edit.editingFinished.connect(self._name_changed)
        self.pane_b.name_edit.editingFinished.connect(self._name_changed)

        for w in (self.pause_lines, self.pause_speakers,
                  self.pane_a.speed_spin, self.pane_b.speed_spin,
                  self.pane_a.speed_slider, self.pane_b.speed_slider,
                  self.pane_a.pitch_spin, self.pane_b.pitch_spin,
                  self.pane_a.pitch_slider, self.pane_b.pitch_slider):
            w.valueChanged.connect(self._changed)
        for c in (self.format_combo, self.sr_combo,
                  self.pane_a.voice_combo, self.pane_b.voice_combo):
            c.currentIndexChanged.connect(self._changed)

    def _name_changed(self) -> None:
        self.speakers_renamed.emit()
        self.changed.emit()

    def _changed(self, *_args) -> None:
        self.changed.emit()

    # -- project sync -----------------------------------------------------

    def set_profiles(self, speaker_a: SpeakerProfile, speaker_b: SpeakerProfile) -> None:
        self.pane_a.set_profile(speaker_a)
        self.pane_b.set_profile(speaker_b)

    def set_preview_busy(self, busy: bool) -> None:
        self.pane_a.set_preview_busy(busy)
        self.pane_b.set_preview_busy(busy)

    def profiles(self) -> tuple[SpeakerProfile, SpeakerProfile]:
        return self.pane_a.profile(), self.pane_b.profile()

    def set_audio_settings(self, pause_lines: float, pause_speakers: float,
                          output_format: str, sample_rate: int) -> None:
        self.pause_lines.setValue(pause_lines)
        self.pause_speakers.setValue(pause_speakers)
        idx = self.format_combo.findText(output_format.upper())
        self.format_combo.setCurrentIndex(max(0, idx))
        idx = self.sr_combo.findText(str(sample_rate))
        self.sr_combo.setCurrentIndex(max(0, idx))

    def audio_settings(self) -> tuple[float, float, str, int]:
        return (self.pause_lines.value(), self.pause_speakers.value(),
                self.format_combo.currentText(), int(self.sr_combo.currentText()))
