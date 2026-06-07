from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import tkinter as tk

from mod_manager.models import ModItem


class DummyDropTarget:
    def __init__(self, widget, callback):
        self.widget = widget
        self.callback = callback


class GuiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = {
            "mods_source_dir": "D:/Source/Mods",
            "game_mods_dir": "D:/Game/Mods",
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
            patch("mod_manager.gui.WindowsDropTarget", DummyDropTarget),
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

        try:
            self.app = ModManagerGui()
        except tk.TclError as exc:
            self._stop_patchers()
            self.skipTest(f"tkinter display unavailable: {exc}")
        self.app.withdraw()
        self.app.update_idletasks()

    def tearDown(self) -> None:
        if hasattr(self, "app"):
            self.app.update()
            self.app.destroy()
        self._stop_patchers()

    def _stop_patchers(self) -> None:
        for patcher in reversed(getattr(self, "patchers", [])):
            patcher.stop()

    def mod_item(self, name: str, installed: bool = False, is_dir: bool = False) -> ModItem:
        return ModItem(
            name=name,
            src=Path("D:/Source/Mods") / name,
            dest=Path("D:/Game/Mods") / name,
            is_dir=is_dir,
            installed=installed,
        )

    def run_action_inline(self, label, worker, done=None) -> None:
        result = worker()
        if done:
            done(result)

    def test_initial_refresh_populates_mods_presets_and_broken_tabs(self):
        mod_rows = self.app.mods_tree.get_children()
        preset_rows = self.app.presets_tree.get_children()
        broken_rows = self.app.broken_tree.get_children()

        self.assertEqual(len(mod_rows), 2)
        self.assertEqual(self.app.mods_tree.item("1", "values"), ("✓  combat.pak", "combat", "2026-01-01 10:00:00"))
        self.assertEqual(self.app.mods_tree.item("2", "values"), ("ui.pak", "-", "-"))
        self.assertEqual(self.app.search_box["values"], ("combat.pak", "ui.pak"))
        self.assertEqual(self.app.label_filter_box["values"], ("combat",))
        self.assertEqual(len(preset_rows), 2)
        self.assertEqual(self.app.presets_tree.item("1", "text"), "core")
        self.assertEqual(self.app.presets_tree.item("1", "values"), ("applied", "1", "2026-01-02 10:00:00"))
        self.assertEqual(len(broken_rows), 1)
        self.assertEqual(self.app.broken_tree.item("1", "text"), "missing.pak")

    def test_view_args_and_clear_search_update_filter_state(self):
        self.app.mod_page.set(3)
        self.app.search_var.set("ui")
        self.app.label_filter_var.set("combat")
        self.app.order_var.set("Created date")

        self.assertEqual(self.app._view_args(), (3, "combat", "ui", "cd"))

        with patch.object(self.app, "refresh_mods") as refresh_mods:
            self.app._mods_clear()

        self.assertEqual(self.app.mod_page.get(), 1)
        self.assertEqual(self.app.search_var.get(), "")
        self.assertEqual(self.app.label_filter_var.get(), "")
        refresh_mods.assert_called_once_with()

    def test_sorting_saves_state_and_refreshes_relevant_tree(self):
        with patch("mod_manager.gui.save_config") as save_config, patch.object(self.app, "refresh_mods") as refresh_mods:
            self.app._sort_mods("name")

        self.assertEqual(self.app.mod_sort_key, "name")
        self.assertFalse(self.app.mod_sort_reverse)
        self.assertEqual(self.app.mod_page.get(), 1)
        save_config.assert_called_once_with(self.app.cfg)
        refresh_mods.assert_called_once_with()

        with patch("mod_manager.gui.save_config") as save_config, patch.object(self.app, "refresh_presets") as refresh_presets:
            self.app._sort_presets("name")

        self.assertEqual(self.app.preset_sort_key, "name")
        self.assertTrue(self.app.preset_sort_reverse)
        save_config.assert_called_once_with(self.app.cfg)
        refresh_presets.assert_called_once_with()

    def test_install_uninstall_and_toggle_selected_mods_dispatch_gui_options(self):
        self.app._run_action = self.run_action_inline
        self.app.mod_page.set(2)
        self.app.search_var.set("pak")
        self.app.label_filter_var.set("combat")

        with patch("mod_manager.gui.apply_mods_page", return_value=(2, 3, 1)) as apply_mods, patch.object(
            self.app, "refresh_mods"
        ) as refresh_mods, patch.object(self.app, "refresh_presets") as refresh_presets:
            self.app._install_page()

        apply_mods.assert_called_once_with(self.app.cfg, 2, "combat", "pak", "d")
        self.assertEqual(self.app.status_var.get(), "Installed 2/3 on page 2. Errors: 1.")
        refresh_mods.assert_called_once_with()
        refresh_presets.assert_called_once_with()

        with patch("mod_manager.gui.deactivate_mods_page", return_value=(2, 2)) as deactivate_mods, patch.object(
            self.app, "refresh_mods"
        ), patch.object(self.app, "refresh_presets"):
            self.app._uninstall_page()

        deactivate_mods.assert_called_once_with(self.app.cfg, 2, "combat", "pak", "d")
        self.assertEqual(self.app.status_var.get(), "Uninstalled 2 on page 2.")

        self.app.refresh_mods()
        self.app.mods_tree.selection_set(("1", "2"))
        with patch("mod_manager.gui.toggle_mods_by_indexes", return_value="Toggled") as toggle_mods, patch.object(
            self.app, "refresh_mods"
        ) as refresh_mods, patch.object(self.app, "refresh_presets"):
            self.app._toggle_selected_mods()

        toggle_mods.assert_called_once_with(self.mods, [1, 2])
        refresh_mods.assert_called_once_with(["combat.pak", "ui.pak"])
        self.assertEqual(self.app.status_var.get(), "Toggled")

    def test_label_buttons_validate_input_and_dispatch_selected_mods(self):
        self.app._run_action = self.run_action_inline
        self.app.refresh_mods()
        self.app.mods_tree.selection_set(("1",))

        with patch("mod_manager.gui.messagebox.showerror") as showerror:
            self.app.label_edit_var.set("")
            self.app._add_label_selected()

        showerror.assert_called_once_with("Label", "Enter label.")

        self.app.label_edit_var.set("combat")
        with patch("mod_manager.gui.add_label_to_mods", return_value="Label added") as add_label, patch.object(
            self.app, "refresh_mods"
        ):
            self.app._add_label_selected()

        add_label.assert_called_once_with("combat", ["combat.pak"])
        self.assertEqual(self.app.status_var.get(), "Label added")

        with patch("mod_manager.gui.remove_label_from_mods", return_value="Label removed") as remove_label, patch.object(
            self.app, "refresh_mods"
        ):
            self.app._remove_label_selected()

        remove_label.assert_called_once_with("combat", ["combat.pak"])
        self.assertEqual(self.app.status_var.get(), "Label removed")

    def test_import_paths_filters_supported_mods_and_reports_counts(self):
        self.app._run_action = self.run_action_inline
        self.app.current_mod_items = [self.mods[0]]

        with patch("mod_manager.gui.is_mod_file", side_effect=lambda path, _cfg: path.suffix == ".pak"), patch(
            "mod_manager.gui.messagebox.askyesno",
            return_value=True,
        ) as askyesno, patch(
            "mod_manager.gui.import_mod_file",
            side_effect=[(True, "combat.pak"), (False, "new.pak")],
        ) as import_mod, patch.object(self.app, "refresh_mods") as refresh_mods:
            self.app._import_paths([Path("D:/Drop/combat.pak"), Path("D:/Drop/skip.txt"), Path("D:/Drop/new.pak")])

        askyesno.assert_called_once()
        self.assertEqual(import_mod.call_count, 2)
        import_mod.assert_any_call(self.app.cfg, Path("D:/Drop/combat.pak"), True)
        import_mod.assert_any_call(self.app.cfg, Path("D:/Drop/new.pak"), False)
        self.assertEqual(self.app.status_var.get(), "Imported: 1. Skipped: 1.")
        refresh_mods.assert_called_once_with()

    def test_save_settings_converts_numeric_values_and_refreshes_ui(self):
        self.app._run_action = self.run_action_inline
        self.app.setting_vars["page_size"].set("25")
        self.app.setting_vars["ui_scale_percent"].set("150%")
        self.app.setting_vars["game_mods_dir"].set("D:/Game/NewMods")
        self.app.setting_vars["mod_extensions"].set(".pak")

        with patch("mod_manager.gui.save_config") as save_config, patch.object(self.app, "_rebuild_tabs") as rebuild, patch.object(
            self.app, "refresh_all"
        ) as refresh_all:
            self.app._save_settings()

        self.assertEqual(self.app.cfg["page_size"], 25)
        self.assertEqual(self.app.cfg["ui_scale_percent"], 150)
        self.assertEqual(self.app.cfg["game_mods_dir"], "D:/Game/NewMods")
        self.assertEqual(self.app.cfg["mod_extensions"], ".pak")
        save_config.assert_called_once_with(self.app.cfg)
        rebuild.assert_called_once_with()
        refresh_all.assert_called_once_with()
        self.assertEqual(self.app.status_var.get(), "Settings saved.")

    def test_preset_and_broken_actions_dispatch_selected_rows(self):
        self.app._run_action = self.run_action_inline
        self.app.refresh_presets()
        self.app.presets_tree.selection_set(("1", "2"))

        with patch("mod_manager.gui.toggle_presets_by_indexes", return_value=("Preset toggled", [], False)) as toggle, patch.object(
            self.app, "refresh_mods"
        ), patch.object(self.app, "refresh_presets"):
            self.app._toggle_selected_presets()

        toggle.assert_called_once_with(self.app.cfg, 1, [1, 2], {"combat.pak"})
        self.assertEqual(self.app.status_var.get(), "Preset toggled")

        with patch("mod_manager.gui.delete_presets_by_indexes", return_value=(2, [])) as delete_presets, patch.object(
            self.app, "refresh_presets"
        ):
            self.app._delete_selected_presets()

        delete_presets.assert_called_once_with(self.app.cfg, 1, [1, 2])
        self.assertEqual(self.app.status_var.get(), "Deleted: 2. Missing: none")

        self.app.refresh_broken()
        self.app.broken_tree.selection_set(("1",))
        with patch("mod_manager.gui.deactivate_mod", return_value=(True, "OK")) as deactivate, patch.object(
            self.app, "refresh_broken"
        ):
            self.app._remove_selected_broken()

        deactivate.assert_called_once_with(self.broken[0])
        self.assertEqual(self.app.status_var.get(), "Removed broken links: 1")


if __name__ == "__main__":
    unittest.main()
