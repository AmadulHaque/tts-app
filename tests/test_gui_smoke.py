"""Offscreen GUI smoke test: the main window and all five tabs construct.

The engine loader is stubbed so no torch/model download happens in tests.
"""

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


def _patch_engine_loader(monkeypatch):
    """Prevent the real EngineLoader from touching torch/downloads."""
    from app.core import batch_runner as br
    import types

    def run(self):
        self.ready.emit(True, "cpu-test")

    monkeypatch.setattr(br.EngineLoader, "run", run)


@pytest.fixture
def window(qapp, monkeypatch):
    """A MainWindow that is always closed (a window left running aborts
    teardown: its engine QThread would be destroyed while still in exec)."""
    _patch_engine_loader(monkeypatch)
    from app.ui.main_window import MainWindow
    from app.utils.config import Settings

    win = MainWindow(Settings())
    win.show()  # offscreen: makes isVisible() meaningful, renders nothing
    yield win
    win.close()


def test_main_window_constructs(window):
    assert window.tabs.count() == 5
    assert window.editor.table is not None
    assert window.library is not None
    assert window.batch_tab is not None
    assert window.settings_tab is not None
    assert window.about is not None

    # Undo stack + line ops round-trip through the table.
    window.editor.add_line()
    window.editor.project.lines[0].text = "Hello world"
    assert len(window.editor.project.lines) == 1
    window.editor.undo_stack.undo()
    assert len(window.editor.project.lines) == 0
    window.editor.undo_stack.redo()
    assert len(window.editor.project.lines) == 1


def test_voice_panel_defaults(window):
    a, b = window.editor.voice_panel.profiles()
    assert a.voice_id == "am_michael"
    assert b.voice_id == "af_heart"


def test_voice_library_grid(window):
    assert len(window.library._cards) == 28
    window.tabs.setCurrentWidget(window.library)  # stacked pages hide non-current tabs
    window.library.gender_combo.setCurrentText("Female")
    visible = [c for c in window.library._cards.values() if c.isVisible()]
    assert len(visible) == 15
