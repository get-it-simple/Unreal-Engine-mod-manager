from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mod_manager.mods import discover_mods, import_mod_image, is_mod_file, mod_image_path, parse_extensions


class ParseExtensionsTests(unittest.TestCase):
    def test_empty_extensions_show_everything_including_folders(self):
        self.assertEqual(parse_extensions({"mod_extensions": ""}), (True, [], True))

    def test_multiple_extensions_are_normalized(self):
        self.assertEqual(
            parse_extensions({"mod_extensions": ".pak, utoc, .UCAS"}),
            (False, [".pak", ".utoc", ".ucas"], False),
        )

    def test_folders_token_enables_folder_mods_alongside_extensions(self):
        self.assertEqual(
            parse_extensions({"mod_extensions": ".pak,.utoc,folders"}),
            (False, [".pak", ".utoc"], True),
        )

    def test_folders_only_excludes_all_files(self):
        self.assertEqual(parse_extensions({"mod_extensions": "folders"}), (False, [], True))


class DiscoverModsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name) / "source"
        self.dst = Path(self.tmp.name) / "game"
        self.src.mkdir()
        self.dst.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _cfg(self, **overrides) -> dict:
        cfg = {
            "mods_source_dir": str(self.src),
            "game_mods_dir": str(self.dst),
            "mod_extensions": "",
            "mod_recursive_scan": False,
            "link_prefix": "",
        }
        cfg.update(overrides)
        return cfg

    def test_default_config_includes_top_level_files_and_folders(self):
        (self.src / "weapon.pak").touch()
        (self.src / "FolderMod").mkdir()
        (self.src / "images").mkdir()

        items = discover_mods(self._cfg())

        names = {item.name for item in items}
        self.assertEqual(names, {"weapon.pak", "FolderMod"})
        folder_item = next(item for item in items if item.name == "FolderMod")
        self.assertTrue(folder_item.is_dir)

    def test_extensions_without_folders_token_excludes_directories(self):
        (self.src / "weapon.pak").touch()
        (self.src / "readme.txt").touch()
        (self.src / "FolderMod").mkdir()

        items = discover_mods(self._cfg(mod_extensions=".pak,.utoc"))

        self.assertEqual({item.name for item in items}, {"weapon.pak"})

    def test_folders_token_combined_with_extensions(self):
        (self.src / "weapon.pak").touch()
        (self.src / "readme.txt").touch()
        (self.src / "FolderMod").mkdir()

        items = discover_mods(self._cfg(mod_extensions=".pak,folders"))

        self.assertEqual({item.name for item in items}, {"weapon.pak", "FolderMod"})

    def test_recursive_scan_finds_nested_files_when_folders_excluded(self):
        nested = self.src / "Category" / "Sub"
        nested.mkdir(parents=True)
        (nested / "weapon.pak").touch()
        (self.src / "top.pak").touch()

        non_recursive = discover_mods(self._cfg(mod_extensions=".pak", mod_recursive_scan=False))
        self.assertEqual({item.name for item in non_recursive}, {"top.pak"})

        recursive = discover_mods(self._cfg(mod_extensions=".pak", mod_recursive_scan=True))
        self.assertEqual({item.name for item in recursive}, {"top.pak", "weapon.pak"})

    def test_recursive_scan_does_not_recurse_into_folder_mods(self):
        folder_mod = self.src / "FolderMod"
        folder_mod.mkdir()
        (folder_mod / "inner.pak").touch()

        items = discover_mods(self._cfg(mod_extensions=".pak,folders", mod_recursive_scan=True))

        self.assertEqual({item.name for item in items}, {"FolderMod"})

    def test_same_image_imported_for_different_mods_is_stored_per_mod_name(self):
        drop = Path(self.tmp.name) / "drop"
        drop.mkdir()
        image = drop / "preview.png"
        image.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
            b"\x00\x00\x00\x03\x00\x01\x9a`\x1d\x15\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        cfg = self._cfg()

        ok_first, first_name = import_mod_image(cfg, "weapon.pak", image)
        ok_second, second_name = import_mod_image(cfg, "FolderMod", image)

        self.assertTrue(ok_first)
        self.assertTrue(ok_second)
        self.assertTrue(first_name.startswith("weapon.pak"))
        self.assertTrue(second_name.startswith("FolderMod"))
        first_path = mod_image_path(cfg, "weapon.pak")
        second_path = mod_image_path(cfg, "FolderMod")
        self.assertIsNotNone(first_path)
        self.assertIsNotNone(second_path)
        self.assertNotEqual(first_path, second_path)
        self.assertNotIn("preview", {p.name for p in (self.src / "images").iterdir()})

    def test_is_mod_file_respects_folder_inclusion(self):
        folder = self.src / "FolderMod"
        folder.mkdir()
        pak = self.src / "weapon.pak"
        pak.touch()

        cfg_no_folders = self._cfg(mod_extensions=".pak")
        self.assertFalse(is_mod_file(folder, cfg_no_folders))
        self.assertTrue(is_mod_file(pak, cfg_no_folders))

        cfg_with_folders = self._cfg(mod_extensions=".pak,folders")
        self.assertTrue(is_mod_file(folder, cfg_with_folders))


if __name__ == "__main__":
    unittest.main()
