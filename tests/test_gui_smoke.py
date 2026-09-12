"""Offscreen smoke test: the simple TTS window constructs and is wired."""

import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_window_constructs(qapp):
    from app.ui.main_window import MainWindow

    win = MainWindow()
    assert win.voice_combo.count() == 28
    assert win.voice_combo.currentData()  # a real voice id
    assert win.text_edit.toPlainText() == ""
    assert win.generate_btn.isEnabled()
    win.close()


def test_empty_text_click_shows_hint(qapp):
    from app.ui.main_window import MainWindow

    win = MainWindow()
    win.generate_btn.click()
    assert "Type some text" in win._status.text()
    assert not win._status.text().startswith("Generating")
    win.close()
