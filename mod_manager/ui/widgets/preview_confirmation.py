from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..theme import tokens
from .style_utils import apply_margins


class PreviewConfirmationContent(QtWidgets.QWidget):
    def __init__(self, source: Path, count: int, clipboard: bool, parent=None):
        super().__init__(parent)
        layout = apply_margins(QtWidgets.QVBoxLayout(self), spacing=tokens.SPACE_2XL)
        if clipboard:
            text = "Use the image from the clipboard as the preview?"
        else:
            text = "Apply this preview image?"
        if count > 1:
            text += f"\nThe same image will be applied to all {count} selected mods, replacing their existing previews."
        else:
            text += "\nThe selected mod's existing preview will be replaced."
        self.message = QtWidgets.QLabel(text, self)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.preview = QtWidgets.QLabel(self)
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setFixedHeight(tokens.PREVIEW_CONFIRM_IMAGE_SIZE)
        reader = QtGui.QImageReader(str(source))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            size.scale(tokens.PREVIEW_CONFIRM_IMAGE_SIZE, tokens.PREVIEW_CONFIRM_IMAGE_SIZE, QtCore.Qt.KeepAspectRatio)
            reader.setScaledSize(size)
        self.preview.setPixmap(QtGui.QPixmap.fromImage(reader.read()))
        self.preview.setAccessibleName("Preview image to apply")
        layout.addWidget(self.preview)
