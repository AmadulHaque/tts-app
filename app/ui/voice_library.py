"""Tab 2 — Voice Library.

Grid of the 28 English Kokoro voices with gender/accent/grade filtering,
preview, favourites and named presets. Requires the model to be initialized
(the main window wires the preview signal)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from ..models.voice import VOICE_CATALOG, VoiceInfo, voice_info
from ..utils import config as cfg


class VoiceCard(QFrame):
    preview_requested = Signal(str)           # voice_id
    favorite_toggled = Signal(str, bool)       # voice_id, is_favorite
    set_default_requested = Signal(str, str)  # voice_id, "A"|"B"

    def __init__(self, info: VoiceInfo, favorite: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.voice_id = info.voice_id
        self.setObjectName("voiceCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(2)

        top = QHBoxLayout()
        title = QLabel(f"<b>{info.name}</b>  <span style='color:#888'>{info.voice_id}</span>")
        title.setTextFormat(Qt.TextFormat.RichText)
        self.star_btn = QPushButton("★" if favorite else "☆")
        self.star_btn.setObjectName("starButton")
        self.star_btn.setFixedWidth(30)
        self.star_btn.setToolTip("Add/remove favourite")
        self.star_btn.setCheckable(True)
        self.star_btn.setChecked(favorite)
        top.addWidget(title, 1)
        top.addWidget(self.star_btn, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(top)

        meta = f"{'Male' if info.gender == 'male' else 'Female'} · {info.accent} · grade {info.grade}"
        v.addWidget(QLabel(meta))
        desc = QLabel(info.description)
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#8a8a8a; font-size:11px;")
        v.addWidget(desc)

        btns = QHBoxLayout()
        self.preview_btn = QPushButton("🔊 Preview")
        self.preview_btn.setMinimumHeight(26)
        btns.addWidget(self.preview_btn)
        v.addLayout(btns)

        self.star_btn.clicked.connect(self._on_star)

    def _on_star(self, checked: bool) -> None:
        self.star_btn.setText("★" if checked else "☆")
        self.favorite_toggled.emit(self.voice_id, checked)

    def card_context_menu(self, pos) -> None:
        menu = QMenu(self)
        set_a = menu.addAction("Set as Speaker A voice")
        set_b = menu.addAction("Set as Speaker B voice")
        action = menu.exec(self.mapToGlobal(pos))
        if action == set_a:
            self.set_default_requested.emit(self.voice_id, "A")
        elif action == set_b:
            self.set_default_requested.emit(self.voice_id, "B")


class VoiceLibraryTab(QWidget):
    preview_requested = Signal(str)
    set_default_requested = Signal(str, str)
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._favorites = set(cfg.load_favorites())
        self._presets = dict(cfg.load_voice_presets())
        self._cards: dict[str, VoiceCard] = {}

        root = QVBoxLayout(self)

        # Toolbar / filters
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Gender:"))
        self.gender_combo = QComboBox()
        self.gender_combo.addItems(["All", "Female", "Male"])
        bar.addWidget(self.gender_combo)
        bar.addWidget(QLabel("Accent:"))
        self.accent_combo = QComboBox()
        self.accent_combo.addItems(["All", "US", "UK"])
        bar.addWidget(self.accent_combo)
        bar.addWidget(QLabel("Quality:"))
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["All", "A/A-", "B/B-", "C/C-", "D/D-", "F/F+"])
        bar.addWidget(self.quality_combo)
        bar.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("voice id or name…")
        self.search_edit.setClearButtonEnabled(True)
        bar.addWidget(self.search_edit, 1)
        bar.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(140)
        bar.addWidget(self.preset_combo)
        self.preset_btn = QPushButton("Save preset…")
        self.del_preset_btn = QPushButton("Delete")
        bar.addWidget(self.preset_btn)
        bar.addWidget(self.del_preset_btn)
        root.addLayout(bar)

        # Scrollable grid
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._grid_host)
        root.addWidget(scroll, 1)

        # Wiring
        for w in (self.gender_combo, self.accent_combo, self.quality_combo):
            w.currentIndexChanged.connect(self._apply_filters)
        self.search_edit.textChanged.connect(lambda _t: self._apply_filters())
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        self.preset_btn.clicked.connect(self._save_preset)
        self.del_preset_btn.clicked.connect(self._delete_preset)

        self._rebuild()
        self._reload_presets()
        self._apply_filters()

    # -- grid -------------------------------------------------------------

    def _rebuild(self) -> None:
        # Clear previous
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._cards.clear()
        for i, info in enumerate(sorted(VOICE_CATALOG.values(), key=lambda v: v.name)):
            card = VoiceCard(info, favorite=info.voice_id in self._favorites, parent=self)
            card.preview_btn.clicked.connect(lambda _=False, vid=info.voice_id: self.preview_requested.emit(vid))
            card.favorite_toggled.connect(self._on_favorite)
            card.set_default_requested.connect(self.set_default_requested)
            card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            card.customContextMenuRequested.connect(card.card_context_menu)
            self._cards[info.voice_id] = card
            self._grid.addWidget(card, i // 4, i % 4)

    def _apply_filters(self) -> None:
        gender = self.gender_combo.currentText().lower()
        accent = self.accent_combo.currentText()
        quality = self.quality_combo.currentText()
        search = self.search_edit.text().strip().lower()

        def grade_bucket(g: str) -> str:
            for b in ("A/A-", "B/B-", "C/C-", "D/D-", "F/F+"):
                if g.upper().startswith(b[0]):
                    return b
            return "A/A-"

        for vid, card in self._cards.items():
            info = voice_info(vid)  # type: ignore[assignment]
            if info is None:
                card.setVisible(False)
                continue
            show = True
            if gender != "all" and info.gender != gender:
                show = False
            if accent != "All" and info.accent != accent:
                show = False
            if quality != "All" and grade_bucket(info.grade) != quality:
                show = False
            if search and search not in (vid + info.name).lower():
                show = False
            card.setVisible(show)

    # -- favourites --------------------------------------------------------

    def _on_favorite(self, voice_id: str, value: bool) -> None:
        if value:
            self._favorites.add(voice_id)
        else:
            self._favorites.discard(voice_id)
        cfg.save_favorites(sorted(self._favorites))
        self.status_message.emit(f"{voice_id} {'added to' if value else 'removed from'} favourites")

    def refresh_favorites(self) -> None:
        self._favorites = set(cfg.load_favorites())
        for vid, card in self._cards.items():
            card.star_btn.setChecked(vid in self._favorites)
            card.star_btn.setText("★" if vid in self._favorites else "☆")

    # -- presets ------------------------------------------------------------

    def _reload_presets(self) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("— choose a preset —")
        self.preset_combo.addItems(sorted(self._presets))
        self.preset_combo.blockSignals(False)

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Save voice preset", "Preset name:")
        if not ok or not name.strip():
            return
        voice_id, ok2 = QInputDialog.getItem(self, "Save voice preset", "Voice:",
                                             sorted(VOICE_CATALOG), 0, False)
        if not ok2:
            return
        self._presets[name.strip()] = {"voice_id": voice_id}
        cfg.save_voice_presets(self._presets)
        self._reload_presets()
        self.status_message.emit(f"Preset '{name.strip()}' saved")

    def _delete_preset(self) -> None:
        name = self.preset_combo.currentText()
        if name in self._presets:
            del self._presets[name]
            cfg.save_voice_presets(self._presets)
            self._reload_presets()
            self.status_message.emit(f"Preset '{name}' deleted")

    def _on_preset_selected(self, index: int) -> None:
        if self.preset_combo.currentText() in self._presets:
            voice_id = self._presets[self.preset_combo.currentText()]["voice_id"]
            self.preview_requested.emit(voice_id)
            self.status_message.emit(f"Preset uses {voice_id}")
