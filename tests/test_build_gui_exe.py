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
        with patch.dict("os.environ", {}, clear=True), patch(
            "subprocess.call",
            return_value=0,
        ) as call, patch.dict(
            module["main"].__globals__,
            {"_clean_before": clean_before, "_clean_after": clean_after, "_ensure_packages": Mock(return_value=True)},
        ):
            code = module["main"](["--exe", "--onefile"])

        self.assertEqual(code, 0)
        clean_before.assert_called_once_with()
        clean_after.assert_called_once_with()
        self.assertIn("--onefile", call.call_args.args[0])
        self.assertNotIn("--onedir", call.call_args.args[0])
        self.assertIn("-m", call.call_args.args[0])
        self.assertIn("PyInstaller", call.call_args.args[0])

    def test_main_dispatches_pyz_from_args_even_when_env_requests_exe(self):
        module = self.load_build_module()
        build_pyz = Mock(return_value=0)
        with patch.dict("os.environ", {"MOD_MANAGER_BUILD_EXE": "1"}, clear=True), patch.dict(
            module["main"].__globals__,
            {"_clean_before": Mock(), "_clean_after": Mock(), "_build_pyz": build_pyz, "_ensure_packages": Mock(return_value=True)},
        ):
            code = module["main"](["--pyz"])

        self.assertEqual(code, 0)
        build_pyz.assert_called_once_with()

    def test_main_keeps_env_var_compatibility(self):
        module = self.load_build_module()
        with patch.dict("os.environ", {"MOD_MANAGER_BUILD_EXE": "1", "MOD_MANAGER_ONEFILE": "1"}, clear=True), patch(
            "subprocess.call", return_value=0
        ) as call, patch.dict(
            module["main"].__globals__,
            {"_clean_before": Mock(), "_clean_after": Mock(), "_ensure_packages": Mock(return_value=True)},
        ):
            code = module["main"]([])

        self.assertEqual(code, 0)
        self.assertIn("--onefile", call.call_args.args[0])

    def test_main_returns_error_when_runtime_package_check_fails_for_pyz(self):
        module = self.load_build_module()
        build_pyz = Mock()
        with patch.dict("os.environ", {}, clear=True), patch.dict(
            module["main"].__globals__,
            {"_ensure_packages": Mock(return_value=False), "_clean_before": Mock(), "_build_pyz": build_pyz},
        ):
            code = module["main"](["--pyz"])

        self.assertEqual(code, 1)
        build_pyz.assert_not_called()

    def test_ensure_packages_installs_missing_packages_interactively(self):
        module = self.load_build_module()
        module_globals = module["_ensure_packages"].__globals__
        calls = iter([["PySide6>=6.7.0"], []])
        with patch.dict(
            module_globals,
            {"_missing_packages": Mock(side_effect=lambda _modules: next(calls))},
        ), patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="y"), patch(
            "subprocess.call",
            return_value=0,
        ) as call:
            result = module["_ensure_packages"]({"PySide6": "PySide6>=6.7.0"})

        self.assertTrue(result)
        self.assertIn("pip", call.call_args.args[0])
        self.assertIn("PySide6>=6.7.0", call.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
