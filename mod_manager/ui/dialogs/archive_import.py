from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ..theme import tokens
from ..widgets.archive_browser import ArchiveBrowser
from ..widgets.style_utils import apply_margins
from ..widgets.toolbar import IconToolbar


class ArchiveImportDialog(QtWidgets.QDialog):
    importRequested = QtCore.Signal()
    pasteRequested = QtCore.Signal()
    dropRequested = QtCore.Signal(object)
    closing = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import mods from archives")
        self.resize(*tokens.ARCHIVE_DIALOG_SIZE)
        self.setAcceptDrops(True)
        self.working = False
        self.browser = ArchiveBrowser(self)
        self.status = QtWidgets.QLabel("Select files to import. Paste or drop an image to assign a preview.", self)
        self.status.setWordWrap(True)
        self.actions = IconToolbar(self)
        section = self.actions.add_section("import", "Import")
        section.add_text_action("import", "Add", "import", "Import the selected mods from all archives", self.importRequested.emit)
        section.add_text_action("cancel", "Cancel", "remove", "Cancel without importing", self.reject)
        self.actions.add_stretch()
        for button in self.findChildren(QtWidgets.QPushButton):
            button.setAutoDefault(False)
        self.actions.button("import").setDefault(True)
        layout = apply_margins(QtWidgets.QVBoxLayout(self), margins=tokens.DETAIL_MARGIN, spacing=tokens.SPACE_LG)
        layout.addWidget(self.browser, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.actions)
        QtGui.QShortcut(QtGui.QKeySequence.Paste, self, activated=self.pasteRequested.emit)
        self.browser.model.dataChanged.connect(self.update_import_enabled)
        self.browser.model.modelReset.connect(self.update_import_enabled)

    def update_import_enabled(self, *_args) -> None:
        selected = any(archive.mode == "together" or archive.selected for archive in self.browser.archives)
        self.actions.set_enabled("import", bool(selected) and not self.working)

    def set_working(self, working: bool) -> None:
        self.working = working
        self.browser.setEnabled(not working)
        self.actions.set_enabled("cancel", not working)
        self.update_import_enabled()

    def reject(self) -> None:
        if not self.working:
            self.closing.emit()
            super().reject()

    def accept(self) -> None:
        if not self.working:
            self.closing.emit()
            super().accept()

    def closeEvent(self, event) -> None:
        if self.working:
            event.ignore()
        else:
            self.closing.emit()
            super().closeEvent(event)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self.dropRequested.emit(event.mimeData())
        event.acceptProposedAction()
