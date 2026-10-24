from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PySide6 import QtCore, QtGui, QtTest, QtWidgets

from mod_manager.ui.dialogs.preview_confirmation import PreviewConfirmationDialog
from mod_manager.ui.theme import tokens
from tests.qt_support import dispose, qt_app


class PreviewConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "image.png"
        image = QtGui.QImage(400, 200, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor("red"))
        self.assertTrue(image.save(str(self.path)))

    def dialog(self, count=2, clipboard=False):
        dialog = PreviewConfirmationDialog(None, self.path, count, clipboard)
        dialog.setModal(False)
        self.addCleanup(dispose, dialog)
        return dialog

    def test_thumbnail_shows_proposed_image_without_distorting_it(self):
        dialog = self.dialog()
        image = dialog.content.preview.pixmap().toImage()
        self.assertFalse(image.isNull())
        self.assertEqual(image.width(), image.height() * 2)
        self.assertLessEqual(image.width(), tokens.PREVIEW_CONFIRM_IMAGE_SIZE)
        self.assertEqual(image.pixelColor(10, 10), QtGui.QColor("red"))

    def test_batch_message_describes_count_and_replacement(self):
        dialog = self.dialog(count=12)
        text = dialog.content.message.text()
        self.assertIn("12 selected mods", text)
        self.assertIn("replacing their existing previews", text)
        self.assertIsNone(dialog.file_button)

    def test_clipboard_offer_has_manual_file_alternative(self):
        dialog = self.dialog(count=1, clipboard=True)
        self.assertIn("clipboard", dialog.content.message.text())
        self.assertEqual(dialog.apply_button.text(), "Use image")
        self.assertEqual(dialog.file_button.text(), "Choose file...")
        dialog.file_button.click()
        self.assertEqual(dialog.choice, "file")

    def test_apply_button_confirms_assignment(self):
        dialog = self.dialog()
        dialog.apply_button.click()
        self.assertEqual(dialog.choice, "apply")
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)

    def test_cancel_escape_and_window_close_all_cancel(self):
        for action in ("button", "escape", "close"):
            with self.subTest(action=action):
                dialog = self.dialog(clipboard=True)
                dialog.show()
                self.app.processEvents()
                if action == "button":
                    dialog.cancel_button.click()
                elif action == "escape":
                    QtTest.QTest.keyClick(dialog, QtCore.Qt.Key_Escape)
                else:
                    dialog.close()
                self.assertEqual(dialog.choice, "cancel")
                self.assertFalse(dialog.isVisible())
