from __future__ import annotations

from pathlib import Path

from PySide6 import QtWidgets

from ..theme import tokens
from ..widgets.preview_confirmation import PreviewConfirmationContent
from ..widgets.style_utils import apply_margins


class PreviewConfirmationDialog(QtWidgets.QDialog):
    def __init__(self, parent, source: Path, count: int, clipboard: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Set preview image")
        self.setModal(True)
        self.choice = "cancel"
        layout = apply_margins(QtWidgets.QVBoxLayout(self), margins=tokens.DETAIL_MARGIN, spacing=tokens.SPACE_2XL)
        self.content = PreviewConfirmationContent(source, count, clipboard, self)
        layout.addWidget(self.content)
        self.buttons = QtWidgets.QDialogButtonBox(self)
        self.apply_button = self.buttons.addButton(
            "Use image" if clipboard else "Apply", QtWidgets.QDialogButtonBox.AcceptRole
        )
        self.apply_button.clicked.connect(self._apply)
        self.file_button = None
        if clipboard:
            self.file_button = self.buttons.addButton("Choose file...", QtWidgets.QDialogButtonBox.ActionRole)
            self.file_button.clicked.connect(self._choose_file)
        self.cancel_button = self.buttons.addButton(QtWidgets.QDialogButtonBox.Cancel)
        self.cancel_button.setDefault(True)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.resize(tokens.PREVIEW_CONFIRM_WIDTH, self.sizeHint().height())

    def _apply(self) -> None:
        self.choice = "apply"
        self.accept()

    def _choose_file(self) -> None:
        self.choice = "file"
        self.accept()
