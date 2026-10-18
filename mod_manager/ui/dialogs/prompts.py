from __future__ import annotations

from PySide6 import QtGui, QtWidgets


def show_error(parent, title: str, message: str) -> None:
    QtWidgets.QMessageBox.critical(parent, title, message)


def show_warning(parent, title: str, message: str) -> None:
    QtWidgets.QMessageBox.warning(parent, title, message)


def show_info(parent, title: str, message: str) -> None:
    QtWidgets.QMessageBox.information(parent, title, message)


def ask_yes_no(parent, title: str, message: str) -> bool:
    answer = QtWidgets.QMessageBox.question(
        parent,
        title,
        message,
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
    )
    return answer == QtWidgets.QMessageBox.Yes


def choose_directory(parent, title: str) -> str:
    return QtWidgets.QFileDialog.getExistingDirectory(parent, title)


def choose_files(parent, title: str, file_filter: str = "") -> list[str]:
    paths, _selected = QtWidgets.QFileDialog.getOpenFileNames(parent, title, "", file_filter)
    return list(paths)


def choose_open_file(parent, title: str, file_filter: str = "") -> str:
    path, _selected = QtWidgets.QFileDialog.getOpenFileName(parent, title, "", file_filter)
    return path


def choose_color(parent, current: QtGui.QColor, title: str) -> QtGui.QColor:
    return QtWidgets.QColorDialog.getColor(current, parent, title)


def choose_import_conflict(parent, name: str) -> str:
    dialog = QtWidgets.QMessageBox(parent)
    dialog.setWindowTitle("Import name conflict")
    dialog.setText(f"The import target '{name}' already exists. Choose how to import the new mod.")
    replace = dialog.addButton("Replace", QtWidgets.QMessageBox.DestructiveRole)
    keep = dialog.addButton("Keep both", QtWidgets.QMessageBox.AcceptRole)
    skip = dialog.addButton("Skip", QtWidgets.QMessageBox.RejectRole)
    dialog.setDefaultButton(keep)
    dialog.setEscapeButton(skip)
    dialog.exec()
    return "replace" if dialog.clickedButton() is replace else "keep_both" if dialog.clickedButton() is keep else "skip"
