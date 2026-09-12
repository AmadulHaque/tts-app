"""Tab 5 — About."""

from __future__ import annotations

from .. import __version__
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class AboutTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        title = QLabel("<h1>🎙️ Kokoro Studio</h1>")
        title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title)

        version = QLabel(f"Version {__version__}")
        layout.addWidget(version)

        desc = QLabel(
            "A local, offline desktop app for generating podcast-style two-person "
            "English conversations with the <a href='https://huggingface.co/hexgrad/Kokoro-82M'>"
            "Kokoro-82M</a> TTS engine.\n\n"
            "Built with Python + PySide6 (Qt6). Runs on Apple Silicon (MPS acceleration) "
            "with CPU fallback for Intel Macs, Windows and Linux.\n\n"
            "No cloud dependencies — models and voices are downloaded once from "
            "Hugging Face and cached locally.")
        desc.setWordWrap(True)
        desc.setOpenExternalLinks(True)
        desc.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(desc)

        layout.addWidget(QLabel("<b>Credits</b>"))
        credits = QLabel(
            "• Kokoro TTS: <a href='https://github.com/hexgrad/kokoro'>hexgrad/kokoro</a> "
            "(Apache-2.0), weights by Kokoro team\n"
            "• G2P: <a href='https://github.com/hexgrad/misaki'>hexgrad/misaki</a>\n"
            "• GUI framework: Qt 6 / PySide6")
        credits.setWordWrap(True)
        credits.setOpenExternalLinks(True)
        credits.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(credits)

        usage = QLabel(
            "<b>Quick start</b><br>"
            "1. Open the <i>Dialogue Editor</i>, add lines and pick voices on the right.<br>"
            "2. Press <b>Ctrl+G</b> to generate the audio, <b>Space</b> to preview a line.<br>"
            "3. Use the <i>Batch Generator</i> to render many episodes at once.")
        usage.setWordWrap(True)
        usage.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(usage)

        license_label = QLabel(
            "<b>License</b><br>Kokoro Studio: Apache-2.0. Kokoro-82M weights: Apache-2.0.")
        license_label.setWordWrap(True)
        license_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(license_label)

        layout.addStretch(1)
