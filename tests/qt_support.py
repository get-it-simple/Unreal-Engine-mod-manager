from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6 import QtWidgets
except ModuleNotFoundError:
    QtWidgets = None


def qt_available() -> bool:
    return QtWidgets is not None


def qt_app():
    if QtWidgets is None:
        raise RuntimeError("PySide6 is not installed")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    fail_on_modal_dialogs()
    return app


def dispose(widget) -> None:
    """Close a widget and make Qt actually destroy it, so tests do not pile up windows."""
    from PySide6 import QtCore

    widget.close()
    widget.deleteLater()
    app = QtWidgets.QApplication.instance()
    app.processEvents()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    app.processEvents()


def fail_on_modal_dialogs() -> None:
    """Turn an unexpected modal dialog into a loud failure instead of a hung test."""
    from mod_manager.ui.dialogs import prompts

    def blocked(name):
        def raise_instead(*args, **kwargs):
            raise AssertionError(f"unexpected modal dialog: {name}{args[1:]}")
        return raise_instead

    for name in ("show_error", "show_warning", "show_info", "ask_yes_no", "choose_color",
                 "choose_directory", "choose_files", "choose_open_file", "choose_import_conflict"):
        setattr(prompts, name, blocked(name))
