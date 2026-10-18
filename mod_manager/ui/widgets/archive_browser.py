from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ...imports import PreparedArchive
from ...settings_schema import label_for, spec_for
from ..models.archive_model import ArchiveModModel
from ..theme import tokens
from .archive_selector import ArchiveSelector
from .style_utils import apply_margins
from .toolbar import IconToolbar


class ArchiveBrowser(QtWidgets.QWidget):
    archiveChanged = QtCore.Signal(int)
    imageRequested = QtCore.Signal(object, int)
    pathsDropped = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.archives: list[PreparedArchive] = []
        self.selector = ArchiveSelector(self)
        self.selector_model = self.selector.model()
        self.selector.selectionModel().currentChanged.connect(self._switch_archive)
        self.filename = QtWidgets.QLabel(self)
        self.filename.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.filename.setWordWrap(True)
        self.together = QtWidgets.QCheckBox("Add files together", self)
        self.together.setToolTip(spec_for("archive_import_mode").tooltip)
        self.preserve = QtWidgets.QCheckBox(label_for("archive_preserve_structure"), self)
        self.preserve.setToolTip(spec_for("archive_preserve_structure").tooltip)
        self.together.toggled.connect(self._mode_changed)
        self.preserve.toggled.connect(self._preserve_changed)
        self.model = ArchiveModModel(self)
        self.table = QtWidgets.QTableView(self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, tokens.ARCHIVE_CHECK_COLUMN_WIDTH)
        self.table.setColumnWidth(1, tokens.ARCHIVE_NAME_COLUMN_WIDTH)
        self.table.selectionModel().currentChanged.connect(self.update_preview)
        self.table.setAcceptDrops(True)
        self.table.viewport().setAcceptDrops(True)
        self.table.viewport().installEventFilter(self)
        self.preview = QtWidgets.QLabel("Select a mod to assign a preview", self)
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setWordWrap(True)
        self.preview.setFixedSize(tokens.ARCHIVE_PREVIEW_SIZE, tokens.ARCHIVE_PREVIEW_SIZE)
        self.toolbar = IconToolbar(self)
        selection = self.toolbar.add_section("selection", "Selection")
        selection.add_text_action("select_all", "Select all", "add", "Select every mod", lambda: self.model.select_all(True))
        selection.add_text_action("select_none", "Select none", "clear", "Clear the mod selection", lambda: self.model.select_all(False))
        artwork = self.toolbar.add_section("preview", "Preview")
        artwork.add_action("clear_image", "clear", "Clear the selected mod preview", self.clear_preview)
        self.toolbar.add_stretch()
        options = apply_margins(QtWidgets.QHBoxLayout(), spacing=tokens.SPACE_LG)
        options.addWidget(self.together)
        options.addWidget(self.preserve)
        options.addStretch()
        content = apply_margins(QtWidgets.QHBoxLayout(), spacing=tokens.SPACE_LG)
        content.addWidget(self.table, 1)
        content.addWidget(self.preview)
        layout = apply_margins(QtWidgets.QVBoxLayout(self), spacing=tokens.SPACE_LG)
        layout.addWidget(self.selector)
        layout.addWidget(self.filename)
        layout.addLayout(options)
        layout.addWidget(self.toolbar)
        layout.addLayout(content, 1)

    @property
    def archive(self) -> PreparedArchive | None:
        index = self.selector.currentIndex().row()
        return self.archives[index] if 0 <= index < len(self.archives) else None

    @property
    def selected_row(self) -> int:
        return self.table.currentIndex().row()

    def set_archives(self, archives: list[PreparedArchive]) -> None:
        current = max(0, self.selector.currentIndex().row())
        previous = self.archive
        self.archives = archives
        with QtCore.QSignalBlocker(self.selector.selectionModel()):
            self.selector.set_names([archive.source_name or archive.name for archive in archives])
            if archives:
                self.selector.setCurrentIndex(self.selector_model.index(min(current, len(archives) - 1)))
        self.filename.setVisible(len(archives) == 1)
        if self.archive is not previous:
            self._switch_archive(self.selector.currentIndex(), QtCore.QModelIndex())

    def _switch_archive(self, current, _previous) -> None:
        archive = self.archive
        self.model.set_archive(archive)
        if archive is None:
            return
        self.filename.setText(archive.source_name or archive.name)
        self.together.blockSignals(True)
        self.preserve.blockSignals(True)
        self.together.setChecked(archive.mode == "together")
        self.preserve.setChecked(archive.preserve_structure)
        self.together.blockSignals(False)
        self.preserve.blockSignals(False)
        self._update_actions()
        self.update_preview()
        self.archiveChanged.emit(current.row())

    def _update_actions(self) -> None:
        separate = self.archive is not None and self.archive.mode == "separate"
        for key in ("select_all", "select_none", "clear_image"):
            self.toolbar.set_enabled(key, separate)

    def _mode_changed(self, together: bool) -> None:
        if self.archive is not None:
            self.archive.mode = "together" if together else "separate"
            self.model.set_archive(self.archive)
            self._update_actions()
            self.update_preview()

    def _preserve_changed(self, preserve: bool) -> None:
        if self.archive is not None:
            self.archive.preserve_structure = preserve

    def update_preview(self, *_args) -> None:
        archive = self.archive
        path = archive.images.get(self.selected_row) if archive and archive.mode == "separate" else None
        pixmap = QtGui.QPixmap(str(path)) if path else QtGui.QPixmap()
        self.preview.clear()
        if pixmap.isNull():
            self.preview.setText("Select a mod to assign a preview" if archive and archive.mode == "separate" else "Files will be added together")
        else:
            self.preview.setPixmap(pixmap.scaled(self.preview.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def clear_preview(self) -> None:
        if self.archive is not None:
            row = self.selected_row
            self.archive.images.pop(row, None)
            self.model.dataChanged.emit(self.model.index(row, 1), self.model.index(row, 1))
            self.update_preview()

    def eventFilter(self, source, event):
        if source is self.table.viewport():
            if event.type() in (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove):
                if event.mimeData().hasUrls() or event.mimeData().hasImage():
                    event.acceptProposedAction()
                    return True
            if event.type() == QtCore.QEvent.Drop:
                index = self.table.indexAt(event.position().toPoint())
                if index.isValid():
                    self.table.setCurrentIndex(index)
                self.imageRequested.emit(event.mimeData(), index.row())
                event.acceptProposedAction()
                return True
        return super().eventFilter(source, event)
