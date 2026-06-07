from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mod_manager.cli_utils import select_in_explorer


class CliUtilsTests(unittest.TestCase):
    def test_select_in_explorer_uses_quoted_absolute_windows_select_path(self):
        base = Path(tempfile.gettempdir()) / "mm select source drive"
        base.mkdir(parents=True, exist_ok=True)
        path = base / "mm select target.pak"
        path.write_text("x", encoding="utf-8")
        try:
            with patch("mod_manager.cli_utils.is_windows", return_value=True), patch("subprocess.Popen") as popen:
                select_in_explorer(path)

            args = popen.call_args.args[0]
            self.assertEqual(args[0], "explorer")
            self.assertEqual(args[1], f'/select,"{path.absolute()}"')
        finally:
            path.unlink(missing_ok=True)
            try:
                base.rmdir()
            except OSError:
                pass

    def test_select_in_explorer_selects_windows_symlink_even_when_target_is_missing(self):
        link = Path(tempfile.gettempdir()) / "mm_select_broken_link.pak"
        try:
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(Path(tempfile.gettempdir()) / "mm_missing_link_target.pak")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available")
        try:
            with patch("mod_manager.cli_utils.is_windows", return_value=True), patch("subprocess.Popen") as popen:
                select_in_explorer(link)

            args = popen.call_args.args[0]
            self.assertEqual(args[0], "explorer")
            self.assertEqual(args[1], f'/select,"{link.absolute()}"')
        finally:
            if link.exists() or link.is_symlink():
                link.unlink()


if __name__ == "__main__":
    unittest.main()
