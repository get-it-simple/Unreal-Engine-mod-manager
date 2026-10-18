from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from threading import Event

from PySide6 import QtCore, QtGui, QtWidgets

from ...archive_backend import ARCHIVE_EXTENSIONS
from ...cli_utils import ensure_paths
from ...dragdrop import read_clipboard_image, read_clipboard_paths
from ...imports import create_plans, execute_plans, ignored_file, prepare_archive, resolve_plans
from ...mods import is_image_file
from ...log import logger
from ..dialogs import prompts
from ..dialogs.archive_import import ArchiveImportDialog
from ..dialogs.base import show_dialog
from ..widgets.drop_target import QtWindowsDropTarget, dropped_paths


class ArchiveImportController(QtCore.QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.dialog: ArchiveImportDialog | None = None
        self.archives = []
        self.pending_paths = []
        self.cfg = {}
        self.assets = None
        self.drop_target = None
        self.closed = False
        self.scans = 0
        self.publishing = False
        self.cancelled = Event()
        self.deferred_inputs = []

    def handle_paths(self, paths, image_target_name: str = "") -> bool:
        virtual_root = getattr(paths, "temporary_root", None)
        virtual = virtual_root is not None
        archives = [path for path in paths if path.suffix.lower() in ARCHIVE_EXTENSIONS and path.is_file() and not ignored_file(path, self.window.cfg)]
        images_only = bool(paths) and all(is_image_file(path) for path in paths)
        if images_only and self.dialog is None:
            return False
        if not archives and not virtual and self.dialog is None:
            return False
        if not ensure_paths(self.window.cfg):
            return True
        if self.publishing and not self.closed:
            self.deferred_inputs.append((paths, image_target_name))
            self.window._set_status("Finishing the current import. Additional files have been queued.")
            return True
        if self.closed:
            release = getattr(paths, "close", None)
            if release:
                release()
            return True
        if self.dialog and images_only:
            try:
                if len(paths) == 1:
                    self.assign_image(paths[0], self.dialog.browser.selected_row)
                else:
                    self.dialog.status.setText("Choose one image for the selected mod.")
            finally:
                release = getattr(paths, "close", None)
                if release:
                    release()
            return True
        if not self.cfg:
            self.cfg = dict(self.window.cfg)
            self.assets = tempfile.TemporaryDirectory(prefix="mods-import-images-")
        inputs = list(archives)
        if virtual:
            inputs = list(paths) if all(path.is_dir() or path.suffix.lower() in ARCHIVE_EXTENSIONS for path in paths) else [Path(virtual_root)]
        else:
            self.pending_paths.extend(path for path in paths if path not in archives and not ignored_file(path, self.cfg))
        if not inputs:
            return True
        self.scans += 1
        cfg = dict(self.cfg)
        if self.dialog:
            self.dialog.set_working(True)

        def worker():
            prepared, errors = [], []
            try:
                for path in inputs:
                    try:
                        archive = prepare_archive(path, cfg, self.cancelled)
                        if virtual and path == Path(virtual_root):
                            archive.name = "Archive contents"
                            archive.source_name = "Archive contents"
                        prepared.append(archive)
                    except Exception as exc:
                        errors.append(f"{path.name}: {exc}")
            finally:
                release = getattr(paths, "close", None)
                if release:
                    release()
            if self.closed:
                for archive in prepared:
                    archive.close()
                self._cleanup()
            return prepared, errors

        def done(result):
            prepared, errors = result
            self.scans -= 1
            if self.closed:
                return
            self.archives.extend(prepared)
            if errors:
                prompts.show_warning(self.window, "Archive import", "\n".join(errors))
            if self.scans:
                return
            if not self.archives:
                self._cleanup()
                return
            if self.dialog or len(self.archives) > 1 or len(self.archives[0].units) > 1:
                self._show_manager()
            else:
                self.commit()

        self.window._run_action("Reading archives...", worker, done)
        return True

    def _show_manager(self) -> None:
        if self.dialog is None:
            self.dialog = ArchiveImportDialog(self.window)
            self.dialog.importRequested.connect(self.commit)
            self.dialog.pasteRequested.connect(self.paste)
            self.dialog.dropRequested.connect(self.handle_mime)
            self.dialog.browser.imageRequested.connect(self.handle_mime)
            self.dialog.finished.connect(self._finished)
            self.dialog.closing.connect(self._disable_drop_target)

            def native_drop(paths, x, y):
                if self.dialog is None:
                    return
                table = self.dialog.browser.table
                index = table.indexAt(table.viewport().mapFromGlobal(QtCore.QPoint(x, y)))
                if index.isValid():
                    table.setCurrentIndex(index)
                self.handle_paths(paths)

            self.drop_target = QtWindowsDropTarget(self.dialog.browser.table.viewport(), native_drop)
        self.dialog.browser.set_archives(self.archives)
        self.dialog.set_working(False)
        show_dialog(self.dialog)

    def handle_mime(self, mime, row: int = -1) -> None:
        if self.dialog is None or self.dialog.working:
            return
        paths = dropped_paths(mime) if mime.hasUrls() else []
        if paths:
            if len(paths) == 1 and is_image_file(paths[0]):
                self.assign_image(paths[0], row if row >= 0 else self.dialog.browser.selected_row)
            else:
                self.handle_paths(paths)
        elif mime.hasImage():
            image = QtGui.QImage(mime.imageData())
            self._assign_qimage(image, row if row >= 0 else self.dialog.browser.selected_row)

    def paste(self) -> None:
        if self.dialog is None or self.dialog.working:
            return
        paths = read_clipboard_paths()
        if paths:
            self.handle_paths(paths)
            return
        image = QtWidgets.QApplication.clipboard().image()
        if not image.isNull():
            self._assign_qimage(image, self.dialog.browser.selected_row)
            return
        path = read_clipboard_image()
        if path:
            try:
                self.assign_image(path, self.dialog.browser.selected_row)
            finally:
                path.unlink(missing_ok=True)

    def _assign_qimage(self, image: QtGui.QImage, row: int) -> None:
        if image.isNull() or self.assets is None:
            return
        handle = tempfile.NamedTemporaryFile(suffix=".png", dir=self.assets.name, delete=False)
        path = Path(handle.name)
        handle.close()
        if image.save(str(path), "PNG"):
            self.assign_image(path, row)

    def assign_image(self, source: Path, row: int) -> None:
        if self.dialog is None or self.assets is None:
            return
        archive = self.dialog.browser.archive
        if archive is None or archive.mode != "separate" or not 0 <= row < len(archive.units):
            self.dialog.status.setText("Switch to separate mode and select a mod before assigning an image.")
            return
        if QtGui.QImageReader(str(source)).size().isEmpty():
            self.dialog.status.setText("This image could not be read. The mod can still be imported.")
            return
        try:
            with tempfile.NamedTemporaryFile(suffix=source.suffix, dir=self.assets.name, delete=False) as handle:
                target = Path(handle.name)
            shutil.copy2(source, target)
        except OSError as exc:
            self.dialog.status.setText(f"Cannot assign preview: {exc}")
            return
        archive.images[row] = target
        self.dialog.browser.table.setCurrentIndex(self.dialog.browser.model.index(row, 1))
        self.dialog.browser.model.dataChanged.emit(self.dialog.browser.model.index(row, 1), self.dialog.browser.model.index(row, 1))
        self.dialog.browser.update_preview()
        self.dialog.status.setText(f"Preview assigned to {archive.units[row].name}.")

    def commit(self) -> None:
        if self.publishing or self.scans or self.closed:
            return
        if any(self.cfg.get(key) != self.window.cfg.get(key) for key in ("active_game_profile_id", "mods_source_dir", "game_mods_dir")):
            prompts.show_warning(self.window, "Archive import", "The game profile or mod directories changed. Close this import and add the archives again.")
            return
        choose = lambda name: prompts.choose_import_conflict(self.dialog or self.window, name)
        plans = resolve_plans(self.cfg, create_plans(self.archives, choose), choose)
        if not plans:
            if self.dialog:
                self.dialog.status.setText("No mods selected for import.")
            else:
                self._cleanup()
            return
        self.publishing = True
        if self.dialog:
            self.dialog.set_working(True)

        def worker():
            try:
                return execute_plans(self.cfg, plans, self.cancelled)
            except Exception as exc:
                logger.exception("Archive import failed")
                return [], [str(exc)]
            finally:
                if self.closed:
                    self._cleanup()

        def done(result):
            self.publishing = False
            imported, errors = result
            pending = list(self.pending_paths)
            deferred = self.deferred_inputs
            self.deferred_inputs = []
            for plan in plans:
                if plan.image:
                    self.window._invalidate_mod_image(plan.name)
            self.window.refresh_mods()
            self.window._set_status(f"Imported mods: {len(imported)}. Failed: {len(errors)}.")
            if errors:
                prompts.show_warning(self.dialog or self.window, "Archive import", "\n".join(errors))
            if self.dialog:
                self.dialog.set_working(False)
                self.dialog.accept()
            else:
                self._cleanup()
            if pending and not self.closed:
                self.window._import_regular_paths(pending)
            for paths, target in deferred:
                if not self.closed:
                    self.window._import_paths(paths, target)

        self.window._run_action("Importing archives...", worker, done)

    def _finished(self, _result) -> None:
        dialog = self.dialog
        self.dialog = None
        if dialog is not None:
            dialog.deleteLater()
        self._cleanup()

    def _disable_drop_target(self) -> None:
        if self.drop_target is not None:
            self.drop_target.disable()
            self.drop_target = None

    def _cleanup(self) -> None:
        self._disable_drop_target()
        for archive in self.archives:
            archive.close()
        self.archives.clear()
        self.pending_paths.clear()
        for paths, _target in self.deferred_inputs:
            release = getattr(paths, "close", None)
            if release:
                release()
        self.deferred_inputs.clear()
        self.cfg = {}
        if self.assets is not None:
            self.assets.cleanup()
            self.assets = None

    def shutdown(self) -> None:
        self.closed = True
        self.cancelled.set()
        self._disable_drop_target()
        if not self.scans and not self.publishing:
            self._cleanup()
