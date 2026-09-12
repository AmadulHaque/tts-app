"""QUndoCommand subclasses for the dialogue editor.

Commands are thin: each knows a row index and the operation to redo/undo, and
delegates to the editor's ``apply_op`` dispatcher so undo logic lives in one
place. ``EditLineCommand`` must be passed the *previous* DialogueLine object."""

from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QUndoCommand

from ..models.dialogue import DialogueLine

ApplyCb = Callable[..., None]


class AddLineCommand(QUndoCommand):
    def __init__(self, apply_cb: ApplyCb, row: int, line: DialogueLine):
        super().__init__(f"Add line {row + 1}")
        self.apply = apply_cb
        self.row = row
        self.line = line

    def redo(self) -> None:
        self.apply("add", self.row, self.line)

    def undo(self) -> None:
        self.apply("remove", self.row, self.line)


class RemoveLineCommand(QUndoCommand):
    def __init__(self, apply_cb: ApplyCb, row: int, line: DialogueLine):
        super().__init__("Delete line")
        self.apply = apply_cb
        self.row = row
        self.line = line

    def redo(self) -> None:
        self.apply("remove", self.row, self.line)

    def undo(self) -> None:
        self.apply("add", self.row, self.line)


class MoveLineCommand(QUndoCommand):
    def __init__(self, apply_cb: ApplyCb, src: int, dst: int):
        super().__init__("Move line")
        self.apply = apply_cb
        self.src = src
        self.dst = dst

    def redo(self) -> None:
        self.apply("move", self.src, self.dst)

    def undo(self) -> None:
        self.apply("move", self.dst, self.src)


class EditLineCommand(QUndoCommand):
    def __init__(self, apply_cb: ApplyCb, row: int, old_line: DialogueLine, new_line: DialogueLine,
                 label: str = "Edit line"):
        super().__init__(label)
        self.apply = apply_cb
        self.row = row
        self.old = old_line
        self.new = new_line

    def redo(self) -> None:
        self.apply("edit", self.row, self.new)

    def undo(self) -> None:
        self.apply("edit", self.row, self.old)


class DuplicateLineCommand(QUndoCommand):
    def __init__(self, apply_cb: ApplyCb, row: int, line: DialogueLine):
        super().__init__("Duplicate line")
        self.apply = apply_cb
        self.row = row
        self.line = line

    def redo(self) -> None:
        self.apply("add", self.row + 1, self.line)

    def undo(self) -> None:
        self.apply("remove", self.row + 1, self.line)


class SetLinesCommand(QUndoCommand):
    """Replace the whole line list (import / load)."""

    def __init__(self, apply_cb: ApplyCb, before: list[DialogueLine], after: list[DialogueLine]):
        super().__init__("Import lines")
        self.apply = apply_cb
        self.before = list(before)
        self.after = list(after)

    def redo(self) -> None:
        self.apply("set_all", 0, self.after)

    def undo(self) -> None:
        self.apply("set_all", 0, self.before)
