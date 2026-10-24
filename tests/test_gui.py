from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.qt_support import dispose, qt_app

from mod_manager.models import ModItem
from tests.window_fixture import FAKE_DEST as _FAKE_DEST
from tests.window_fixture import FAKE_SRC as _FAKE_SRC
from tests.window_fixture import base_config
from mod_manager.ui.theme import tokens

try:
    from PySide6 import QtCore, QtGui, QtWidgets

    from mod_manager.ui.dialogs.game_profile import GameProfileDialog
except ModuleNotFoundError:
    QtCore = None
    QtGui = None
    QtWidgets = None

_FAKE_DROP = Path(tempfile.gettempdir()) / "mm_test_drop"


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt_app = qt_app()

    def setUp(self) -> None:
        self.cfg = base_config()
        self.mods = [
            self.mod_item("combat.pak", installed=True),
            self.mod_item("ui.pak", installed=False),
        ]
        self.presets = {"core": ["combat.pak"], "ui": ["ui.pak"]}
        self.broken = [self.mod_item("missing.pak", installed=True)]
        self.patchers = [
            # storage.save_config is imported lazily inside workers, so it must be patched at
            # its source or a test would overwrite the real config.json next to the app.
            patch("mod_manager.storage.save_config"),
            patch("mod_manager.ui.app.load_config", return_value=self.cfg),
            patch("mod_manager.ui.app.save_config"),
            patch("mod_manager.ui.app.ensure_paths", return_value=True),
            patch("mod_manager.ui.app.mod_image_path", return_value=None),
            patch("mod_manager.ui.app.mods_view", return_value=(self.mods, self.mods, 1, 1, {"combat.pak": "combat"})),
            patch(
                "mod_manager.ui.app.mods_records",
                return_value={"combat.pak": {"last_managed": "2026-01-01 10:00:00"}},
            ),
            patch("mod_manager.ui.app.presets_view", return_value=(self.presets, list(self.presets), ["core", "ui"], 1, 1)),
            patch(
                "mod_manager.ui.app.presets_records",
                return_value={"core": {"state": "applied", "last_managed": "2026-01-02 10:00:00"}},
            ),
            patch("mod_manager.ui.app.list_installed_mods", return_value=[self.mods[0]]),
            patch("mod_manager.ui.app.list_broken_links", return_value=self.broken),
        ]
        for patcher in self.patchers:
            patcher.start()
        from mod_manager.ui.app import ModManagerGui

        self.window = ModManagerGui()
        self.window.hide()
        self.qt_app.processEvents()

    def tearDown(self) -> None:
        dispose(self.window)
        for patcher in reversed(self.patchers):
            patcher.stop()

    def mod_item(self, name: str, installed: bool = False, is_dir: bool = False) -> ModItem:
        return ModItem(name=name, src=_FAKE_SRC / name, dest=_FAKE_DEST / name, is_dir=is_dir, installed=installed)

    def run_action_inline(self, label, worker, done=None, file_key="global") -> None:
        result = worker()
        if done:
            done(result)

    def select_mod_rows(self, *rows: int) -> None:
        view = self.window._current_mod_view()
        selection_model = view.selectionModel()
        selection_model.clearSelection()
        for row in rows:
            left = self.window.mods_model.index(row, 0)
            right = self.window.mods_model.index(row, self.window.mods_model.columnCount() - 1)
            selection = QtCore.QItemSelection(left, right)
            selection_model.select(selection, QtCore.QItemSelectionModel.Select)
        self.qt_app.processEvents()

    def widget_texts(self, widget):
        values = []
        try:
            text = widget.text()
            if text:
                values.append(text)
        except AttributeError:
            pass
        for child in widget.findChildren(QtWidgets.QWidget):
            try:
                text = child.text()
                if text:
                    values.append(text)
            except AttributeError:
                pass
        return values

    def test_initial_refresh_populates_models(self):
        self.assertIs(self.window.centralWidget(), self.window.mods_tab)
        self.assertFalse(hasattr(self.window, "tabs"))
        self.assertEqual(self.window.mods_model.rowCount(), 2)
        self.assertEqual(self.window.mods_model.data(self.window.mods_model.index(0, 0)), "")
        self.assertEqual(self.window.mods_model.data(self.window.mods_model.index(0, 1)), "combat.pak")
        self.assertEqual(self.window.mods_model.data(self.window.mods_model.index(1, 1)), "ui.pak")
        self.assertFalse(self.window.mods_model.data(self.window.mods_model.index(0, 0), QtCore.Qt.DecorationRole).isNull())
        self.assertFalse(self.window.mods_model.data(self.window.mods_model.index(1, 0), QtCore.Qt.DecorationRole).isNull())
        self.assertEqual(self.window.mods_model.data(self.window.mods_model.index(0, 2)), "combat")
        self.assertEqual(self.window.presets_model.rowCount(), 2)
        self.assertEqual(self.window.presets_model.data(self.window.presets_model.index(0, 0)), "core")
        self.assertEqual(self.window.presets_model.data(self.window.presets_model.index(0, 1), QtCore.Qt.UserRole), "active")
        self.assertEqual(self.window.presets_model.data(self.window.presets_model.index(1, 1), QtCore.Qt.UserRole), "inactive")
        self.assertFalse(self.window.presets_model.data(self.window.presets_model.index(0, 1), QtCore.Qt.DecorationRole).isNull())
        self.assertEqual(self.window.broken_model.rowCount(), 1)
        self.assertEqual(self.window.broken_model.data(self.window.broken_model.index(0, 0)), "missing.pak")

    def test_mod_table_stretches_only_name_column(self):
        header = self.window.mods_table.horizontalHeader()

        self.assertFalse(header.stretchLastSection())
        self.assertEqual(header.sectionResizeMode(0), QtWidgets.QHeaderView.Fixed)
        self.assertEqual(header.sectionResizeMode(1), QtWidgets.QHeaderView.Stretch)
        self.assertEqual(header.sectionResizeMode(2), QtWidgets.QHeaderView.ResizeToContents)
        self.assertEqual(header.sectionResizeMode(3), QtWidgets.QHeaderView.ResizeToContents)
        self.assertTrue(header.sectionsClickable())

    def test_state_column_uses_the_configured_width(self):
        header = self.window.mods_table.horizontalHeader()

        self.assertEqual(header.sectionSize(0), self.cfg["placeholder_image_col_width"])

    def test_manage_section_opens_secondary_dialogs(self):
        manage = self.window.mods_toolbar.sections["manage"]
        self.assertEqual(manage.title, "Manage")
        self.assertEqual(
            [button.accessibleName() for button in manage.widgets()],
            ["Open presets", "Open settings", "Open broken links cleanup"],
        )

        self.window._open_presets_dialog()
        self.assertTrue(self.window.presets_dialog.isVisible())
        self.window.presets_dialog.close()

        self.window._open_settings_dialog()
        self.assertTrue(self.window.settings_dialog.isVisible())
        self.window.settings_dialog.close()

        self.window._open_broken_dialog()
        self.assertTrue(self.window.broken_dialog.isVisible())
        self.window.broken_dialog.close()

    def test_duplicate_manage_menu_is_not_built(self):
        self.assertIsNone(self.window.menuWidget())

    def test_page_inputs_apply_on_enter_for_mods_and_presets(self):
        self.window.page_control.set_page(1, 5)
        with patch.object(self.window, "refresh_mods") as refresh_mods:
            self.window.page_control.input.setText("3")
            self.window.page_control.input.returnPressed.emit()
        self.assertEqual(self.window.mod_page.get(), 3)
        refresh_mods.assert_called_once_with()

        self.window.preset_page_control.set_page(1, 4)
        with patch.object(self.window, "refresh_presets") as refresh_presets:
            self.window.preset_page_control.input.setText("2")
            self.window.preset_page_control.input.returnPressed.emit()
        self.assertEqual(self.window.preset_page.get(), 2)
        refresh_presets.assert_called_once_with()

    def test_favorite_filter_combines_with_search_and_label(self):
        self.window.search_var.set("pak")
        self.window.label_filter_var.set("combat")
        with patch(
            "mod_manager.ui.app.mods_view",
            return_value=(self.mods, self.mods, 1, 1, {"combat.pak": "combat"}),
        ) as mods_view:
            self.window.favorite_filter_button.click()

        self.assertTrue(self.window.favorite_filter_var.get())
        mods_view.assert_called_once_with(self.window.cfg, 1, "combat", "pak", "default", True)

    def test_selected_favorite_action_adds_or_removes_the_whole_selection(self):
        self.select_mod_rows(0, 1)
        self.window.current_mod_favorites = {"combat.pak"}
        with patch("mod_manager.ui.app.add_favorites_to_mods", return_value="Added") as add, patch.object(
            self.window, "refresh_mods"
        ):
            self.window._toggle_favorite_selected()
        add.assert_called_once_with(self.window.cfg, ["combat.pak", "ui.pak"])

        self.window.current_mod_favorites = {"combat.pak", "ui.pak"}
        with patch("mod_manager.ui.app.remove_favorites_from_mods", return_value="Removed") as remove, patch.object(
            self.window, "refresh_mods"
        ):
            self.window._toggle_favorite_selected()
        remove.assert_called_once_with(self.window.cfg, ["combat.pak", "ui.pak"])

    def test_single_mod_detail_exposes_favorite_action(self):
        self.window.current_mod_favorites = set()
        self.window._refresh_mod_detail(self.mods[0])
        labels = [button.text() for button in self.window.detail_frame.findChildren(QtWidgets.QPushButton)]
        self.assertIn("Add to favorites", labels)

        self.window.current_mod_favorites = {"combat.pak"}
        self.window._refresh_mod_detail(self.mods[0])
        labels = [button.text() for button in self.window.detail_frame.findChildren(QtWidgets.QPushButton)]
        self.assertIn("Remove from favorites", labels)

    def test_filter_boxes_use_popup_completion_without_inline_autofill(self):
        for box in (self.window.search_box, self.window.label_filter_box):
            self.assertEqual(box.insertPolicy(), QtWidgets.QComboBox.NoInsert)
            completer = box.completer()
            self.assertEqual(completer.completionMode(), QtWidgets.QCompleter.PopupCompletion)
            self.assertEqual(completer.filterMode(), QtCore.Qt.MatchContains)
            self.assertEqual(completer.caseSensitivity(), QtCore.Qt.CaseInsensitive)

    def test_tab_completes_filter_text_to_available_option(self):
        line_edit = self.window.search_box.lineEdit()
        line_edit.setText("bat")
        event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Tab, QtCore.Qt.NoModifier)

        self.assertTrue(self.window.eventFilter(line_edit, event))
        self.assertEqual(line_edit.text(), "combat.pak")

    def test_tab_without_text_or_match_leaves_input_unchanged(self):
        line_edit = self.window.search_box.lineEdit()
        event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Tab, QtCore.Qt.NoModifier)

        line_edit.setText("zzz")
        self.assertFalse(self.window.eventFilter(line_edit, event))
        self.assertEqual(line_edit.text(), "zzz")

        line_edit.setText("")
        self.assertFalse(self.window.eventFilter(line_edit, event))
        self.assertEqual(line_edit.text(), "")

    def test_label_edit_suggests_available_labels_without_inline_autofill(self):
        completer = self.window.label_edit.completer()

        self.assertIsNotNone(completer)
        self.assertEqual(completer.completionMode(), QtWidgets.QCompleter.PopupCompletion)
        self.assertEqual(completer.filterMode(), QtCore.Qt.MatchContains)
        self.assertEqual(completer.caseSensitivity(), QtCore.Qt.CaseInsensitive)
        self.assertEqual(self.window.label_edit_model.stringList(), ["combat"])

    def test_tab_completes_label_edit_to_available_label(self):
        self.window.label_edit.setText("bat")
        event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Tab, QtCore.Qt.NoModifier)

        self.assertTrue(self.window.eventFilter(self.window.label_edit, event))
        self.assertEqual(self.window.label_edit.text(), "combat")

    def test_tab_in_label_edit_without_match_leaves_input_unchanged(self):
        event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Tab, QtCore.Qt.NoModifier)

        self.window.label_edit.setText("zzz")
        self.assertFalse(self.window.eventFilter(self.window.label_edit, event))
        self.assertEqual(self.window.label_edit.text(), "zzz")

        self.window.label_edit.setText("")
        self.assertFalse(self.window.eventFilter(self.window.label_edit, event))
        self.assertEqual(self.window.label_edit.text(), "")

    def test_enter_applies_filter_with_typed_partial_text(self):
        self.window.search_box.setCurrentText("co")
        item_count = self.window.search_box.count()

        with patch.object(self.window, "refresh_mods") as refresh_mods:
            self.window.search_box.lineEdit().returnPressed.emit()

        self.assertEqual(self.window.search_var.get(), "co")
        self.assertEqual(self.window.search_box.currentText(), "co")
        self.assertEqual(self.window.search_box.count(), item_count)
        self.assertEqual(self.window.mod_page.get(), 1)
        refresh_mods.assert_called_once_with()

    def test_view_args_and_clear_search_update_filter_state(self):
        self.window.mod_page.set(3)
        self.window.search_var.set("ui")
        self.window.label_filter_var.set("combat")

        self.assertEqual(self.window._view_args(), (3, "combat", "ui", "default"))

        with patch.object(self.window, "refresh_mods") as refresh_mods:
            self.window._mods_clear()

        self.assertEqual(self.window.mod_page.get(), 1)
        self.assertEqual(self.window.search_var.get(), "")
        self.assertEqual(self.window.label_filter_var.get(), "")
        refresh_mods.assert_called_once_with()

    def test_order_control_restores_default_and_created_date_modes(self):
        with patch.object(self.window, "refresh_mods") as refresh_mods, patch("mod_manager.ui.app.save_config") as save_config:
            self.window._set_mod_order("Created date")

        self.assertEqual(self.window.order_var.get(), "Created date")
        self.assertEqual(self.window._view_args()[3], "created_date")
        refresh_mods.assert_called_once_with()
        save_config.assert_called_once_with(self.window.cfg)

        with patch.object(self.window, "refresh_mods"):
            self.window._set_mod_order("Default")

        self.assertEqual(self.window._view_args()[3], "default")

        with patch.object(self.window, "refresh_mods") as refresh_mods, patch("mod_manager.ui.app.save_config"):
            self.window._sort_mods_by_section(2)

        self.assertEqual(self.window.mod_sort_key, "label")
        self.assertEqual(self.window.order_box.currentText(), "Label")
        self.assertEqual(self.window._view_args()[3], "label")
        refresh_mods.assert_called_once_with()

        with patch.object(self.window, "refresh_mods"), patch("mod_manager.ui.app.save_config"):
            self.window._toggle_mod_order_direction()

        self.assertEqual(self.window._view_args()[3], "-label")

        with patch.object(self.window, "refresh_mods") as refresh_mods, patch("mod_manager.ui.app.save_config"):
            self.window._sort_mods_by_section(2)

        self.assertEqual(self.window._view_args()[3], "label")
        refresh_mods.assert_called_once_with()

        self.window.order_box.setCurrentText("Default")
        self.window.mod_sort_key = "default"
        self.window.mod_sort_reverse = True
        with patch.object(self.window, "refresh_mods") as refresh_mods, patch("mod_manager.ui.app.save_config"):
            self.window._activate_mod_order(self.window.order_box.currentIndex())

        self.assertEqual(self.window._view_args()[3], "default")
        refresh_mods.assert_called_once_with()

    def test_clicking_same_sort_column_twice_toggles_direction(self):
        with patch.object(self.window, "refresh_mods"), patch("mod_manager.ui.app.save_config"):
            self.window._sort_mods_by_section(1)

        self.assertEqual(self.window._view_args()[3], "name")

        with patch.object(self.window, "refresh_mods"), patch("mod_manager.ui.app.save_config"):
            self.window._sort_mods_by_section(1)

        self.assertEqual(self.window._view_args()[3], "-name")

        with patch.object(self.window, "refresh_mods"), patch("mod_manager.ui.app.save_config"):
            self.window._sort_mods_by_section(1)

        self.assertEqual(self.window._view_args()[3], "name")

    def test_selecting_same_order_option_twice_toggles_direction(self):
        with patch.object(self.window, "refresh_mods"), patch("mod_manager.ui.app.save_config"):
            self.window._set_mod_order("Name")

        self.assertEqual(self.window._view_args()[3], "name")

        with patch.object(self.window, "refresh_mods"), patch("mod_manager.ui.app.save_config"):
            self.window._set_mod_order("Name")

        self.assertEqual(self.window._view_args()[3], "-name")

    def test_tile_view_uses_same_model_and_label_button_toggles_filter(self):
        with patch("mod_manager.ui.app.save_config") as save_config:
            self.window._set_view_mode("tiles")

        self.assertEqual(self.window.mods_stack.currentWidget(), self.window.tile_splitter)
        self.assertEqual(self.window.tiles_view.model(), self.window.mods_model)
        self.assertTrue(self.window.view_tiles_button.isChecked())
        self.assertFalse(self.window.view_list_button.isChecked())
        self.assertEqual(self.window.tile_delegate._label_badge_text("123456789"), "12345678")
        self.assertEqual(self.window.tile_delegate._label_badge_text("-"), "")
        metrics = QtGui.QFontMetrics(self.window.tiles_view.font())
        long_name = "very-long-mod-name-that-needs-one-line.pak"
        elided = self.window.tile_delegate._elided_mod_name(metrics, long_name, 48)
        self.assertNotEqual(elided, long_name)
        self.assertLessEqual(self.window.tile_delegate.sizeHint(QtWidgets.QStyleOptionViewItem(), self.window.mods_model.index(0, 0)).height(), 198)
        save_config.assert_called()

        with patch.object(self.window, "refresh_mods") as refresh_mods:
            self.window._toggle_label_filter("combat")

        self.assertEqual(self.window.label_filter_var.get(), "combat")
        self.assertEqual(self.window.mod_page.get(), 1)
        refresh_mods.assert_called_once_with()

        with patch.object(self.window, "refresh_mods") as refresh_mods:
            self.window._toggle_label_filter("combat")

        self.assertEqual(self.window.label_filter_var.get(), "")
        refresh_mods.assert_called_once_with()

    def test_tile_tooltips_show_full_text_only_when_badges_are_truncated(self):
        long_mod = self.mod_item("very-long-mod-name-that-needs-one-line.pak")
        self.window.mods_model.set_data([long_mod], {long_mod.name: "longlabelname"}, {})
        option = QtWidgets.QStyleOptionViewItem()
        option.font = self.window.tiles_view.font()
        option.rect = QtCore.QRect(0, 0, 168, 198)
        index = self.window.mods_model.index(0, 0)
        metrics = QtGui.QFontMetrics(option.font)
        rect = self.window.tile_delegate._content_rect(option)
        image_rect = self.window.tile_delegate._image_rect(rect)
        label_rect = self.window.tile_delegate._label_badge_rect(rect, metrics, "longlabe")
        name_rect = self.window.tile_delegate._name_badge_rect(rect, image_rect)

        self.assertEqual(self.window.tile_delegate._tooltip_for_pos(option, index, label_rect.center()), "longlabelname")
        self.assertEqual(self.window.tile_delegate._tooltip_for_pos(option, index, name_rect.center()), long_mod.name)

        self.window.mods_model.set_data([self.mod_item("short.pak")], {"short.pak": "short"}, {})
        short_index = self.window.mods_model.index(0, 0)
        self.assertEqual(self.window.tile_delegate._tooltip_for_pos(option, short_index, label_rect.center()), "")
        self.assertEqual(self.window.tile_delegate._tooltip_for_pos(option, short_index, name_rect.center()), "")

    def test_tile_label_badge_click_toggles_label_filter(self):
        self.window._set_view_mode("tiles")
        option = QtWidgets.QStyleOptionViewItem()
        option.font = self.window.tiles_view.font()
        option.rect = QtCore.QRect(0, 0, 168, 198)
        index = self.window.mods_model.index(0, 0)
        rect = self.window.tile_delegate._content_rect(option)
        metrics = QtGui.QFontMetrics(option.font)
        label_pos = self.window.tile_delegate._label_badge_rect(rect, metrics, "combat").center()
        event = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonPress,
            QtCore.QPointF(label_pos),
            QtCore.Qt.LeftButton,
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier,
        )

        with patch.object(self.window.tiles_view, "indexAt", return_value=index), patch.object(
            self.window.tiles_view, "visualRect", return_value=option.rect
        ), patch.object(self.window, "refresh_mods") as refresh_mods:
            handled = self.window.eventFilter(self.window.tiles_view.viewport(), event)

        self.assertTrue(handled)
        self.assertEqual(self.window.label_filter_var.get(), "combat")
        refresh_mods.assert_called_once_with()

        with patch.object(self.window.tiles_view, "indexAt", return_value=index), patch.object(
            self.window.tiles_view, "visualRect", return_value=option.rect
        ), patch.object(self.window, "refresh_mods") as refresh_mods:
            handled = self.window.eventFilter(self.window.tiles_view.viewport(), event)

        self.assertTrue(handled)
        self.assertEqual(self.window.label_filter_var.get(), "")
        refresh_mods.assert_called_once_with()

    def test_double_click_toggles_mods_in_list_and_tile_views(self):
        with patch.object(self.window, "_toggle_selected_mods") as toggle:
            self.window.mods_table.doubleClicked.emit(self.window.mods_model.index(0, 0))
        toggle.assert_called_once_with()

        with patch.object(self.window, "_toggle_selected_mods") as toggle:
            self.window._set_view_mode("tiles")
            self.window.tiles_view.doubleClicked.emit(self.window.mods_model.index(0, 0))
        toggle.assert_called_once_with()

    def test_detail_panel_clears_nested_rows_and_keeps_image_above_text(self):
        self.window._set_view_mode("tiles")
        self.window._refresh_mod_detail(self.mods[0])
        self.window._refresh_mod_detail(self.mods[1])

        texts = self.widget_texts(self.window.detail_frame)
        self.assertEqual(texts.count("Name"), 1)
        self.assertIn("ui.pak", texts)
        self.assertNotIn("combat.pak", texts)
        self.assertEqual(self.window.detail_layout.alignment(), QtCore.Qt.AlignTop)

    def test_single_mod_detail_shows_state_action_button(self):
        self.window._refresh_mod_detail(self.mods[0])
        texts = self.widget_texts(self.window.detail_frame)
        self.assertIn("Action", texts)
        self.assertIn("Uninstall", texts)
        self.assertNotIn("State", texts)

        with patch.object(self.window, "_toggle_selected_indexes") as toggle:
            buttons = [widget for widget in self.window.detail_frame.findChildren(QtWidgets.QPushButton) if widget.text() == "Uninstall"]
            self.assertEqual(len(buttons), 1)
            buttons[0].click()

        toggle.assert_called_once_with([1])

    def test_single_mod_detail_shows_created_date_with_last_managed(self):
        self.window.current_mod_records["combat.pak"]["created_date"] = "2026-01-01 09:00:00"
        self.assertTrue(self.window._dates_fit_on_one_row("2026-01-01 10:00:00", "2026-01-01 09:00:00", 900))
        self.assertFalse(self.window._dates_fit_on_one_row("2026-01-01 10:00:00", "2026-01-01 09:00:00", 180))

        self.window._refresh_mod_detail(self.mods[0])
        texts = self.widget_texts(self.window.detail_frame)
        self.assertIn("Last managed", texts)
        self.assertIn("2026-01-01 10:00:00", texts)
        self.assertIn("Created", texts)
        self.assertIn("2026-01-01 09:00:00", texts)

    def test_multi_select_detail_shows_installed_counts_and_options(self):
        self.window._set_view_mode("tiles")
        self.select_mod_rows(0, 1)
        self.window._refresh_selected_detail()

        texts = self.widget_texts(self.window.detail_frame)
        self.assertIn("2 mods selected", texts)
        self.assertIn("Installed", texts)
        self.assertIn("Not installed", texts)
        self.assertIn("1", texts)
        self.assertIn("Install 1", texts)
        self.assertIn("Uninstall 1", texts)
        self.assertIn("Toggle selected", texts)

    def test_label_filter_refresh_updates_detail_once_without_intermediate_multi_panel(self):
        self.window._set_view_mode("tiles")
        with patch.object(self.window, "_refresh_multi_detail") as multi_detail, patch.object(
            self.window, "_refresh_mod_detail", wraps=self.window._refresh_mod_detail
        ) as mod_detail:
            self.window._toggle_label_filter("combat")

        multi_detail.assert_not_called()
        self.assertEqual(mod_detail.call_count, 1)

    def test_tile_zoom_updates_size_and_saves_config(self):
        self.window._set_view_mode("tiles")
        self.window.cfg["tile_size"] = 140

        with patch("mod_manager.ui.app.save_config") as save_config:
            result = self.window._zoom_tiles(1)

        self.assertEqual(result, "break")
        self.assertEqual(self.window.cfg["tile_size"], 152)
        save_config.assert_called_once_with(self.window.cfg)

    def test_install_uninstall_and_toggle_selected_mods_dispatch_gui_options(self):
        self.window._run_action = self.run_action_inline
        self.window.mod_page.set(2)
        self.window.search_var.set("pak")
        self.window.label_filter_var.set("combat")

        with patch("mod_manager.ui.app.apply_mods_page", return_value=(2, 3, 1)) as apply_mods, patch.object(
            self.window, "refresh_mods"
        ) as refresh_mods, patch.object(self.window, "refresh_presets") as refresh_presets:
            self.window._install_page()

        apply_mods.assert_called_once_with(self.window.cfg, 2, "combat", "pak", "default", False, True)
        self.assertEqual(self.window.context.status_text, "Installed 2/3 on page 2. Errors: 1.")
        refresh_mods.assert_called_once_with()
        refresh_presets.assert_called_once_with()

        self.select_mod_rows(0, 1)
        with patch("mod_manager.ui.app.toggle_mods_by_indexes", return_value="Toggled") as toggle_mods, patch.object(
            self.window, "refresh_mods"
        ) as refresh_mods, patch.object(self.window, "refresh_presets"):
            self.window._toggle_selected_mods()

        toggle_mods.assert_called_once_with(self.mods, [1, 2], True)
        refresh_mods.assert_called_once_with(["combat.pak", "ui.pak"])
        self.assertEqual(self.window.context.status_text, "Toggled")

    def test_mod_selection_buttons_are_enabled_only_with_selection(self):
        self.window.mods_table.selectionModel().clearSelection()
        self.window._update_mod_selection_actions()
        self.assertTrue(self.window.mod_selection_widgets)
        self.assertTrue(all(not button.isEnabled() for button in self.window.mod_selection_widgets))

        self.select_mod_rows(0)
        self.assertTrue(all(button.isEnabled() for button in self.window.mod_selection_widgets))

    def test_source_and_destination_rows_select_paths_in_explorer(self):
        self.window._refresh_mod_detail(self.mods[0])
        buttons = [widget for widget in self.window.detail_frame.findChildren(QtWidgets.QPushButton) if widget.text() in {str(self.mods[0].src), str(self.mods[0].dest)}]
        self.assertEqual(len(buttons), 2)

        with patch("mod_manager.ui.app.select_in_explorer") as select_in_explorer:
            buttons[0].click()
            buttons[1].click()

        select_in_explorer.assert_any_call(self.mods[0].src)
        select_in_explorer.assert_any_call(self.mods[0].dest)

    def test_tile_splitter_sizes_are_saved_and_restored(self):
        self.window.tile_splitter.setSizes([420, 240])
        self.window._save_tile_splitter_sizes()

        saved = self.window.tile_splitter.sizes()
        self.assertEqual(self.window.cfg["_tile_list_width"], saved[0])
        self.assertEqual(self.window.cfg["_tile_detail_width"], saved[1])

        self.window.tile_splitter.setSizes([120, 520])
        self.window._restore_tile_splitter_sizes()
        self.assertEqual(self.window.tile_splitter.sizes(), saved)

    def test_detail_image_is_after_text_and_uses_full_panel_width(self):
        image_path = _FAKE_DROP / "preview.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        pixmap = QtGui.QPixmap(800, 1600)
        pixmap.fill(QtGui.QColor("red"))
        pixmap.save(str(image_path), "PNG")
        self.window.detail_scroll.resize(300, 500)
        self.qt_app.processEvents()

        with patch("mod_manager.ui.app.mod_image_path", return_value=image_path):
            self.window._refresh_mod_detail(self.mods[0])

        image_labels = [
            widget
            for widget in self.window.detail_frame.findChildren(QtWidgets.QLabel)
            if widget.pixmap() is not None and not widget.pixmap().isNull()
        ]
        self.assertEqual(len(image_labels), 1)
        image = image_labels[0]
        self.assertEqual(image.alignment(), QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        self.assertEqual(image.sizePolicy().horizontalPolicy(), QtWidgets.QSizePolicy.Expanding)
        target_size = self.window._detail_image_target_size(image)
        self.assertLessEqual(image.pixmap().width(), target_size.width())
        self.assertLessEqual(image.pixmap().height(), target_size.height())
        self.assertEqual(image.minimumWidth(), 0)
        image.update_scaled_pixmap(QtCore.QSize(240, 120))
        self.assertLessEqual(image.pixmap().width(), 240)
        self.assertLessEqual(image.pixmap().height(), 120)
        image_index = self.window.detail_layout.indexOf(image)
        self.assertGreater(image_index, 3)

    def test_action_buttons_and_settings_fields_do_not_expand_to_full_width(self):
        self.assertEqual(self.window.label_edit.sizePolicy().horizontalPolicy(), QtWidgets.QSizePolicy.Fixed)
        self.assertLessEqual(self.window.label_edit.maximumWidth(), 200)
        self.assertEqual(self.window.mod_selection_widgets[0].sizePolicy().horizontalPolicy(), QtWidgets.QSizePolicy.Fixed)

    def test_dialog_fields_expand_to_available_width(self):
        self.assertEqual(
            self.window.setting_widgets["page_size"].sizePolicy().horizontalPolicy(),
            QtWidgets.QSizePolicy.Fixed,
        )
        presets_header = self.window.presets_table.horizontalHeader()
        self.assertFalse(presets_header.stretchLastSection())
        self.assertEqual(presets_header.sectionResizeMode(0), QtWidgets.QHeaderView.Stretch)
        self.assertEqual(presets_header.sectionResizeMode(1), QtWidgets.QHeaderView.ResizeToContents)
        self.assertEqual(presets_header.sectionResizeMode(2), QtWidgets.QHeaderView.ResizeToContents)
        self.assertEqual(presets_header.sectionResizeMode(3), QtWidgets.QHeaderView.ResizeToContents)
        self.assertFalse(presets_header.highlightSections())
        self.assertTrue(self.window.broken_table.horizontalHeader().stretchLastSection())

    def test_settings_font_family_uses_system_font_select(self):
        font_widget = self.window.setting_widgets["gui_font_family"]

        self.assertIsInstance(font_widget, QtWidgets.QComboBox)
        self.assertFalse(font_widget.isEditable())
        self.assertGreater(font_widget.count(), 0)
        self.assertEqual(font_widget.itemText(0), "")

    def test_settings_theme_uses_restart_only_select(self):
        theme_widget = self.window.setting_widgets["gui_theme"]

        self.assertIsInstance(theme_widget, QtWidgets.QComboBox)
        self.assertEqual([theme_widget.itemText(i) for i in range(theme_widget.count())], ["system", "light", "dark"])
        self.assertEqual(theme_widget.currentText(), "system")

        with patch.object(self.window, "_update_mod_order_direction_button") as update_icon:
            self.window.changeEvent(QtCore.QEvent(QtCore.QEvent.PaletteChange))

        update_icon.assert_not_called()

    def test_icon_buttons_have_palette_aware_icons_and_tooltips(self):
        icon_buttons = [
            widget
            for widget in self.window.action_widgets
            if isinstance(widget, QtWidgets.QPushButton) and not widget.text()
        ]

        self.assertGreaterEqual(len(icon_buttons), 10)
        for button in icon_buttons:
            self.assertFalse(button.icon().isNull(), button.accessibleName())
            self.assertTrue(button.toolTip())
            self.assertTrue(button.accessibleName())
            self.assertEqual(button.iconSize(), QtCore.QSize(tokens.ICON_SIZE, tokens.ICON_SIZE))
            self.assertEqual(button.property("variant"), "acrylic")

        self.assertEqual(self.window.order_direction_button.property("variant"), "acrylic")
        self.assertFalse(self.window.order_direction_button.icon().isNull())

        self.window._refresh_mod_detail(self.mods[0])
        uninstall = [widget for widget in self.window.detail_frame.findChildren(QtWidgets.QPushButton) if widget.text() == "Uninstall"][0]
        self.assertFalse(uninstall.icon().isNull())
        self.assertTrue(uninstall.toolTip())
        import_button = self.window.mods_actions.button("import_files")
        self.assertFalse(import_button.icon().isNull())
        self.assertEqual(import_button.toolTip(), "Import mod files")
        self.assertEqual(import_button.accessibleName(), "Import mod files")

    def test_save_settings_converts_numeric_values_and_refreshes_ui(self):
        self.window._run_action = self.run_action_inline
        self.window._open_settings_dialog()
        self.window.setting_widgets["page_size"].setText("25")
        self.window.setting_widgets["ui_scale_percent"].setText("150")
        self.window.setting_widgets["mod_view_mode"].setCurrentText("tiles")
        self.window.setting_widgets["tile_size"].setText("188")
        font_widget = self.window.setting_widgets["gui_font_family"]
        if font_widget.count() > 1:
            font_widget.setCurrentIndex(1)
        selected_font = font_widget.currentText()

        with patch("mod_manager.storage.save_config") as save_config, patch.object(self.window, "refresh_all") as refresh_all:
            self.window._save_settings()

        self.assertEqual(self.window.cfg["page_size"], 25)
        self.assertEqual(self.window.cfg["mod_view_mode"], "tiles")
        self.assertEqual(self.window.cfg["tile_size"], 188)
        self.assertEqual(self.window.cfg["gui_font_family"], selected_font)
        save_config.assert_called_once()
        refresh_all.assert_called_once_with()
        self.assertEqual(self.window.context.status_text, "Settings saved.")
        self.assertFalse(self.window.settings_dialog.isVisible())

    def test_game_profile_dialog_owns_the_per_game_fields(self):
        with patch.object(QtWidgets.QDialog, "exec", return_value=QtWidgets.QDialog.Accepted):
            values = self.window._game_profile_values({
                "name": "My Game",
                "mod_extensions": ".pak,.utoc",
                "mod_recursive_scan": True,
            })

        self.assertEqual(values["mod_extensions"], ".pak,.utoc")
        self.assertEqual(values["mod_recursive_scan"], True)
        for key in ("mods_source_dir", "game_mods_dir", "link_prefix"):
            self.assertIn(key, values, key)

    def test_game_profile_dialog_offers_the_install_method_and_grouping(self):
        dialog = GameProfileDialog(self.window, {"name": "My Game", "install_mode": "copy"})
        try:
            method = dialog.form.fields["install_mode"]
            self.assertIsInstance(method, QtWidgets.QComboBox)
            self.assertEqual([method.itemText(i) for i in range(method.count())], ["link", "copy"])
            self.assertEqual(method.currentText(), "copy")
            self.assertIsInstance(dialog.form.fields["mod_group_extensions"], QtWidgets.QLineEdit)

            dialog.form.fields["mod_group_extensions"].setText(".pak,.utoc,.ucas")
            with patch.object(QtWidgets.QDialog, "exec", return_value=QtWidgets.QDialog.Accepted):
                values = dialog.values()
        finally:
            dispose(dialog)

        self.assertEqual(values["install_mode"], "copy")
        self.assertEqual(values["mod_group_extensions"], ".pak,.utoc,.ucas")

    def test_save_theme_setting_applies_live_without_restart(self):
        self.window._run_action = self.run_action_inline
        self.window._open_settings_dialog()
        self.window.setting_widgets["gui_theme"].setCurrentText("dark")

        with patch.object(self.window, "_apply_button_style") as apply_style:
            self.window._save_settings()

        self.assertEqual(self.window.cfg["gui_theme"], "dark")
        apply_style.assert_called_once()
        self.assertEqual(self.window.context.status_text, "Settings saved.")

    def test_accent_color_mode_defaults_to_system_with_color_row_hidden(self):
        self.window._run_action = self.run_action_inline
        self.window._open_settings_dialog()

        self.assertEqual(self.window.setting_widgets["gui_accent_color_mode"].currentText(), "system")
        self.assertEqual(self.window.setting_widgets["gui_accent_color"].text(), "#2563eb")
        self.assertFalse(self.window.settings_form.is_row_visible("gui_accent_color"))

    def test_selecting_custom_accent_mode_reveals_color_row_and_updates_preview(self):
        self.window._run_action = self.run_action_inline
        self.window._open_settings_dialog()

        self.window.setting_widgets["gui_accent_color_mode"].setCurrentText("custom")

        self.assertTrue(self.window.settings_form.is_row_visible("gui_accent_color"))
        self.assertEqual(self.window._settings_accent_color().name(), "#2563eb")

    def test_choose_accent_color_updates_field_and_preview(self):
        self.window._run_action = self.run_action_inline
        self.window._open_settings_dialog()
        self.window.setting_widgets["gui_accent_color_mode"].setCurrentText("custom")

        with patch("mod_manager.ui.dialogs.prompts.choose_color", return_value=QtGui.QColor("#ff0000")):
            self.window._choose_color("gui_accent_color")

        self.assertEqual(self.window.setting_widgets["gui_accent_color"].text(), "#ff0000")
        self.assertEqual(self.window._settings_accent_color().name(), "#ff0000")
        self.assertFalse(self.window.accent_preview_badge.icon().isNull())

    def test_save_custom_accent_color_applies_live(self):
        self.window._run_action = self.run_action_inline
        self.window._open_settings_dialog()
        self.window.setting_widgets["gui_accent_color_mode"].setCurrentText("custom")
        self.window.setting_widgets["gui_accent_color"].setText("#ff0000")

        with patch("mod_manager.storage.save_config"):
            self.window._save_settings()

        self.assertEqual(self.window.cfg["gui_accent_color_mode"], "custom")
        self.assertEqual(self.window.cfg["gui_accent_color"], "#ff0000")
        self.assertEqual(self.window.context.status_text, "Settings saved.")
        self.assertEqual(self.window._theme_accent.name(), "#ff0000")

    def test_clicking_accent_preview_badge_toggles_color_mode(self):
        self.window._run_action = self.run_action_inline
        self.window._open_settings_dialog()

        self.assertEqual(self.window.setting_widgets["gui_accent_color_mode"].currentText(), "system")
        self.assertFalse(self.window.settings_form.is_row_visible("gui_accent_color"))

        self.window.accent_preview_badge.click()
        self.assertEqual(self.window.setting_widgets["gui_accent_color_mode"].currentText(), "custom")
        self.assertTrue(self.window.settings_form.is_row_visible("gui_accent_color"))

        self.window.accent_preview_badge.click()
        self.assertEqual(self.window.setting_widgets["gui_accent_color_mode"].currentText(), "system")
        self.assertFalse(self.window.settings_form.is_row_visible("gui_accent_color"))

    def test_save_settings_without_accent_change_does_not_require_restart(self):
        self.window._run_action = self.run_action_inline
        self.window._open_settings_dialog()
        self.window.setting_widgets["page_size"].setText("25")

        with patch("mod_manager.storage.save_config"):
            self.window._save_settings()

        self.assertEqual(self.window.context.status_text, "Settings saved.")

    def test_text_color_mode_defaults_to_system_with_color_row_hidden(self):
        self.window._run_action = self.run_action_inline
        self.window._open_settings_dialog()

        self.assertEqual(self.window.setting_widgets["gui_text_color_mode"].currentText(), "system")
        self.assertEqual(self.window.setting_widgets["gui_text_color"].text(), "#111827")
        self.assertFalse(self.window.settings_form.is_row_visible("gui_text_color"))

    def test_clicking_text_preview_badge_toggles_color_mode(self):
        self.window._run_action = self.run_action_inline
        self.window._open_settings_dialog()

        self.window.text_preview_badge.click()
        self.assertEqual(self.window.setting_widgets["gui_text_color_mode"].currentText(), "custom")
        self.assertTrue(self.window.settings_form.is_row_visible("gui_text_color"))

        self.window.text_preview_badge.click()
        self.assertEqual(self.window.setting_widgets["gui_text_color_mode"].currentText(), "system")
        self.assertFalse(self.window.settings_form.is_row_visible("gui_text_color"))

    def test_choose_text_color_updates_field_and_preview(self):
        self.window._run_action = self.run_action_inline
        self.window._open_settings_dialog()
        self.window.setting_widgets["gui_text_color_mode"].setCurrentText("custom")

        with patch("mod_manager.ui.dialogs.prompts.choose_color", return_value=QtGui.QColor("#00ff00")):
            self.window._choose_color("gui_text_color")

        self.assertEqual(self.window.setting_widgets["gui_text_color"].text(), "#00ff00")
        self.assertEqual(self.window._settings_text_color().name(), "#00ff00")
        self.assertIn("#00ff00", self.window.text_preview_badge.styleSheet())

    def test_save_custom_text_color_applies_live(self):
        self.window._run_action = self.run_action_inline
        self.window._open_settings_dialog()
        self.window.setting_widgets["gui_text_color_mode"].setCurrentText("custom")
        self.window.setting_widgets["gui_text_color"].setText("#00ff00")

        with patch("mod_manager.storage.save_config"):
            self.window._save_settings()

        self.assertEqual(self.window.cfg["gui_text_color_mode"], "custom")
        self.assertEqual(self.window.cfg["gui_text_color"], "#00ff00")
        self.assertEqual(self.window.context.status_text, "Settings saved.")
        self.assertEqual(self.window._theme_button_text.name(), "#00ff00")

    def test_system_appearance_change_refreshes_theme_when_following_system(self):
        self.window._run_action = self.run_action_inline
        with patch.object(self.window, "_apply_button_style") as apply_style:
            self.window._on_system_appearance_changed()

        apply_style.assert_called_once()

    def test_system_appearance_change_ignored_while_applying_theme(self):
        self.window._applying_theme = True
        with patch.object(self.window, "_refresh_theme") as refresh_theme:
            self.window._on_system_appearance_changed()

        refresh_theme.assert_not_called()
        self.window._applying_theme = False

    def test_preset_and_broken_actions_dispatch_selected_rows(self):
        self.window._run_action = self.run_action_inline
        self.window._open_presets_dialog()
        preset_selection = self.window.presets_table.selectionModel()
        preset_selection.select(self.window.presets_model.index(0, 0), QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
        preset_selection.select(self.window.presets_model.index(1, 0), QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)

        with patch("mod_manager.ui.app.toggle_presets_by_names", return_value=("Preset toggled", [], False)) as toggle, patch.object(
            self.window, "refresh_mods"
        ), patch.object(self.window, "refresh_presets"):
            self.window._toggle_selected_presets()

        toggle.assert_called_once_with(self.window.cfg, ["core", "ui"], {"combat.pak"}, True)
        self.assertEqual(self.window.context.status_text, "Preset toggled")
        self.assertFalse(self.window.presets_dialog.isVisible())

        self.window._open_broken_dialog()
        broken_selection = self.window.broken_table.selectionModel()
        broken_selection.select(self.window.broken_model.index(0, 0), QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
        with patch("mod_manager.ui.app.deactivate_mod", return_value=(True, "OK")) as deactivate, patch.object(self.window, "refresh_broken"):
            self.window._remove_selected_broken()

        deactivate.assert_called_once_with(self.broken[0])
        self.assertEqual(self.window.context.status_text, "Removed broken links: 1")
        self.assertFalse(self.window.broken_dialog.isVisible())

    def test_preset_double_click_toggles_clicked_preset(self):
        self.window._run_action = self.run_action_inline
        self.window._open_presets_dialog()
        with patch("mod_manager.ui.app.toggle_presets_by_names", return_value=("Preset toggled", [], False)) as toggle, patch.object(
            self.window, "refresh_mods"
        ), patch.object(self.window, "refresh_presets"):
            self.window.presets_table.doubleClicked.emit(self.window.presets_model.index(1, 0))

        toggle.assert_called_once_with(self.window.cfg, ["ui"], {"combat.pak"}, True)
        self.assertEqual(self.window.context.status_text, "Preset toggled")
        self.assertFalse(self.window.presets_dialog.isVisible())

    def test_preset_save_and_delete_keep_dialog_open(self):
        self.window._run_action = self.run_action_inline
        self.window._open_presets_dialog()
        self.window.preset_name.setText("new")

        with patch("mod_manager.ui.app.save_preset_from_installed", return_value=(True, "Saved")):
            self.window._save_preset()

        self.assertTrue(self.window.presets_dialog.isVisible())

        selection = self.window.presets_table.selectionModel()
        selection.select(self.window.presets_model.index(0, 0), QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
        with patch("mod_manager.ui.app.delete_presets_by_names", return_value=(1, [])) as delete_presets:
            self.window._delete_selected_presets()

        delete_presets.assert_called_once_with(["core"])
        self.assertTrue(self.window.presets_dialog.isVisible())
        self.window.presets_dialog.close()

    def test_refresh_presets_suspends_table_updates_and_preserves_selection(self):
        selection = self.window.presets_table.selectionModel()
        selection.select(self.window.presets_model.index(0, 0), QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)

        with patch.object(self.window.presets_table, "setUpdatesEnabled", wraps=self.window.presets_table.setUpdatesEnabled) as updates:
            self.window.refresh_presets()

        self.assertEqual([call.args[0] for call in updates.call_args_list], [False, True])
        self.assertEqual(self.window._selected_rows(self.window.presets_table), [0])

    def test_import_paths_filters_supported_mods_and_reports_counts(self):
        self.window._run_action = self.run_action_inline
        self.window.current_mod_items = [self.mods[0]]

        with patch("mod_manager.ui.app.is_mod_file", side_effect=lambda path, _cfg: path.suffix == ".pak"), patch(
            "mod_manager.ui.dialogs.prompts.choose_import_conflict",
            return_value="replace",
        ) as question, patch("mod_manager.ui.app._run_import_batch", return_value=(["combat.pak"], ["new.pak"])) as import_batch, patch.object(
            self.window, "refresh_mods"
        ) as refresh_mods:
            self.window._import_paths([_FAKE_DROP / "combat.pak", _FAKE_DROP / "skip.txt", _FAKE_DROP / "new.pak"])

        question.assert_called_once()
        import_batch.assert_called_once()
        self.assertEqual(self.window.context.status_text, "Imported: 1. Skipped: 1.")
        refresh_mods.assert_called_once_with()

    def test_drop_image_on_target_mod_imports_without_picker_and_refreshes_tile(self):
        self.window._run_action = self.run_action_inline
        self.window.current_mod_items = list(self.mods)
        self.window.current_mods_shown = list(self.mods)
        self.window.tile_delegate._pixmaps[("combat.pak", 140)] = QtGui.QPixmap(1, 1)
        image_path = _FAKE_DROP / "new-preview.png"

        with patch("mod_manager.ui.app.is_image_file", return_value=True), patch(
            "mod_manager.ui.app._run_import_batch", return_value=(["combat.pak.png"], [])
        ) as import_batch, patch("mod_manager.ui.app.prompts.choose_item") as picker, patch.object(
            self.window, "refresh_mods"
        ) as refresh_mods:
            self.window._handle_mods_drop([image_path], target_mod_name="combat.pak")

        picker.assert_not_called()
        import_batch.assert_called_once()
        tasks = import_batch.call_args.args[1]
        self.assertEqual(tasks, [("image", image_path, "combat.pak", False)])
        self.assertNotIn(("combat.pak", 140), self.window.tile_delegate._pixmaps)
        refresh_mods.assert_called_once_with(["combat.pak"])

    def test_image_named_after_mod_opens_picker_with_that_mod_preselected(self):
        self.window._run_action = self.run_action_inline

        with patch("mod_manager.ui.app.is_image_file", side_effect=lambda p: p.suffix == ".png"), patch(
            "mod_manager.ui.app.prompts.choose_item", return_value=("ui.pak", True)
        ) as picker, patch("mod_manager.ui.app._run_import_batch", return_value=(["ui.pak.png"], [])) as import_batch, patch.object(
            self.window, "refresh_mods"
        ):
            self.window._import_paths([_FAKE_DROP / "combat.pak.png"])

        picker.assert_called_once()
        self.assertEqual(picker.call_args.args[3], ["combat.pak", "ui.pak"])
        self.assertEqual(picker.call_args.args[4], 0)
        tasks = import_batch.call_args.args[1]
        self.assertEqual(tasks, [("image", _FAKE_DROP / "combat.pak.png", "ui.pak", False)])

    def test_image_dropped_together_with_its_mod_skips_picker(self):
        self.window._run_action = self.run_action_inline

        with patch("mod_manager.ui.app.is_image_file", side_effect=lambda p: p.suffix == ".png"), patch(
            "mod_manager.ui.app.is_mod_file", side_effect=lambda p, _cfg: p.suffix == ".pak"
        ), patch("mod_manager.ui.app.prompts.choose_item") as picker, patch(
            "mod_manager.ui.app._run_import_batch", return_value=(["new.pak", "new.pak.png"], [])
        ) as import_batch, patch.object(self.window, "refresh_mods"):
            self.window._import_paths([_FAKE_DROP / "new.pak", _FAKE_DROP / "new.pak.png"])

        picker.assert_not_called()
        tasks = import_batch.call_args.args[1]
        self.assertIn(("image", _FAKE_DROP / "new.pak.png", "new.pak", False), tasks)
        self.assertIn(("mod", _FAKE_DROP / "new.pak", "", False), tasks)

    def test_drop_position_maps_to_mod_name_in_tile_view(self):
        index = self.window.mods_model.index(1, 0)

        with patch.object(self.window.tiles_view, "indexAt", return_value=index):
            mod_name = self.window._mod_name_at_view_position(self.window.tiles_view.viewport(), QtCore.QPoint(12, 12))

        self.assertEqual(mod_name, "ui.pak")


if __name__ == "__main__":
    unittest.main()
