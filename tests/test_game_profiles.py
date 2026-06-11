from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mod_manager import storage
from mod_manager.cli import run_cli


class GameProfileStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config_path = self.root / "config.json"
        self.presets_path = self.root / "presets.json"
        self.labels_path = self.root / "labels.json"
        self.profile_dir = self.root / "profiles"
        self.patches = [
            patch("mod_manager.storage.CONFIG_PATH", self.config_path),
            patch("mod_manager.storage.PRESETS_PATH", self.presets_path),
            patch("mod_manager.storage.LABELS_PATH", self.labels_path),
            patch("mod_manager.storage.PROFILE_DATA_DIR", self.profile_dir),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_legacy_game_settings_become_default_profile(self):
        storage.save_json(
            self.config_path,
            {
                "game_name": "Cyber Game",
                "mods_source_dir": "D:/mods/source",
                "game_mods_dir": "D:/game/mods",
                "mod_extensions": ".pak",
            },
        )

        cfg = storage.load_config()

        self.assertEqual(len(cfg["game_profiles"]), 1)
        profile = cfg["game_profiles"][0]
        self.assertEqual(profile["name"], "Cyber Game")
        self.assertEqual(profile["mods_source_dir"], "D:/mods/source")
        self.assertEqual(profile["game_mods_dir"], "D:/game/mods")
        self.assertEqual(profile["mod_extensions"], ".pak")
        self.assertEqual(cfg["active_game_profile_id"], profile["id"])
        self.assertEqual(cfg["mods_source_dir"], "D:/mods/source")

    def test_mod_recursive_scan_persists_per_profile(self):
        cfg = storage.load_config()
        first = storage.create_game_profile(
            "First Game",
            {"mods_source_dir": "A", "game_mods_dir": "B", "mod_recursive_scan": True},
            cfg,
        )
        second = storage.create_game_profile(
            "Second Game",
            {"mods_source_dir": "C", "game_mods_dir": "D"},
            cfg,
        )

        self.assertEqual(first["mod_recursive_scan"], True)
        self.assertFalse(second.get("mod_recursive_scan"))

        storage.set_active_game_profile(cfg, first["id"])
        self.assertEqual(cfg["mod_recursive_scan"], True)

        storage.set_active_game_profile(cfg, second["id"])
        self.assertFalse(cfg["mod_recursive_scan"])

    def test_legacy_presets_are_migrated_into_default_profile(self):
        storage.save_json(
            self.config_path,
            {
                "game_name": "Cyber Game",
                "mods_source_dir": "D:/mods/source",
                "game_mods_dir": "D:/game/mods",
            },
        )
        storage.save_json(self.presets_path, {"legacy": ["old.pak"]})

        cfg = storage.load_config()
        profile_id = cfg["active_game_profile_id"]

        self.assertEqual(storage.load_presets(), {"legacy": ["old.pak"]})
        self.assertTrue((self.profile_dir / f"{profile_id}-presets.json").exists())

    def test_legacy_labels_merge_when_profile_file_was_created_empty_first(self):
        storage.save_json(
            self.config_path,
            {
                "game_name": "Cyber Game",
                "mods_source_dir": "D:/mods/source",
                "game_mods_dir": "D:/game/mods",
            },
        )
        cfg = storage.load_config()
        profile_id = cfg["active_game_profile_id"]
        storage.save_json(self.labels_path, {"combat.pak": {"label": "combat", "last_managed": None, "state": "undefined"}})
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        storage.save_json(self.profile_dir / f"{profile_id}-labels.json", {"combat.pak": {"label": "", "last_managed": None, "state": "undefined"}})

        self.assertEqual(storage.load_labels(), {"combat.pak": "combat"})

    def test_profile_labels_and_presets_are_separated_by_active_game(self):
        cfg = storage.load_config()
        first = storage.create_game_profile("First Game", {"mods_source_dir": "A", "game_mods_dir": "B"}, cfg)
        second = storage.create_game_profile("Second Game", {"mods_source_dir": "C", "game_mods_dir": "D"}, cfg)
        storage.set_active_game_profile(cfg, first["id"])
        storage.save_config(cfg)
        storage.save_labels({"a.pak": "combat"})
        storage.save_presets({"core": ["a.pak"]})

        storage.set_active_game_profile(cfg, second["id"])
        storage.save_config(cfg)
        storage.save_labels({"b.pak": "ui"})
        storage.save_presets({"ui": ["b.pak"]})

        storage.set_active_game_profile(cfg, first["id"])
        storage.save_config(cfg)
        self.assertEqual(storage.load_labels(), {"a.pak": "combat"})
        self.assertEqual(storage.load_presets(), {"core": ["a.pak"]})

        storage.set_active_game_profile(cfg, second["id"])
        storage.save_config(cfg)
        self.assertEqual(storage.load_labels(), {"b.pak": "ui"})
        self.assertEqual(storage.load_presets(), {"ui": ["b.pak"]})


class GameProfileCliTests(unittest.TestCase):
    def test_games_add_select_and_list_use_profile_contract(self):
        cfg = {"game_profiles": [], "active_game_profile_id": ""}
        saved = []

        with patch("mod_manager.cli.load_config", return_value=cfg), patch("mod_manager.cli.save_config", side_effect=lambda c: saved.append(dict(c))):
            self.assertEqual(run_cli(["games", "add", "Stalker Two", "--mods-source-dir", "src", "--game-mods-dir", "dst"]), 0)

        profile = cfg["game_profiles"][0]
        self.assertEqual(profile["name"], "Stalker Two")
        self.assertEqual(profile["mods_source_dir"], "src")
        self.assertEqual(profile["game_mods_dir"], "dst")
        self.assertEqual(cfg["active_game_profile_id"], profile["id"])
        self.assertTrue(saved)


if __name__ == "__main__":
    unittest.main()
