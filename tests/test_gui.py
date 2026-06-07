from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mod_manager.models import ModItem

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ModuleNotFoundError:
    QtCore = None
    QtGui = None
    QtWidgets = None

_FAKE_SRC = Path(tempfile.gettempdir()) / "mm_test_source"
_FAKE_DEST = Path(tempfile.gettempdir()) / "mm_test_game"
_FAKE_DROP = Path(tempfile.gettempdir()) / "mm_test_drop"
_FAKE_NEW_DEST = Path(tempfile.gettempdir()) / "mm_test_new_game"


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self) -> None:
        self.cfg = {
            "mods_source_dir": str(_FAKE_SRC),
            "game_mods_dir": str(_FAKE_DEST),
            "mod_extensions": ".pak,.utoc",
            "link_prefix": "",
            "page_size": 10,
            "max_mod_name_len": 28,
            "max_preset_name_len": 28,
            "max_label_name_len": 12,
            "button_size_percent": 100,
            "gui_font_family": "",
            "gui_font_size": 10,
            "placeholder_image_col_width": 56,
            "mod_view_mode": "list",
            "tile_size": 140,
            "window_width": 900,
            "window_height": 600,
            "order_var": "Default",
            "mod_sort_key": "d",
            "mod_sort_reverse": False,
            "preset_sort_key": "name",
            "preset_sort_reverse": False,
        }
        self.mods = [
            self.mod_item("combat.pak", installed=True),
            self.mod_item("ui.pak", installed=False),
        ]
        self.presets = {"core": ["combat.pak"], "ui": ["ui.pak"]}
        self.broken = [self.mod_item("missing.pak", installed=True)]
        self.patchers = [
            patch("mod_manager.gui.load_config", return_value=self.cfg),
            patch("mod_manager.gui.save_config"),
            patch("mod_manager.gui.ensure_paths", return_value=True),
            patch("mod_manager.gui.mod_image_path", return_value=None),
            patch("mod_manager.gui.mods_view", return_value=(self.mods, self.mods, 1, 1, {"combat.pak": "combat"})),
            patch(
                "mod_manager.gui.mods_records",
                return_value={"combat.pak": {"last_managed": "2026-01-01 10:00:00"}},
            ),
            patch("mod_manager.gui.presets_view", return_value=(self.presets, list(self.presets), ["core", "ui"], 1, 1)),
            patch(
                "mod_manager.gui.presets_records",
                return_value={"core": {"state": "applied", "last_managed": "2026-01-02 10:00:00"}},
            ),
            patch("mod_manager.gui.list_installed_mods", return_value=[self.mods[0]]),
            patch("mod_manager.gui.list_broken_links", return_value=self.broken),
        ]
        for patcher in self.patchers:
            patcher.start()
        from mod_manager.gui import ModManagerGui

        self.window = ModManagerGui()
        self.window.hide()
        self.qt_app.processEvents()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.qt_app.processEvents()
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
        self.assertEqual(self.window.mods_model.data(self.window.mods_model.index(0, 0)), "[installed] combat.pak")
        self.assertEqual(self.window.mods_model.data(self.window.mods_model.index(0, 1)), "combat")
        self.assertEqual(self.window.presets_model.rowCount(), 2)
        self.assertEqual(self.window.presets_model.data(self.window.presets_model.index(0, 0)), "core")
        self.assertEqual(self.window.presets_model.data(self.window.presets_model.index(0, 1)), "applied")
        self.assertEqual(self.window.broken_model.rowCount(), 1)
        self.assertEqual(self.window.broken_model.data(self.window.broken_model.index(0, 0)), "missing.pak")

    def test_mod_table_stretches_only_name_column(self):
        header = self.window.mods_table.horizontalHeader()

        self.assertFalse(header.stretchLastSection())
        self.assertEqual(header.sectionResizeMode(0), QtWidgets.QHeaderView.Stretch)
        self.assertEqual(header.sectionResizeMode(1), QtWidgets.QHeaderView.ResizeToContents)
        self.assertEqual(header.sectionResizeMode(2), QtWidgets.QHeaderView.ResizeToContents)

    def test_manage_menu_opens_secondary_dialogs(self):
        menu_titles = [action.text() for action in self.window.menuBar().actions()]
        self.assertIn("Manage", menu_titles)
        self.assertEqual(self.window.manage_button.text(), "Menu")
        self.assertIsNotNone(self.window.manage_button.menu())
        self.assertFalse(self.window.manage_button.icon().isNull())
        self.assertEqual([action.text() for action in self.window.manage_button.menu().actions()], ["Presets", "Settings", "Broken links"])

        self.window._open_presets_dialog()
        self.assertTrue(self.window.presets_dialog.isVisible())
        self.window.presets_dialog.close()

        self.window._open_settings_dialog()
        self.assertTrue(self.window.settings_dialog.isVisible())
        self.window.settings_dialog.close()

        self.window._open_broken_dialog()
        self.assertTrue(self.window.broken_dialog.isVisible())
        self.window.broken_dialog.close()

    def test_view_args_and_clear_search_update_filter_state(self):
        self.window.mod_page.set(3)
        self.window.search_var.set("ui")
        self.window.label_filter_var.set("combat")

        self.assertEqual(self.window._view_args(), (3, "combat", "ui", "d"))

        with patch.object(self.window, "refresh_mods") as refresh_mods:
            self.window._mods_clear()

        self.assertEqual(self.window.mod_page.get(), 1)
        self.assertEqual(self.window.search_var.get(), "")
        self.assertEqual(self.window.label_filter_var.get(), "")
        refresh_mods.assert_called_once_with()

    def test_order_control_restores_default_and_created_date_modes(self):
        with patch.object(self.window, "refresh_mods") as refresh_mods, patch("mod_manager.gui.save_config") as save_config:
            self.window._set_mod_order("Created date")

        self.assertEqual(self.window.order_var.get(), "Created date")
        self.assertEqual(self.window._view_args()[3], "cd")
        refresh_mods.assert_called_once_with()
        save_config.assert_called_once_with(self.window.cfg)

        with patch.object(self.window, "refresh_mods"):
            self.window._set_mod_order("Default")

        self.assertEqual(self.window._view_args()[3], "d")

    def test_tile_view_uses_same_model_and_label_button_toggles_filter(self):
        with patch("mod_manager.gui.save_config") as save_config:
            self.window._set_view_mode("tiles")

        self.assertEqual(self.window.mods_stack.currentWidget(), self.window.tile_splitter)
        self.assertEqual(self.window.tiles_view.model(), self.window.mods_model)
        self.assertTrue(self.window.view_tiles_button.isChecked())
        self.assertFalse(self.window.view_list_button.isChecked())
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

        with patch("mod_manager.gui.save_config") as save_config:
            result = self.window._zoom_tiles(1)

        self.assertEqual(result, "break")
        self.assertEqual(self.window.cfg["tile_size"], 152)
        save_config.assert_called_once_with(self.window.cfg)

    def test_install_uninstall_and_toggle_selected_mods_dispatch_gui_options(self):
        self.window._run_action = self.run_action_inline
        self.window.mod_page.set(2)
        self.window.search_var.set("pak")
        self.window.label_filter_var.set("combat")

        with patch("mod_manager.gui.apply_mods_page", return_value=(2, 3, 1)) as apply_mods, patch.object(
            self.window, "refresh_mods"
        ) as refresh_mods, patch.object(self.window, "refresh_presets") as refresh_presets:
            self.window._install_page()

        apply_mods.assert_called_once_with(self.window.cfg, 2, "combat", "pak", "d")
        self.assertEqual(self.window.status_var.get(), "Installed 2/3 on page 2. Errors: 1.")
        refresh_mods.assert_called_once_with()
        refresh_presets.assert_called_once_with()

        self.select_mod_rows(0, 1)
        with patch("mod_manager.gui.toggle_mods_by_indexes", return_value="Toggled") as toggle_mods, patch.object(
            self.window, "refresh_mods"
        ) as refresh_mods, patch.object(self.window, "refresh_presets"):
            self.window._toggle_selected_mods()

        toggle_mods.assert_called_once_with(self.mods, [1, 2])
        refresh_mods.assert_called_once_with(["combat.pak", "ui.pak"])
        self.assertEqual(self.window.status_var.get(), "Toggled")

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

        with patch("mod_manager.gui.select_in_explorer") as select_in_explorer:
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

        with patch("mod_manager.gui.mod_image_path", return_value=image_path):
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
        for key in ("page_size", "mods_source_dir", "game_mods_dir"):
            self.assertEqual(self.window.setting_widgets[key].sizePolicy().horizontalPolicy(), QtWidgets.QSizePolicy.Expanding)
        self.assertEqual(self.window.setting_widgets["mods_source_dir"].maximumWidth(), 16777215)
        self.assertTrue(self.window.presets_table.horizontalHeader().stretchLastSection())
        self.assertTrue(self.window.broken_table.horizontalHeader().stretchLastSection())

    def test_settings_font_family_uses_system_font_select(self):
        font_widget = self.window.setting_widgets["gui_font_family"]

        self.assertIsInstance(font_widget, QtWidgets.QComboBox)
        self.assertFalse(font_widget.isEditable())
        self.assertGreater(font_widget.count(), 0)
        self.assertEqual(font_widget.itemText(0), "")

    def test_icon_buttons_have_palette_aware_icons_and_tooltips(self):
        icon_buttons = [
            widget
            for widget in self.window.action_widgets
            if isinstance(widget, QtWidgets.QPushButton) and not widget.text()
        ]

        self.assertGreaterEqual(len(icon_buttons), 10)
        for button in icon_buttons:
            self.assertFalse(button.icon().isNull())
            self.assertTrue(button.toolTip())
            self.assertTrue(button.accessibleName())
            self.assertEqual(button.iconSize(), QtCore.QSize(18, 18))

        self.window._refresh_mod_detail(self.mods[0])
        uninstall = [widget for widget in self.window.detail_frame.findChildren(QtWidgets.QPushButton) if widget.text() == "Uninstall"][0]
        self.assertFalse(uninstall.icon().isNull())
        self.assertTrue(uninstall.toolTip())
        import_button = [button for button in icon_buttons if button.accessibleName() == "Import files"][0]
        self.assertFalse(import_button.icon().isNull())
        self.assertEqual(import_button.toolTip(), "Import mod files")

    def test_save_settings_converts_numeric_values_and_refreshes_ui(self):
        self.window._run_action = self.run_action_inline
        self.window._open_settings_dialog()
        self.window.setting_widgets["page_size"].setText("25")
        self.window.setting_widgets["ui_scale_percent"].setText("150")
        self.window.setting_widgets["game_mods_dir"].setText(str(_FAKE_NEW_DEST))
        self.window.setting_widgets["mod_extensions"].setText(".pak")
        self.window.setting_widgets["mod_view_mode"].setCurrentText("tiles")
        self.window.setting_widgets["tile_size"].setText("188")
        font_widget = self.window.setting_widgets["gui_font_family"]
        if font_widget.count() > 1:
            font_widget.setCurrentIndex(1)
        selected_font = font_widget.currentText()

        with patch("mod_manager.storage.save_config") as save_config, patch.object(self.window, "refresh_all") as refresh_all:
            self.window._save_settings()

        self.assertEqual(self.window.cfg["page_size"], 25)
        self.assertEqual(self.window.cfg["game_mods_dir"], str(_FAKE_NEW_DEST))
        self.assertEqual(self.window.cfg["mod_extensions"], ".pak")
        self.assertEqual(self.window.cfg["mod_view_mode"], "tiles")
        self.assertEqual(self.window.cfg["tile_size"], 188)
        self.assertEqual(self.window.cfg["gui_font_family"], selected_font)
        save_config.assert_called_once()
        refresh_all.assert_called_once_with()
        self.assertEqual(self.window.status_var.get(), "Settings saved.")
        self.assertFalse(self.window.settings_dialog.isVisible())

    def test_preset_and_broken_actions_dispatch_selected_rows(self):
        self.window._run_action = self.run_action_inline
        self.window._open_presets_dialog()
        preset_selection = self.window.presets_table.selectionModel()
        preset_selection.select(self.window.presets_model.index(0, 0), QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
        preset_selection.select(self.window.presets_model.index(1, 0), QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)

        with patch("mod_manager.gui.toggle_presets_by_indexes", return_value=("Preset toggled", [], False)) as toggle, patch.object(
            self.window, "refresh_mods"
        ), patch.object(self.window, "refresh_presets"):
            self.window._toggle_selected_presets()

        toggle.assert_called_once_with(self.window.cfg, 1, [1, 2], {"combat.pak"})
        self.assertEqual(self.window.status_var.get(), "Preset toggled")
        self.assertFalse(self.window.presets_dialog.isVisible())

        self.window._open_broken_dialog()
        broken_selection = self.window.broken_table.selectionModel()
        broken_selection.select(self.window.broken_model.index(0, 0), QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
        with patch("mod_manager.gui.deactivate_mod", return_value=(True, "OK")) as deactivate, patch.object(self.window, "refresh_broken"):
            self.window._remove_selected_broken()

        deactivate.assert_called_once_with(self.broken[0])
        self.assertEqual(self.window.status_var.get(), "Removed broken links: 1")
        self.assertFalse(self.window.broken_dialog.isVisible())

    def test_preset_double_click_toggles_clicked_preset(self):
        self.window._run_action = self.run_action_inline
        self.window._open_presets_dialog()
        with patch("mod_manager.gui.toggle_presets_by_indexes", return_value=("Preset toggled", [], False)) as toggle, patch.object(
            self.window, "refresh_mods"
        ), patch.object(self.window, "refresh_presets"):
            self.window.presets_table.doubleClicked.emit(self.window.presets_model.index(1, 0))

        toggle.assert_called_once_with(self.window.cfg, 1, [2], {"combat.pak"})
        self.assertEqual(self.window.status_var.get(), "Preset toggled")
        self.assertFalse(self.window.presets_dialog.isVisible())

    def test_preset_save_and_delete_keep_dialog_open(self):
        self.window._run_action = self.run_action_inline
        self.window._open_presets_dialog()
        self.window.preset_name.setText("new")

        with patch("mod_manager.gui.save_preset_from_installed", return_value=(True, "Saved")):
            self.window._save_preset()

        self.assertTrue(self.window.presets_dialog.isVisible())

        selection = self.window.presets_table.selectionModel()
        selection.select(self.window.presets_model.index(0, 0), QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
        with patch("mod_manager.gui.delete_presets_by_indexes", return_value=(1, [])):
            self.window._delete_selected_presets()

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

        with patch("mod_manager.gui.is_mod_file", side_effect=lambda path, _cfg: path.suffix == ".pak"), patch(
            "mod_manager.gui.QtWidgets.QMessageBox.question",
            return_value=QtWidgets.QMessageBox.Yes,
        ) as question, patch("mod_manager.gui._run_import_batch", return_value=(["combat.pak"], ["new.pak"])) as import_batch, patch.object(
            self.window, "refresh_mods"
        ) as refresh_mods:
            self.window._import_paths([_FAKE_DROP / "combat.pak", _FAKE_DROP / "skip.txt", _FAKE_DROP / "new.pak"])

        question.assert_called_once()
        import_batch.assert_called_once()
        self.assertEqual(self.window.status_var.get(), "Imported: 1. Skipped: 1.")
        refresh_mods.assert_called_once_with()

    def test_drop_image_on_target_mod_imports_without_picker_and_refreshes_tile(self):
        self.window._run_action = self.run_action_inline
        self.window.current_mod_items = list(self.mods)
        self.window.current_mods_shown = list(self.mods)
        self.window.tile_delegate._pixmaps[("combat.pak", 140)] = QtGui.QPixmap(1, 1)
        image_path = _FAKE_DROP / "new-preview.png"

        with patch("mod_manager.gui.is_image_file", return_value=True), patch(
            "mod_manager.gui._run_import_batch", return_value=(["combat.pak.png"], [])
        ) as import_batch, patch("mod_manager.gui.QtWidgets.QInputDialog.getItem") as picker, patch.object(
            self.window, "refresh_mods"
        ) as refresh_mods:
            self.window._handle_mods_drop([image_path], target_mod_name="combat.pak")

        picker.assert_not_called()
        import_batch.assert_called_once()
        tasks = import_batch.call_args.args[1]
        self.assertEqual(tasks, [("image", image_path, "combat.pak", False)])
        self.assertNotIn(("combat.pak", 140), self.window.tile_delegate._pixmaps)
        refresh_mods.assert_called_once_with(["combat.pak"])

    def test_drop_position_maps_to_mod_name_in_tile_view(self):
        index = self.window.mods_model.index(1, 0)

        with patch.object(self.window.tiles_view, "indexAt", return_value=index):
            mod_name = self.window._mod_name_at_view_position(self.window.tiles_view.viewport(), QtCore.QPoint(12, 12))

        self.assertEqual(mod_name, "ui.pak")


if __name__ == "__main__":
    unittest.main()
