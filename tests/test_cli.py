from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from mod_manager.cli import run_cli
from mod_manager.models import ModItem

_FAKE_SRC = Path(tempfile.gettempdir()) / "mm_test_source"
_FAKE_DEST = Path(tempfile.gettempdir()) / "mm_test_game"
_FAKE_NEW_DEST = Path(tempfile.gettempdir()) / "mm_test_new_game"


class CliRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = {
            "game_mods_dir": str(_FAKE_DEST),
            "mods_source_dir": str(_FAKE_SRC),
            "page_size": 10,
            "gui_theme": "system",
        }

    def run_request(self, argv):
        out = io.StringIO()
        with patch("mod_manager.cli.load_config", return_value=self.cfg), patch("sys.stdout", out):
            code = run_cli(argv)
        return code, out.getvalue()

    def mod_item(self, name: str, installed: bool = False) -> ModItem:
        return ModItem(
            name=name,
            src=_FAKE_SRC / name,
            dest=_FAKE_DEST / name,
            is_dir=False,
            installed=installed,
        )

    def test_help_request_prints_nested_command_help_without_loading_config(self):
        out = io.StringIO()
        with patch("mod_manager.cli.load_config") as load_config, patch("sys.stdout", out):
            code = run_cli(["help", "mods", "toggle"])

        self.assertEqual(code, 0)
        self.assertIn("usage: mod-manager.py mods toggle", out.getvalue())
        load_config.assert_not_called()

    def test_mods_list_request_prints_mod_page(self):
        shown = [self.mod_item("weapon.pak", installed=True), self.mod_item("ui.pak")]

        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.mods_view",
            return_value=(shown, shown, 1, 1, {"weapon.pak": "combat"}),
        ) as mods_view:
            code, output = self.run_request(["mods", "list", "--search", "pak", "--label", "combat"])

        self.assertEqual(code, 0)
        mods_view.assert_called_once_with(self.cfg, 1, "combat", "pak", "default")
        self.assertIn("Page 1/1", output)
        self.assertIn("1. [X] weapon.pak [combat]", output)
        self.assertIn("2. [ ] ui.pak [-]", output)

    def test_mods_install_request_passes_filters_and_returns_error_on_failures(self):
        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.apply_mods_page",
            return_value=(2, 3, 1),
        ) as apply_mods_page:
            code, output = self.run_request(
                ["mods", "install", "--page", "2", "--label", "combat", "--search", "pak", "--order", "cd"]
            )

        self.assertEqual(code, 1)
        apply_mods_page.assert_called_once_with(self.cfg, 2, "combat", "pak", "created_date")
        self.assertIn("Installed 2/3 on page 2. Errors: 1.", output)

    def test_mods_search_command_uses_text_as_search_filter(self):
        shown = [self.mod_item("hud.pak")]

        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.mods_view",
            return_value=(shown, shown, 2, 2, {}),
        ) as mods_view:
            code, output = self.run_request(["mods", "search", "hud", "--page", "2", "--label", "ui", "--order", "default"])

        self.assertEqual(code, 0)
        mods_view.assert_called_once_with(self.cfg, 2, "ui", "hud", "default")
        self.assertIn("Page 2/2", output)

    def test_mods_label_command_uses_text_as_label_filter(self):
        shown = [self.mod_item("combat.pak")]

        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.mods_view",
            return_value=(shown, shown, 1, 1, {"combat.pak": "combat"}),
        ) as mods_view:
            code, _output = self.run_request(["mods", "label", "combat", "--search", "pak", "--order", "created date"])

        self.assertEqual(code, 0)
        mods_view.assert_called_once_with(self.cfg, 1, "combat", "pak", "created_date")

    def test_mods_page_and_order_commands_translate_positionals_to_view_options(self):
        shown = [self.mod_item("a.pak")]

        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.mods_view",
            return_value=(shown, shown, 4, 5, {}),
        ) as mods_view:
            page_code, page_output = self.run_request(["mods", "page", "4", "--search", "a", "--label", "core"])

        self.assertEqual(page_code, 0)
        mods_view.assert_called_once_with(self.cfg, 4, "core", "a", "default")
        self.assertIn("Page 4/5", page_output)

        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.mods_view",
            return_value=(shown, shown, 1, 1, {}),
        ) as mods_view:
            order_code, _order_output = self.run_request(["mods", "order", "cd", "--page", "3"])

        self.assertEqual(order_code, 0)
        mods_view.assert_called_once_with(self.cfg, 3, "", "", "created_date")

    def test_mods_toggle_request_parses_comma_separated_indexes(self):
        shown = [self.mod_item("a.pak"), self.mod_item("b.pak"), self.mod_item("c.pak")]

        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.mods_view",
            return_value=(shown, shown, 1, 1, {}),
        ), patch(
            "mod_manager.cli.toggle_mods_by_indexes",
            return_value="Installed 2/2. Errors: 0.",
        ) as toggle_mods:
            code, output = self.run_request(["mods", "toggle", "1,3", "--page", "2", "--search", "pak"])

        self.assertEqual(code, 0)
        toggle_mods.assert_called_once_with(shown, [1, 3])
        self.assertIn("Installed 2/2. Errors: 0.", output)

    def test_mods_uninstall_request_passes_view_options(self):
        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.deactivate_mods_page",
            return_value=(5, 7),
        ) as deactivate_page:
            code, output = self.run_request(
                ["mods", "uninstall", "--page", "5", "--label", "old", "--search", "pak", "--order", "default"]
            )

        self.assertEqual(code, 0)
        deactivate_page.assert_called_once_with(self.cfg, 5, "old", "pak", "default")
        self.assertIn("Uninstalled 7 on page 5.", output)

    def test_mods_label_add_request_maps_indexes_to_visible_mod_names(self):
        shown = [self.mod_item("a.pak"), self.mod_item("b.pak"), self.mod_item("c.pak")]

        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.mods_view",
            return_value=(shown, shown, 1, 1, {}),
        ), patch(
            "mod_manager.cli.add_label_to_mods",
            return_value="Label added: combat -> a.pak, c.pak",
        ) as add_label:
            code, output = self.run_request(["mods", "label-add", "combat", "1,3"])

        self.assertEqual(code, 0)
        add_label.assert_called_once_with("combat", ["a.pak", "c.pak"])
        self.assertIn("Label added: combat -> a.pak, c.pak", output)

    def test_mods_label_remove_request_uses_filter_label_option(self):
        shown = [self.mod_item("a.pak"), self.mod_item("b.pak")]

        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.mods_view",
            return_value=(shown, shown, 2, 2, {"a.pak": "combat"}),
        ) as mods_view, patch(
            "mod_manager.cli.remove_label_from_mods",
            return_value="Label removed: combat -> a.pak",
        ) as remove_label:
            code, output = self.run_request(
                ["mods", "label-remove", "combat", "1", "--page", "2", "--filter-label", "combat", "--search", "pak"]
            )

        self.assertEqual(code, 0)
        mods_view.assert_called_once_with(self.cfg, 2, "combat", "pak", "default")
        remove_label.assert_called_once_with("combat", ["a.pak"])
        self.assertIn("Label removed: combat -> a.pak", output)

    def test_mods_label_add_returns_error_for_invalid_index(self):
        shown = [self.mod_item("a.pak")]

        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.mods_view",
            return_value=(shown, shown, 1, 1, {}),
        ):
            code, output = self.run_request(["mods", "label-add", "combat", "9"])

        self.assertEqual(code, 1)
        self.assertIn("Invalid index.", output)

    def test_settings_set_request_saves_changed_values(self):
        saved = Mock()
        with patch("mod_manager.cli.save_config", saved):
            code, output = self.run_request(
                [
                    "settings",
                    "set",
                    "--game-mods-dir",
                    str(_FAKE_NEW_DEST),
                    "--page-size",
                    "25",
                    "--gui-theme",
                    "dark",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(self.cfg["game_mods_dir"], str(_FAKE_NEW_DEST))
        self.assertEqual(self.cfg["page_size"], 25)
        self.assertEqual(self.cfg["gui_theme"], "dark")
        saved.assert_called_once_with(self.cfg)
        self.assertIn("Saved.", output)

    def test_settings_show_request_prints_sorted_config_without_saving(self):
        with patch("mod_manager.cli.save_config") as save_config:
            code, output = self.run_request(["settings", "show"])

        self.assertEqual(code, 0)
        save_config.assert_not_called()
        self.assertLess(output.index("game_mods_dir:"), output.index("mods_source_dir:"))
        self.assertIn("page_size: 10", output)

    def test_settings_set_request_with_no_options_does_not_save(self):
        with patch("mod_manager.cli.save_config") as save_config:
            code, output = self.run_request(["settings", "set"])

        self.assertEqual(code, 0)
        save_config.assert_not_called()
        self.assertIn("Nothing changed.", output)

    def test_presets_list_and_page_requests_use_page_options(self):
        presets = {"core": ["a.pak"], "extra": ["b.pak"]}

        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.presets_view",
            return_value=(presets, list(presets), ["extra"], 2, 2),
        ) as presets_view, patch(
            "mod_manager.cli.mods_view",
            return_value=([self.mod_item("b.pak", installed=True)], [], 1, 1, {}),
        ):
            list_code, list_output = self.run_request(["presets", "list", "--page", "2"])

        self.assertEqual(list_code, 0)
        presets_view.assert_called_once_with(self.cfg, 2)
        self.assertIn("Page 2/2", list_output)
        self.assertIn("1. [X] extra [1]", list_output)

        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.presets_view",
            return_value=(presets, list(presets), ["core"], 3, 3),
        ) as presets_view, patch(
            "mod_manager.cli.mods_view",
            return_value=([], [], 1, 1, {}),
        ):
            page_code, page_output = self.run_request(["presets", "page", "3"])

        self.assertEqual(page_code, 0)
        presets_view.assert_called_once_with(self.cfg, 3)
        self.assertIn("Page 3/3", page_output)

    def test_presets_save_and_delete_requests_dispatch_options(self):
        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.save_preset_from_installed",
            return_value=(True, "Preset 'core' saved (2 mods)"),
        ) as save_preset:
            save_code, save_output = self.run_request(["presets", "save", "core"])

        self.assertEqual(save_code, 0)
        save_preset.assert_called_once_with(self.cfg, "core")
        self.assertIn("Preset 'core' saved (2 mods)", save_output)

        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.delete_presets_by_indexes",
            return_value=(2, ["missing"]),
        ) as delete_presets:
            delete_code, delete_output = self.run_request(["presets", "delete", "1,3", "--page", "4"])

        self.assertEqual(delete_code, 0)
        delete_presets.assert_called_once_with(self.cfg, 4, [1, 3])
        self.assertIn("Deleted: 2. Missing: missing", delete_output)

    def test_presets_toggle_request_prints_messages_and_returns_error_on_failures(self):
        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.mods_view",
            return_value=([], [], 1, 1, {}),
        ), patch(
            "mod_manager.cli.toggle_presets_by_indexes",
            return_value=("Installed: 1, Errors: 1", ["missing.pak: ERR"], True),
        ) as toggle_presets:
            code, output = self.run_request(["presets", "toggle", "2,4", "--page", "3"])

        self.assertEqual(code, 1)
        toggle_presets.assert_called_once_with(self.cfg, 3, [2, 4], set())
        self.assertIn("Installed: 1, Errors: 1", output)
        self.assertIn(" -  missing.pak: ERR", output)

    def test_open_requests_dispatch_source_and_game_targets(self):
        with patch("mod_manager.cli.open_folder", return_value=(True, "Opened")) as open_folder:
            source_code, source_output = self.run_request(["open", "source"])

        self.assertEqual(source_code, 0)
        open_folder.assert_called_once_with(str(_FAKE_SRC))
        self.assertIn("Open source folder: OK", source_output)

        with patch("mod_manager.cli.open_folder", return_value=(False, "denied")) as open_folder:
            game_code, game_output = self.run_request(["open", "game"])

        self.assertEqual(game_code, 1)
        open_folder.assert_called_once_with(str(_FAKE_DEST))
        self.assertIn("Open game folder: ERR", game_output)

    def test_broken_list_request_prints_items(self):
        broken = [self.mod_item("missing-a.pak", installed=True)]

        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.list_broken_links",
            return_value=broken,
        ):
            code, output = self.run_request(["broken", "list"])

        self.assertEqual(code, 0)
        self.assertIn("1. [!] missing-a.pak (FILE) -> missing source:", output)

    def test_broken_remove_indexes_request_removes_selected_items_only(self):
        broken = [
            self.mod_item("missing-a.pak", installed=True),
            self.mod_item("missing-b.pak", installed=True),
            self.mod_item("missing-c.pak", installed=True),
        ]

        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.list_broken_links",
            return_value=broken,
        ), patch("mod_manager.cli.deactivate_mod", return_value=(True, "OK")) as deactivate:
            code, output = self.run_request(["broken", "remove", "2,99"])

        self.assertEqual(code, 0)
        deactivate.assert_called_once_with(broken[1])
        self.assertIn("Remove missing-b.pak: OK", output)

    def test_broken_remove_all_request_removes_each_broken_item(self):
        broken = [self.mod_item("missing-a.pak", installed=True), self.mod_item("missing-b.pak", installed=True)]

        with patch("mod_manager.cli.ensure_paths", return_value=True), patch(
            "mod_manager.cli.list_broken_links",
            return_value=broken,
        ), patch(
            "mod_manager.cli.deactivate_mod",
            side_effect=[(True, "OK"), (False, "Already removed")],
        ) as deactivate:
            code, output = self.run_request(["broken", "remove", "--all"])

        self.assertEqual(code, 0)
        self.assertEqual(deactivate.call_count, 2)
        self.assertIn("Remove missing-a.pak: OK", output)
        self.assertIn("Remove missing-b.pak: ERR", output)

    def test_commands_that_need_paths_return_error_before_dispatch_when_paths_are_missing(self):
        with patch("mod_manager.cli.ensure_paths", return_value=False), patch("mod_manager.cli.mods_view") as mods_view:
            mods_code, _mods_output = self.run_request(["mods", "list"])

        self.assertEqual(mods_code, 1)
        mods_view.assert_not_called()

        with patch("mod_manager.cli.ensure_paths", return_value=False), patch(
            "mod_manager.cli.presets_view"
        ) as presets_view:
            presets_code, _presets_output = self.run_request(["presets", "list"])

        self.assertEqual(presets_code, 1)
        presets_view.assert_not_called()

        with patch("mod_manager.cli.ensure_paths", return_value=False), patch(
            "mod_manager.cli.list_broken_links"
        ) as list_broken:
            broken_code, _broken_output = self.run_request(["broken", "list"])

        self.assertEqual(broken_code, 1)
        list_broken.assert_not_called()

    def test_invalid_order_request_exits_with_argparse_error(self):
        with patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as exc:
                run_cli(["mods", "list", "--order", "newest"])

        self.assertEqual(exc.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
