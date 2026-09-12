"""Busy (loading) state for buttons: disable + animated dots while async
work runs. Always pair ``set_busy`` with ``clear_busy``."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QPushButton

_ORIG_TEXT = "busyOrigText"
_TIMER = "busyTimer"


class BusyAnimator(QTimer):
    """Cycles trailing dots on a button label while work is in flight."""

    def __init__(self, btn: QPushButton, label: str):
        super().__init__(btn)
        self._btn = btn
        self._label = label.rstrip(" .…")
        self._dots = 0
        self.setInterval(400)
        self.timeout.connect(self._tick)

    def _tick(self) -> None:
        self._dots = (self._dots + 1) % 4
        self._btn.setText(f"{self._label}{'.' * self._dots}")


def set_busy(btn: QPushButton, busy_text: str | None = None) -> None:
    if btn.property(_ORIG_TEXT) is not None:
        return
    label = busy_text if busy_text is not None else btn.text()
    btn.setProperty(_ORIG_TEXT, btn.text())
    animator = BusyAnimator(btn, label)
    btn.setProperty(_TIMER, animator)
    btn.setEnabled(False)
    btn.setText(label)
    animator.start()


def clear_busy(btn: QPushButton) -> None:
    animator = btn.property(_TIMER)
    if animator is not None:
        animator.stop()
        animator.deleteLater()
        btn.setProperty(_TIMER, None)
    orig = btn.property(_ORIG_TEXT)
    btn.setProperty(_ORIG_TEXT, None)
    if isinstance(orig, str):
        btn.setText(orig)
    btn.setEnabled(True)
