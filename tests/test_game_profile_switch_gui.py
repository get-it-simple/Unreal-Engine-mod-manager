from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mod_manager import storage

try:
    from PySide6 import QtWidgets
except ModuleNotFoundError:
    QtWidgets = None


@unittest.skipIf(QtWidgets is None, "PySide6 is not installed")
class GameProfileSwitchGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.config_path = root / "config.json"
        self.presets_path = root / "presets.json"
        self.labels_path = root / "labels.json"
        self.profile_dir = root / "profiles"
        self.src_a = root / "src_a"
        self.dst_a = root / "dst_a"
        self.src_b = root / "src_b"
        self.dst_b = root / "dst_b"
        for d in (self.src_a, self.dst_a, self.src_b, self.dst_b):
            d.mkdir()
        (self.src_a / "a.pak").touch()
        (self.src_b / "b.pak").touch()

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

    def test_switching_active_profile_refreshes_presets_in_gui(self):
        cfg = storage.load_config()
        first = storage.create_game_profile(
            "First Game", {"mods_source_dir": str(self.src_a), "game_mods_dir": str(self.dst_a)}, cfg
        )
        second = storage.create_game_profile(
            "Second Game", {"mods_source_dir": str(self.src_b), "game_mods_dir": str(self.dst_b)}, cfg
        )
        storage.set_active_game_profile(cfg, first["id"])
        storage.save_config(cfg)
        storage.save_presets({"first_preset": ["a.pak"]})

        storage.set_active_game_profile(cfg, second["id"])
        storage.save_config(cfg)
        storage.save_presets({"second_preset": ["b.pak"]})

        storage.set_active_game_profile(cfg, first["id"])
        storage.save_config(cfg)

        from mod_manager.gui import ModManagerGui

        win = ModManagerGui()
        try:
            win.refresh_presets()
            self.assertEqual(win.presets_model.keys, ["first_preset"])

            win._select_game_profile(second["id"])
            self.assertEqual(win.cfg.get("active_game_profile_id"), second["id"])
            self.assertEqual(win.presets_model.keys, ["second_preset"])

            win._select_game_profile(first["id"])
            self.assertEqual(win.cfg.get("active_game_profile_id"), first["id"])
            self.assertEqual(win.presets_model.keys, ["first_preset"])
        finally:
            win.close()
            win.deleteLater()


if __name__ == "__main__":
    unittest.main()
