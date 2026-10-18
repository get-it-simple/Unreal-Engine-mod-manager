from __future__ import annotations

import unittest

from PySide6 import QtCore, QtGui, QtTest, QtWidgets

from mod_manager.ui.theme import colors, tokens
from mod_manager.ui.theme.stylesheet import build_stylesheet
from mod_manager.ui.widgets.archive_selector import ArchiveSelector
from mod_manager.ui.widgets.buttons import text_button
from tests.qt_support import dispose, qt_app


class ArchiveSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    def setUp(self):
        self.host = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.host)
        self.selector = ArchiveSelector(self.host)
        layout.addWidget(self.selector)
        self.other = QtWidgets.QLineEdit(self.host)
        layout.addWidget(self.other)
        self.host.resize(900, 180)
        self.addCleanup(dispose, self.host)

    def show_names(self, names):
        self.selector.set_names(names)
        self.selector.setCurrentIndex(self.selector.model().index(0))
        self.host.show()
        self.app.processEvents()

    def wheel(self, angle=0, pixels=0):
        position = self.selector.viewport().rect().center()
        event = QtGui.QWheelEvent(
            QtCore.QPointF(position), QtCore.QPointF(self.selector.viewport().mapToGlobal(position)),
            QtCore.QPoint(0, pixels), QtCore.QPoint(0, angle), QtCore.Qt.NoButton,
            QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False,
        )
        self.app.sendEvent(self.selector.viewport(), event)
        self.app.processEvents()

    def hover(self, row):
        position = self.selector.visualRect(self.selector.model().index(row)).center()
        event = QtGui.QMouseEvent(
            QtCore.QEvent.MouseMove, QtCore.QPointF(position),
            QtCore.QPointF(self.selector.viewport().mapToGlobal(position)), QtCore.Qt.NoButton,
            QtCore.Qt.NoButton, QtCore.Qt.NoModifier,
        )
        self.app.sendEvent(self.selector.viewport(), event)

    def test_single_archive_hides_row_and_second_archive_restores_it(self):
        self.show_names(["one.zip"])
        self.assertFalse(self.selector.isVisible())
        hidden_height = self.host.layout().sizeHint().height()
        self.selector.set_names(["one.zip", "two.zip"])
        self.app.processEvents()
        self.assertTrue(self.selector.isVisible())
        self.assertGreater(self.host.layout().sizeHint().height(), hidden_height)

    def test_buttons_fill_available_width_and_resize_equally(self):
        self.show_names(["one.zip", "two.zip", "three.zip"])
        for width in (900, 1100, 700):
            self.host.resize(width, self.host.height())
            self.app.processEvents()
            rects = [self.selector.visualRect(self.selector.model().index(row)) for row in range(3)]
            self.assertLessEqual(max(rect.width() for rect in rects) - min(rect.width() for rect in rects), 1)
            self.assertEqual(rects[0].left(), 0)
            self.assertEqual(rects[-1].right() + 1, self.selector.viewport().width())
            self.assertTrue(all(rect.top() == 0 for rect in rects))
            self.assertFalse(self.selector.horizontalScrollBar().isVisible())

    def test_many_archives_keep_minimum_width_and_last_selection_visible(self):
        self.show_names([f"archive-{row}.zip" for row in range(2000)])
        self.assertTrue(self.selector.horizontalScrollBar().isVisible())
        self.selector.setCurrentIndex(self.selector.model().index(1999))
        self.app.processEvents()
        rect = self.selector.visualRect(self.selector.currentIndex())
        self.assertGreaterEqual(rect.width() - tokens.SPACE_XS * 2, tokens.ARCHIVE_SWITCHER_MIN_WIDTH)
        self.assertGreaterEqual(rect.height(), self.selector.fontMetrics().height())
        self.assertTrue(self.selector.viewport().rect().contains(rect))
        self.assertEqual(self.selector.findChildren(QtWidgets.QPushButton), [])

    def test_wheel_switches_without_focus_and_stops_at_boundaries(self):
        self.show_names([f"archive-{row}.zip" for row in range(20)])
        self.other.setFocus()
        self.wheel(-120)
        self.assertEqual(self.selector.currentIndex().row(), 1)
        self.assertTrue(self.other.hasFocus())
        self.wheel(-120 * 30)
        self.assertEqual(self.selector.currentIndex().row(), 19)
        self.assertTrue(self.selector.viewport().rect().contains(self.selector.visualRect(self.selector.currentIndex())))
        self.wheel(120 * 30)
        self.assertEqual(self.selector.currentIndex().row(), 0)
        self.wheel(120)
        self.assertEqual(self.selector.currentIndex().row(), 0)

    def test_partial_wheel_and_touchpad_deltas_accumulate(self):
        self.show_names(["one.zip", "two.zip", "three.zip"])
        self.wheel(-60)
        self.assertEqual(self.selector.currentIndex().row(), 0)
        self.wheel(-60)
        self.assertEqual(self.selector.currentIndex().row(), 1)
        self.wheel(pixels=-tokens.ARCHIVE_WHEEL_PIXEL_STEP // 2)
        self.assertEqual(self.selector.currentIndex().row(), 1)
        self.wheel(pixels=-tokens.ARCHIVE_WHEEL_PIXEL_STEP // 2)
        self.assertEqual(self.selector.currentIndex().row(), 2)

    def test_arrows_switch_only_when_row_has_focus(self):
        self.show_names([f"archive-{row}.zip" for row in range(20)])
        self.other.setFocus()
        QtTest.QTest.keyClick(self.other, QtCore.Qt.Key_Right)
        self.assertEqual(self.selector.currentIndex().row(), 0)
        self.selector.setFocus()
        QtTest.QTest.keyClick(self.selector, QtCore.Qt.Key_Left)
        self.assertEqual(self.selector.currentIndex().row(), 0)
        for _ in range(25):
            QtTest.QTest.keyClick(self.selector, QtCore.Qt.Key_Right)
        self.assertEqual(self.selector.currentIndex().row(), 19)
        self.assertTrue(self.selector.viewport().rect().contains(self.selector.visualRect(self.selector.currentIndex())))
        QtTest.QTest.keyClick(self.selector, QtCore.Qt.Key_Left)
        self.assertEqual(self.selector.currentIndex().row(), 18)

    def test_click_selects_archive_and_full_name_is_accessible(self):
        name = "Дуже довга назва архіву з багатьма словами та варіантами.zip"
        self.show_names(["one.zip", name])
        index = self.selector.model().index(1)
        QtTest.QTest.mouseClick(self.selector.viewport(), QtCore.Qt.LeftButton, pos=self.selector.visualRect(index).center())
        self.assertEqual(self.selector.currentIndex(), index)
        self.assertEqual(index.data(QtCore.Qt.ToolTipRole), name)
        self.assertEqual(index.data(QtCore.Qt.AccessibleTextRole), name)
        self.assertLessEqual(len(self.selector.display_text(index)), 32)
        self.assertTrue(self.selector.display_text(index).endswith("…"))

    def apply_theme(self, mode):
        theme = colors.build_palette(mode)
        self.host.setObjectName("archiveSelectorTestHost")
        self.host.setStyleSheet(build_stylesheet(theme) + f"QWidget#archiveSelectorTestHost {{ background-color: {theme.bg}; }}")
        return theme

    def text_pixels(self, row, color):
        rect = self.selector.visualRect(self.selector.model().index(row)).adjusted(8, 8, -8, -8)
        image = self.selector.viewport().grab(rect).toImage()
        return {(x, y) for y in range(image.height()) for x in range(image.width())
                if image.pixelColor(x, y) == QtGui.QColor(color)}

    def test_hover_preserves_rendered_short_and_long_text(self):
        theme = self.apply_theme("light")
        self.show_names(["A long archive name with many variants " * 4 + ".zip", "short.zip"])
        self.other.setFocus()
        for row in (0, 1):
            self.hover(1 - row)
            before = self.text_pixels(row, theme.control_fg)
            self.assertTrue(before)
            self.hover(row)
            self.assertEqual(before, self.text_pixels(row, theme.control_fg))
            QtTest.QTest.qWait(30)
            self.assertEqual(before, self.text_pixels(row, theme.control_fg))
            self.app.sendEvent(self.selector.viewport(), QtCore.QEvent(QtCore.QEvent.Leave))
            self.assertEqual(before, self.text_pixels(row, theme.control_fg))

    def test_hover_keeps_text_position_after_resize_and_font_change(self):
        theme = self.apply_theme("light")
        self.show_names(["archive with a moderately long filename.zip", "short.zip"])
        for width, size in ((900, 10), (500, 10), (700, 14)):
            self.host.resize(width, self.host.height())
            font = self.selector.font()
            font.setPointSize(size)
            self.selector.setFont(font)
            self.app.processEvents()
            self.hover(1)
            before = self.text_pixels(0, theme.control_fg)
            self.assertTrue(before)
            self.hover(0)
            self.assertEqual(before, self.text_pixels(0, theme.control_fg))

    def test_background_states_match_standard_buttons_in_both_themes(self):
        reference = text_button("Reference", "Reference", parent=self.host)
        reference.setCheckable(True)
        reference.setFixedWidth(200)
        self.host.layout().addWidget(reference)
        self.show_names(["one.zip", "two.zip"])
        for mode in ("light", "dark"):
            self.apply_theme(mode)
            self.other.setFocus()
            self.app.processEvents()
            for selected, hovered, enabled in ((False, False, True), (False, True, True),
                                                (True, False, True), (False, False, False)):
                with self.subTest(mode=mode, selected=selected, hovered=hovered, enabled=enabled):
                    self.selector.setEnabled(enabled)
                    reference.setEnabled(enabled)
                    self.selector.setCurrentIndex(self.selector.model().index(1 if selected else 0))
                    reference.setChecked(selected)
                    target = reference if hovered else self.other
                    QtTest.QTest.mouseMove(target, target.rect().center())
                    self.app.processEvents()
                    expected = self.host.grab().toImage().pixelColor(reference.mapTo(self.host, QtCore.QPoint(12, 12)))
                    self.hover(1 if hovered else 0)
                    rect = self.selector.visualRect(self.selector.model().index(1))
                    image = self.host.grab().toImage()
                    actual = image.pixelColor(self.selector.viewport().mapTo(self.host, rect.topLeft() + QtCore.QPoint(14, 12)))
                    self.assertEqual(actual, expected)

    def test_height_matches_standard_text_buttons_with_different_fonts_and_overflow(self):
        reference = text_button("Select all", "Select every mod", parent=self.host, icon_name="add")
        self.host.layout().addWidget(reference)
        self.show_names(["one.zip", "two.zip"])
        for mode in ("light", "dark"):
            self.apply_theme(mode)
            for size in (10, 14, 20):
                font = self.selector.font()
                font.setFamily("Segoe UI")
                font.setPointSize(size)
                self.selector.setFont(font)
                reference.setFont(font)
                for count in (2, 30):
                    with self.subTest(mode=mode, size=size, count=count):
                        self.selector.set_names([f"archive-{row}.zip" for row in range(count)])
                        self.selector.setCurrentIndex(self.selector.model().index(count - 1))
                        self.app.processEvents()
                        rect = self.selector.visualRect(self.selector.currentIndex())
                        self.assertEqual(rect.height(), reference.sizeHint().height())
                        self.assertEqual(self.selector.viewport().height(), rect.height())
                        self.assertGreaterEqual(rect.height(), self.selector.fontMetrics().height())
                        self.assertTrue(self.selector.viewport().rect().contains(rect))
                        self.assertEqual(self.selector.horizontalScrollBar().isVisible(), count > 2)

    def test_keyboard_focus_changes_outline_without_moving_text(self):
        theme = self.apply_theme("light")
        self.show_names(["one.zip", "two.zip"])
        self.other.setFocus()
        self.app.processEvents()
        before = self.text_pixels(0, theme.control_fg)
        self.assertTrue(before)
        image = self.selector.viewport().grab().toImage()
        self.selector.setFocus()
        self.app.processEvents()
        self.assertEqual(before, self.text_pixels(0, theme.control_fg))
        self.assertNotEqual(image, self.selector.viewport().grab().toImage())
