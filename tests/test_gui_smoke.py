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


@pytest.fixture
def window(qapp, monkeypatch):
    from app.ui import main_window as mw
    monkeypatch.setattr(mw.EngineLoader, "run",
                        lambda self: self.ready.emit(True, "CPU-TEST"))
    win = mw.MainWindow()
    yield win
    win.close()


def test_window_constructs(window):
    assert window.voice_combo.count() == 28
    assert window.voice_combo.currentData()  # a real voice id
    assert window.text_edit.toPlainText() == ""
    assert window.generate_btn.isEnabled()
    assert not window.play_btn.isEnabled()
    assert not window.save_btn.isEnabled()


def test_empty_text_click_shows_hint(window):
    window.generate_btn.click()
    assert "Type some text" in window._status.text()
    assert not window._status.text().startswith("Generating")


def test_stats_update(window):
    window.speed_spin.setValue(1.0)
    window.text_edit.setPlainText("one two three four five")
    assert "5 words" in window.stats_label.text()
    assert "5 chars" not in window.stats_label.text()  # len is 24 chars
