from __future__ import annotations

import io
import runpy
import unittest
from unittest.mock import patch


class LauncherTests(unittest.TestCase):
    def test_plain_script_mode_starts_interactive_menu(self):
        with patch("sys.argv", ["mod-manager.py"]), patch("mod_manager.menus.main_menu") as main_menu, patch(
            "mod_manager.cli.run_cli"
        ) as run_cli:
            runpy.run_path("mod-manager.py", run_name="__main__")

        main_menu.assert_called_once_with()
        run_cli.assert_not_called()

    def test_script_with_arguments_delegates_to_cli_and_exits_with_cli_code(self):
        with patch("sys.argv", ["mod-manager.py", "help", "mods"]), patch(
            "mod_manager.cli.run_cli",
            return_value=7,
        ) as run_cli, patch("mod_manager.menus.main_menu") as main_menu:
            with self.assertRaises(SystemExit) as exc:
                runpy.run_path("mod-manager.py", run_name="__main__")

        self.assertEqual(exc.exception.code, 7)
        run_cli.assert_called_once_with(["help", "mods"])
        main_menu.assert_not_called()

    def test_plain_script_mode_handles_keyboard_interrupt(self):
        out = io.StringIO()
        with patch("sys.argv", ["mod-manager.py"]), patch(
            "mod_manager.menus.main_menu",
            side_effect=KeyboardInterrupt,
        ), patch("sys.stdout", out):
            runpy.run_path("mod-manager.py", run_name="__main__")

        self.assertIn("Exit", out.getvalue())


if __name__ == "__main__":
    unittest.main()
