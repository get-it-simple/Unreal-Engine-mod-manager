from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6 import QtCore, QtGui

from mod_manager import storage
from mod_manager.dragdrop import TransferredPaths
from mod_manager.mods import discover_mods, mod_image_path
from tests.window_fixture import WindowTestCase


class ArchiveImportGuiTests(WindowTestCase):
    def setUp(self):
        super().setUp()
        self.use_inline_runner()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.window.cfg.update(mods_source_dir=str(self.source), game_mods_dir=str(self.root / "game"))
        self.window.current_mod_items = []
        for key, value in (
            ("CONFIG_PATH", self.root / "config.json"), ("LABELS_PATH", self.root / "labels.json"),
            ("PRESETS_PATH", self.root / "presets.json"), ("PROFILE_DATA_DIR", self.root / "profiles"),
        ):
            patcher = patch.object(storage, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        controller = self.window.archive_import
        if controller.dialog:
            controller.dialog.reject()
        super().tearDown()

    def archive(self, name="archive.zip", members=None):
        path = self.root / name
        with zipfile.ZipFile(path, "w") as archive:
            for member, payload in (members or {"nested/A/a.pak": b"a", "nested/B/b.pak": b"b"}).items():
                archive.writestr(member, payload)
        return path

    def test_paste_single_nested_mod_imports_automatically(self):
        path = self.archive(members={"someFolder/someFolder/actualModFile.pak": b"payload"})
        with patch("mod_manager.ui.app.read_clipboard_paths", return_value=[path]):
            self.window._handle_paste()
        self.assertIsNone(self.window.archive_import.dialog)
        self.assertEqual((self.source / "archive" / "actualModFile.pak").read_bytes(), b"payload")

    def test_file_paste_from_search_field_imports_instead_of_inserting_path(self):
        path = self.archive(members={"nested/a.pak": b"a"})
        search = self.window.search_box.lineEdit()
        shortcut = QtGui.QKeyEvent(QtCore.QEvent.ShortcutOverride, QtCore.Qt.Key_V, QtCore.Qt.ControlModifier)
        key = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_V, QtCore.Qt.ControlModifier)
        with patch("mod_manager.ui.app.clipboard_has_files", return_value=True), patch("mod_manager.ui.app.read_clipboard_paths", return_value=[path]):
            self.assertTrue(self.window.eventFilter(search, shortcut))
            self.assertEqual(list(self.source.iterdir()), [])
            self.assertTrue(self.window.eventFilter(search, key))
        self.assertEqual((self.source / "archive" / "a.pak").read_bytes(), b"a")
        self.assertNotIn("archive.zip", search.text())

    def test_text_only_paste_in_search_is_not_intercepted(self):
        search = self.window.search_box.lineEdit()
        key = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_V, QtCore.Qt.ControlModifier)
        with patch("mod_manager.ui.app.clipboard_has_files", return_value=False), patch.object(self.window, "_handle_paste") as paste:
            self.assertFalse(self.window.eventFilter(search, key))
        paste.assert_not_called()

    def test_second_archive_pasted_during_publication_is_processed_afterwards(self):
        first = self.archive(members={"first.pak": b"first"})
        second = self.archive("second.zip", members={"second.pak": b"second"})
        original = self.window._run_action
        pending = []

        def hold_publication(label, worker, done=None, file_key="global"):
            if label == "Importing archives...":
                pending.append((worker, done))
            else:
                original(label, worker, done, file_key)

        self.window._run_action = hold_publication
        self.window._import_paths([first])
        self.assertTrue(self.window.archive_import.publishing)
        self.window._import_paths([second])
        self.window._run_action = original
        worker, done = pending.pop()
        done(worker())
        self.assertEqual((self.source / "archive" / "first.pak").read_bytes(), b"first")
        self.assertEqual((self.source / "second" / "second.pak").read_bytes(), b"second")

    def test_multiple_archives_switch_without_losing_selection_or_options(self):
        self.window._handle_mods_drop([self.archive(), self.archive("second.zip")])
        dialog = self.window.archive_import.dialog
        self.assertIsNotNone(dialog)
        browser = dialog.browser
        self.assertEqual(browser.selector_model.stringList(), ["archive.zip", "second.zip"])
        self.assertFalse(browser.filename.isVisible())
        self.assertEqual(browser.archive.source_name, "archive.zip")
        browser.together.setChecked(False)
        browser.preserve.setChecked(True)
        browser.model.setData(browser.model.index(0, 0), QtCore.Qt.Unchecked, QtCore.Qt.CheckStateRole)
        browser.selector.setCurrentIndex(browser.selector_model.index(1))
        self.assertTrue(browser.together.isChecked())
        self.assertFalse(browser.preserve.isChecked())
        browser.selector.setCurrentIndex(browser.selector_model.index(0))
        self.assertFalse(browser.together.isChecked())
        self.assertTrue(browser.preserve.isChecked())
        self.assertEqual(browser.model.data(browser.model.index(0, 0), QtCore.Qt.CheckStateRole), QtCore.Qt.Unchecked)

    def test_separate_mode_imports_checked_options_only(self):
        self.window._import_paths([self.archive()])
        dialog = self.window.archive_import.dialog
        dialog.browser.together.setChecked(False)
        dialog.browser.model.setData(dialog.browser.model.index(0, 0), QtCore.Qt.Unchecked, QtCore.Qt.CheckStateRole)
        dialog.actions.button("import").click()
        self.assertIsNone(self.window.archive_import.dialog)
        self.assertEqual({path.name for path in self.source.iterdir()}, {"b.pak"})

    def test_no_selection_disables_add_and_select_all_restores_it(self):
        self.window._import_paths([self.archive()])
        dialog = self.window.archive_import.dialog
        dialog.browser.together.setChecked(False)
        dialog.browser.toolbar.button("select_none").click()
        self.assertFalse(dialog.actions.button("import").isEnabled())
        dialog.browser.toolbar.button("select_all").click()
        self.assertTrue(dialog.actions.button("import").isEnabled())

    def test_cancel_removes_staged_content_without_importing(self):
        self.window._import_paths([self.archive()])
        dialog = self.window.archive_import.dialog
        staged_root = dialog.browser.archive.root
        self.assertTrue(staged_root.exists())
        dialog.reject()
        self.assertFalse(staged_root.exists())
        self.assertEqual(list(self.source.iterdir()), [])

    def test_native_drop_target_is_released_before_manager_window_hides(self):
        self.window._import_paths([self.archive()])
        dialog = self.window.archive_import.dialog
        observed = []
        target = self.window.archive_import.drop_target
        dialog.closing.connect(lambda: observed.append(dialog.isVisible()))
        with patch.object(target, "disable", wraps=target.disable) as disable:
            dialog.reject()
        disable.assert_called_once()
        self.assertEqual(observed, [True])
        self.assertIsNone(self.window.archive_import.drop_target)

    def test_previews_from_paste_and_drop_stay_associated_with_each_mod(self):
        self.window._import_paths([self.archive()])
        controller = self.window.archive_import
        browser = controller.dialog.browser
        browser.together.setChecked(False)
        browser.table.setCurrentIndex(browser.model.index(0, 1))
        image = QtGui.QImage(8, 8, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor("red"))
        clipboard = Mock()
        clipboard.image.return_value = image
        with patch("mod_manager.ui.controllers.archive_import_controller.read_clipboard_paths", return_value=[]), patch(
            "mod_manager.ui.controllers.archive_import_controller.QtWidgets.QApplication.clipboard", return_value=clipboard
        ):
            controller.paste()
        blue_path = self.root / "blue.png"
        image.fill(QtGui.QColor("blue"))
        image.save(str(blue_path))
        mime = QtCore.QMimeData()
        mime.setUrls([QtCore.QUrl.fromLocalFile(str(blue_path))])
        controller.handle_mime(mime, 1)
        self.assertEqual(set(browser.archive.images), {0, 1})
        controller.dialog.actions.button("import").click()
        red = QtGui.QImage(str(mod_image_path(self.window.cfg, "a.pak")))
        blue = QtGui.QImage(str(mod_image_path(self.window.cfg, "b.pak")))
        self.assertEqual(red.pixelColor(0, 0), QtGui.QColor("red"))
        self.assertEqual(blue.pixelColor(0, 0), QtGui.QColor("blue"))

    def test_drop_image_on_mod_row_uses_drop_position(self):
        self.window._import_paths([self.archive()])
        controller = self.window.archive_import
        browser = controller.dialog.browser
        browser.together.setChecked(False)
        browser.table.setCurrentIndex(browser.model.index(0, 1))
        image = QtGui.QImage(8, 8, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor("green"))
        path = self.root / "preview.png"
        image.save(str(path))
        mime = QtCore.QMimeData()
        mime.setUrls([QtCore.QUrl.fromLocalFile(str(path))])
        position = browser.table.visualRect(browser.model.index(1, 1)).center()
        event = QtGui.QDropEvent(QtCore.QPointF(position), QtCore.Qt.CopyAction, mime, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)
        self.assertTrue(browser.eventFilter(browser.table.viewport(), event))
        self.assertEqual(set(browser.archive.images), {1})

    def test_clear_preview_and_mode_switch_do_not_change_file_selection(self):
        self.window._import_paths([self.archive()])
        controller = self.window.archive_import
        browser = controller.dialog.browser
        browser.together.setChecked(False)
        browser.table.setCurrentIndex(browser.model.index(0, 1))
        image = QtGui.QImage(4, 4, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor("red"))
        path = self.root / "preview.png"
        image.save(str(path))
        controller.assign_image(path, 0)
        browser.together.setChecked(True)
        browser.together.setChecked(False)
        self.assertEqual(set(browser.archive.images), {0})
        browser.table.setCurrentIndex(browser.model.index(0, 1))
        browser.toolbar.button("clear_image").click()
        self.assertEqual(browser.archive.images, {})
        self.assertEqual(browser.archive.selected, {0, 1})

    def test_new_archive_is_appended_to_open_manager(self):
        self.window._import_paths([self.archive()])
        dialog = self.window.archive_import.dialog
        self.assertFalse(dialog.browser.selector.isVisible())
        self.assertTrue(dialog.browser.filename.isVisible())
        self.assertEqual(dialog.browser.filename.text(), "archive.zip")
        dialog.browser.together.setChecked(False)
        dialog.browser.table.setCurrentIndex(dialog.browser.model.index(1, 1))
        self.window._import_paths([self.archive("next.zip")])
        self.assertIs(self.window.archive_import.dialog, dialog)
        self.assertEqual(dialog.browser.selector_model.stringList(), ["archive.zip", "next.zip"])
        self.assertFalse(dialog.browser.together.isChecked())
        self.assertTrue(dialog.browser.selector.isVisible())
        self.assertFalse(dialog.browser.filename.isVisible())
        self.assertEqual(dialog.browser.selected_row, 1)

    def test_wheel_and_arrows_switch_archives_without_losing_import_choices(self):
        from PySide6 import QtTest

        self.window._import_paths([self.archive(), self.archive("second.zip")])
        browser = self.window.archive_import.dialog.browser
        browser.together.setChecked(False)
        browser.preserve.setChecked(True)
        browser.model.setData(browser.model.index(0, 0), QtCore.Qt.Unchecked, QtCore.Qt.CheckStateRole)
        position = browser.selector.viewport().rect().center()
        wheel = QtGui.QWheelEvent(
            QtCore.QPointF(position), QtCore.QPointF(browser.selector.viewport().mapToGlobal(position)),
            QtCore.QPoint(), QtCore.QPoint(0, -120), QtCore.Qt.NoButton,
            QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False,
        )
        self.qt_app.sendEvent(browser.selector.viewport(), wheel)
        self.assertEqual(browser.archive.source_name, "second.zip")
        self.assertFalse(browser.filename.isVisible())
        browser.selector.setFocus()
        QtTest.QTest.keyClick(browser.selector, QtCore.Qt.Key_Left)
        self.assertEqual(browser.archive.source_name, "archive.zip")
        self.assertFalse(browser.filename.isVisible())
        self.assertFalse(browser.together.isChecked())
        self.assertTrue(browser.preserve.isChecked())
        self.assertEqual(browser.archive.selected, {1})

    def test_appending_archive_preserves_active_archive_row_and_preview(self):
        self.window._import_paths([self.archive(), self.archive("second.zip")])
        controller = self.window.archive_import
        browser = controller.dialog.browser
        browser.selector.setCurrentIndex(browser.selector_model.index(1))
        browser.together.setChecked(False)
        browser.preserve.setChecked(True)
        browser.model.setData(browser.model.index(0, 0), QtCore.Qt.Unchecked, QtCore.Qt.CheckStateRole)
        image = QtGui.QImage(8, 8, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor("blue"))
        path = self.root / "preview.png"
        image.save(str(path))
        controller.assign_image(path, 1)
        active = browser.archive
        preview = active.images[1]
        self.window._import_paths([self.archive("third.zip")])
        self.assertIs(browser.archive, active)
        self.assertEqual(browser.selected_row, 1)
        self.assertEqual(browser.archive.selected, {1})
        self.assertTrue(browser.preserve.isChecked())
        self.assertEqual(browser.archive.images[1], preview)
        self.assertFalse(browser.preview.pixmap().isNull())

    def test_profile_change_prevents_import_into_wrong_source(self):
        self.window._import_paths([self.archive()])
        dialog = self.window.archive_import.dialog
        self.window.cfg["mods_source_dir"] = str(self.root / "different")
        with patch("mod_manager.ui.dialogs.prompts.show_warning") as warning:
            dialog.actions.button("import").click()
        warning.assert_called_once()
        self.assertEqual(list(self.source.iterdir()), [])

    def test_virtual_folder_with_nested_file_is_imported_and_transfer_is_cleaned(self):
        owner = tempfile.TemporaryDirectory()
        incoming_root = Path(owner.name)
        nested = incoming_root / "Folder" / "nested"
        nested.mkdir(parents=True)
        (nested / "a.pak").write_bytes(b"virtual")
        payload = TransferredPaths([incoming_root / "Folder"], owner)
        self.window._handle_mods_drop(payload)
        self.assertFalse(incoming_root.exists())
        self.assertEqual((self.source / "Folder" / "a.pak").read_bytes(), b"virtual")

    def test_corrupt_archive_reports_failure_and_good_archive_still_imports(self):
        corrupt = self.root / "bad.zip"
        corrupt.write_bytes(b"bad")
        good = self.archive(members={"nested/a.pak": b"a"})
        with patch("mod_manager.ui.dialogs.prompts.show_warning") as warning:
            self.window._import_paths([corrupt, good])
        warning.assert_called_once()
        self.assertEqual((self.source / "archive" / "a.pak").read_bytes(), b"a")

    def test_regular_import_ignores_extensions_and_keep_both_preserves_old_file(self):
        self.window.cfg["import_ignore_extensions"] = ".txt"
        self.window.cfg["mod_extensions"] = ""
        self.window.current_mod_items = discover_mods(self.window.cfg)
        path = self.root / "a.pak"
        path.write_bytes(b"new")
        ignored = self.root / "readme.txt"
        ignored.write_bytes(b"readme")
        (self.source / "a.pak").write_bytes(b"old")
        self.window.current_mod_items = discover_mods(self.window.cfg)
        with patch("mod_manager.ui.dialogs.prompts.choose_import_conflict", return_value="keep_both"):
            self.window._import_paths([path, ignored])
        self.assertEqual((self.source / "a.pak").read_bytes(), b"old")
        self.assertEqual((self.source / "a (1).pak").read_bytes(), b"new")
        self.assertFalse((self.source / "readme.txt").exists())
