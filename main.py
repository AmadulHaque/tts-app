#!/usr/bin/env python3
"""Kokoro Studio entry point.

Sets up the MPS fallback env var BEFORE any torch/kokoro import so the model
can use Apple Silicon GPU acceleration, then boots the Qt application.
"""

import os
import sys

# Ensure the project root is importable when launched as a script.
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Kokoro's KPipeline only enables MPS when this fallback flag is set — it must
# be set before torch is imported (which happens when the engine initializes).
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
os.environ.setdefault("PYTORCH_MPS_HIGH_WATERMARK_RATIO", "0.0")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.utils.config import load_settings


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Kokoro Studio")
    app.setOrganizationName("Kokoro Studio")
    app.setQuitOnLastWindowClosed(True)

    window = MainWindow(load_settings())
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
