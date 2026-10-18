from __future__ import annotations

import hashlib
import io
import json
import runpy
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from tools.prepare_build import prepare_archive_backend, verify_archive_backend


class PrepareBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        self.resources = self.project / "assets/7zip"
        self.resources.mkdir(parents=True)
        self.files = {"7z.exe": b"synthetic executable", "7z.dll": b"synthetic library"}
        package = io.BytesIO()
        with zipfile.ZipFile(package, "w") as archive:
            for name, payload in self.files.items():
                archive.writestr(name, payload)
            archive.writestr("unneeded.txt", b"not distributed")
        self.package = package.getvalue()
        self.manifest = {
            "version": "test",
            "source": "https://example.invalid/7zip-package.exe",
            "source_sha256": hashlib.sha256(self.package).hexdigest(),
            "files": {name: hashlib.sha256(payload).hexdigest() for name, payload in self.files.items()},
        }
        (self.resources / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        (self.resources / "License.txt").write_text("synthetic license", encoding="utf-8")

    def assert_prepared(self):
        verify_archive_backend(self.project)
        for name, payload in self.files.items():
            self.assertEqual((self.resources / name).read_bytes(), payload)
        self.assertFalse((self.resources / "unneeded.txt").exists())

    def test_cold_preparation_downloads_verifies_and_extracts_only_required_files(self):
        with patch("urllib.request.urlopen", return_value=io.BytesIO(self.package)) as download:
            prepare_archive_backend(self.project)
        download.assert_called_once_with(self.manifest["source"], timeout=60)
        self.assert_prepared()

    def test_valid_resources_need_neither_network_nor_an_extractor(self):
        for name, payload in self.files.items():
            (self.resources / name).write_bytes(payload)
        with patch("urllib.request.urlopen", side_effect=AssertionError("unexpected network")), patch(
            "shutil.which", side_effect=AssertionError("unexpected extractor lookup")
        ):
            prepare_archive_backend(self.project)
        self.assert_prepared()

    def test_verified_download_cache_repairs_missing_and_corrupted_resources_offline(self):
        with patch("urllib.request.urlopen", return_value=io.BytesIO(self.package)):
            prepare_archive_backend(self.project)
        (self.resources / "7z.exe").unlink()
        (self.resources / "7z.dll").write_bytes(b"corrupted")
        with patch("urllib.request.urlopen", side_effect=AssertionError("unexpected network")):
            prepare_archive_backend(self.project)
        self.assert_prepared()

    def test_invalid_download_does_not_replace_existing_resources_or_run_it(self):
        (self.resources / "7z.exe").write_bytes(b"previous executable")
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b"wrong package")), patch(
            "subprocess.run"
        ) as extract:
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                prepare_archive_backend(self.project)
        extract.assert_not_called()
        self.assertEqual((self.resources / "7z.exe").read_bytes(), b"previous executable")
        self.assertFalse((self.resources / "7z.dll").exists())

    def test_wrong_extracted_hash_does_not_publish_any_files(self):
        self.manifest["files"]["7z.dll"] = "0" * 64
        (self.resources / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        with patch("urllib.request.urlopen", return_value=io.BytesIO(self.package)):
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch: 7z.dll"):
                prepare_archive_backend(self.project)
        self.assertFalse((self.resources / "7z.exe").exists())
        self.assertFalse((self.resources / "7z.dll").exists())

    def test_corrupt_package_cache_is_replaced_by_a_verified_download(self):
        cache = self.project / "build/7zip-package" / self.manifest["source_sha256"]
        cache.mkdir(parents=True)
        (cache / "7zip-package.exe").write_bytes(b"corrupted cache")
        with patch("urllib.request.urlopen", return_value=io.BytesIO(self.package)):
            prepare_archive_backend(self.project)
        self.assertEqual((cache / "7zip-package.exe").read_bytes(), self.package)
        self.assert_prepared()

    def test_network_error_preserves_existing_resources(self):
        (self.resources / "7z.exe").write_bytes(b"previous executable")
        with patch("urllib.request.urlopen", side_effect=OSError("network unavailable")):
            with self.assertRaisesRegex(OSError, "network unavailable"):
                prepare_archive_backend(self.project)
        self.assertEqual((self.resources / "7z.exe").read_bytes(), b"previous executable")

    def test_missing_license_fails_before_downloading(self):
        (self.resources / "License.txt").unlink()
        with patch("urllib.request.urlopen") as download:
            with self.assertRaisesRegex(ValueError, "license is missing"):
                prepare_archive_backend(self.project)
        download.assert_not_called()

    def test_missing_tar_reports_the_requirement(self):
        with patch("shutil.which", return_value=None), patch("urllib.request.urlopen") as download:
            with self.assertRaisesRegex(OSError, "requires tar"):
                prepare_archive_backend(self.project)
        download.assert_not_called()

    def test_extraction_error_leaves_existing_resources_untouched(self):
        (self.resources / "7z.exe").write_bytes(b"previous executable")
        with patch("urllib.request.urlopen", return_value=io.BytesIO(self.package)), patch(
            "subprocess.run", side_effect=subprocess.CalledProcessError(1, "tar")
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                prepare_archive_backend(self.project)
        self.assertEqual((self.resources / "7z.exe").read_bytes(), b"previous executable")
        self.assertFalse((self.resources / "7z.dll").exists())


class PrepareBuildCommandTests(unittest.TestCase):
    def test_prepare_only_does_not_require_gui_packages_or_build_or_clean_artifacts(self):
        module = runpy.run_path("build-gui-exe.py")
        with patch.dict(module["main"].__globals__, {
            "prepare_archive_backend": Mock(),
            "_ensure_packages": Mock(side_effect=AssertionError("unexpected package installation")),
            "_clean_before": Mock(side_effect=AssertionError("unexpected cleanup")),
            "_build_exe": Mock(side_effect=AssertionError("unexpected build")),
            "_build_pyz": Mock(side_effect=AssertionError("unexpected build")),
        }):
            self.assertEqual(module["main"](["--prepare-only"]), 0)

    def test_preparation_failure_returns_error_before_cleaning_artifacts(self):
        module = runpy.run_path("build-gui-exe.py")
        with patch.dict(module["main"].__globals__, {
            "prepare_archive_backend": Mock(side_effect=OSError("network unavailable")),
            "_clean_before": Mock(side_effect=AssertionError("unexpected cleanup")),
        }):
            self.assertEqual(module["main"](["--exe", "--onefile"]), 1)


if __name__ == "__main__":
    unittest.main()
