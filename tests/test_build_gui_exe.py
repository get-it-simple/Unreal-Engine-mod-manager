from __future__ import annotations

import runpy
import unittest
from unittest.mock import Mock, patch


class BuildGuiExeTests(unittest.TestCase):
    def load_build_module(self):
        return runpy.run_path("build-gui-exe.py")

    def test_main_dispatches_onefile_exe_from_args(self):
        module = self.load_build_module()
        clean_before = Mock()
        clean_after = Mock()
        with patch.dict("os.environ", {}, clear=True), patch("shutil.which", return_value="pyinstaller"), patch(
            "subprocess.call",
            return_value=0,
        ) as call, patch.dict(module["main"].__globals__, {"_clean_before": clean_before, "_clean_after": clean_after}):
            code = module["main"](["--exe", "--onefile"])

        self.assertEqual(code, 0)
        clean_before.assert_called_once_with()
        clean_after.assert_called_once_with()
        self.assertIn("--onefile", call.call_args.args[0])
        self.assertNotIn("--onedir", call.call_args.args[0])

    def test_main_dispatches_pyz_from_args_even_when_env_requests_exe(self):
        module = self.load_build_module()
        build_pyz = Mock(return_value=0)
        with patch.dict("os.environ", {"MOD_MANAGER_BUILD_EXE": "1"}, clear=True), patch.dict(
            module["main"].__globals__,
            {"_clean_before": Mock(), "_clean_after": Mock(), "_build_pyz": build_pyz},
        ):
            code = module["main"](["--pyz"])

        self.assertEqual(code, 0)
        build_pyz.assert_called_once_with()

    def test_main_keeps_env_var_compatibility(self):
        module = self.load_build_module()
        with patch.dict("os.environ", {"MOD_MANAGER_BUILD_EXE": "1", "MOD_MANAGER_ONEFILE": "1"}, clear=True), patch(
            "shutil.which",
            return_value="pyinstaller",
        ), patch("subprocess.call", return_value=0) as call, patch.dict(
            module["main"].__globals__,
            {"_clean_before": Mock(), "_clean_after": Mock()},
        ):
            code = module["main"]([])

        self.assertEqual(code, 0)
        self.assertIn("--onefile", call.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
