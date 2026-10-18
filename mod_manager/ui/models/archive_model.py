from __future__ import annotations

from PySide6 import QtCore, QtGui

from ...imports import PreparedArchive


class ArchiveModModel(QtCore.QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.archive: PreparedArchive | None = None

    def set_archive(self, archive: PreparedArchive | None) -> None:
        self.beginResetModel()
        self.archive = archive
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() or self.archive is None else len(self.archive.units)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else 3

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if orientation == QtCore.Qt.Horizontal and role == QtCore.Qt.DisplayRole:
            return ("Add", "Mod", "Files in archive")[section]
        return None

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid() or self.archive is None:
            return None
        unit = self.archive.units[index.row()]
        if role == QtCore.Qt.DisplayRole:
            return ("", unit.name, ", ".join(path.as_posix() for path in unit.members))[index.column()]
        if role == QtCore.Qt.CheckStateRole and index.column() == 0:
            selected = self.archive.mode == "together" or index.row() in self.archive.selected
            return QtCore.Qt.Checked if selected else QtCore.Qt.Unchecked
        if role == QtCore.Qt.ToolTipRole:
            return "\n".join(path.as_posix() for path in unit.members)
        if role == QtCore.Qt.DecorationRole and index.column() == 1 and index.row() in self.archive.images:
            return QtGui.QIcon(str(self.archive.images[index.row()]))
        return None

    def flags(self, index):
        flags = super().flags(index)
        if index.isValid() and index.column() == 0 and self.archive and self.archive.mode == "separate":
            flags |= QtCore.Qt.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=QtCore.Qt.EditRole) -> bool:
        if not index.isValid() or index.column() != 0 or role != QtCore.Qt.CheckStateRole or self.archive is None or self.archive.mode != "separate":
            return False
        if value == QtCore.Qt.Checked or value == QtCore.Qt.Checked.value:
            self.archive.selected.add(index.row())
        else:
            self.archive.selected.discard(index.row())
        self.dataChanged.emit(index, index, [QtCore.Qt.CheckStateRole])
        return True

    def select_all(self, checked: bool) -> None:
        if self.archive is not None:
            self.archive.selected = set(range(len(self.archive.units))) if checked else set()
            self.set_archive(self.archive)
