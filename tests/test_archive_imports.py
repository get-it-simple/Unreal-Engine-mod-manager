from __future__ import annotations

import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from threading import Event

from mod_manager import storage
from mod_manager.archive_backend import ArchiveError, safe_relative_path, seven_zip_path
from mod_manager.import_registry import directory_mods
from mod_manager.imports import create_plans, execute_plans, prepare_archive, regular_import_tasks, resolve_plans
from mod_manager.mods import apply_mods_batch, deactivate_mod, discover_mods, import_mod_file
from mod_manager.presets import apply_preset, save_preset_from_installed
from mod_manager.workers import _run_import_batch


class ArchiveImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.cfg = {
            "mods_source_dir": str(self.source), "game_mods_dir": str(self.root / "game"),
            "mod_extensions": ".pak", "mod_group_extensions": ".pak,.utoc,.ucas",
            "archive_import_mode": "together", "archive_preserve_structure": False,
        }
        for key, value in (
            ("CONFIG_PATH", self.root / "config.json"), ("LABELS_PATH", self.root / "labels.json"),
            ("PRESETS_PATH", self.root / "presets.json"), ("PROFILE_DATA_DIR", self.root / "profiles"),
        ):
            patcher = patch.object(storage, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def archive(self, members=None, name="archive.zip"):
        path = self.root / name
        with zipfile.ZipFile(path, "w") as archive:
            for member, data in (members or {"someFolder/someFolder/actualModFile.pak": b"pak payload"}).items():
                archive.writestr(member, data)
        return path

    def prepare(self, path, **overrides):
        prepared = prepare_archive(path, {**self.cfg, **overrides})
        self.addCleanup(prepared.close)
        return prepared

    def run_import(self, archives, decision="keep_both"):
        plans = resolve_plans(self.cfg, create_plans(archives, lambda _name: decision), lambda _name: decision)
        result = execute_plans(self.cfg, plans)
        self.assertEqual(result[1], [])
        return plans

    def test_nested_archive_imported_and_discovered_without_folders_or_recursive_scan(self):
        archive = self.prepare(self.archive())
        self.run_import([archive])
        self.assertEqual((self.source / "archive" / "actualModFile.pak").read_bytes(), b"pak payload")
        mods = discover_mods(self.cfg)
        self.assertEqual([mod.name for mod in mods], ["archive"])
        self.assertTrue(mods[0].is_dir)
        self.assertEqual(directory_mods(self.cfg), {"archive"})
        self.assertEqual([mod.name for mod in discover_mods({**self.cfg, "mod_recursive_scan": True})], ["archive"])

    def test_all_structure_and_mode_combinations(self):
        for mode, preserve, expected in (
            ("together", False, "archive/actualModFile.pak"),
            ("together", True, "archive/someFolder/someFolder/actualModFile.pak"),
            ("separate", False, "actualModFile.pak"),
            ("separate", True, "actualModFile/someFolder/someFolder/actualModFile.pak"),
        ):
            with self.subTest(mode=mode, preserve=preserve):
                destination = self.source / f"{mode}-{preserve}"
                destination.mkdir()
                cfg = {**self.cfg, "mods_source_dir": str(destination)}
                archive = self.prepare(self.archive(), archive_import_mode=mode, archive_preserve_structure=preserve)
                plans = resolve_plans(cfg, create_plans([archive], lambda _name: "skip"), lambda _name: "skip")
                self.assertEqual(execute_plans(cfg, plans)[1], [])
                self.assertEqual((destination / expected).read_bytes(), b"pak payload")
                self.assertEqual(len(discover_mods(cfg)), 1)

    def test_groups_are_one_option_and_do_not_merge_different_folders(self):
        archive = self.prepare(self.archive({
            "A/mod.pak": b"A", "A/mod.utoc": b"utoc", "A/mod.ucas": b"ucas", "B/mod.pak": b"B",
        }), archive_import_mode="separate")
        self.assertEqual(len(archive.units), 2)
        self.assertEqual(len(archive.units[0].members), 3)
        self.run_import([archive])
        self.assertEqual((self.source / "mod.pak").read_bytes(), b"A")
        self.assertEqual((self.source / "mod (1).pak").read_bytes(), b"B")
        self.assertEqual({mod.name for mod in discover_mods(self.cfg)}, {"mod.pak", "mod (1).pak"})

    def test_checkbox_selection_imports_only_selected_group(self):
        archive = self.prepare(self.archive({"A/a.pak": b"a", "B/b.pak": b"b", "B/b.ucas": b"c"}), archive_import_mode="separate")
        archive.selected = {1}
        self.run_import([archive])
        self.assertEqual({path.name for path in self.source.iterdir()}, {"b.pak", "b.ucas"})

    def test_together_collision_keeps_related_group_stems_consistent(self):
        archive = self.prepare(self.archive({"A/mod.pak": b"A", "A/mod.ucas": b"Ac", "B/mod.pak": b"B", "B/mod.ucas": b"Bc"}))
        self.run_import([archive])
        self.assertEqual((self.source / "archive" / "mod (1).pak").read_bytes(), b"B")
        self.assertEqual((self.source / "archive" / "mod (1).ucas").read_bytes(), b"Bc")

    def test_replacement_skip_and_keep_both_against_existing_mod(self):
        (self.source / "mod.pak").write_bytes(b"old")
        archive = self.prepare(self.archive({"mod.pak": b"new"}), archive_import_mode="separate")
        self.assertEqual(resolve_plans(self.cfg, create_plans([archive], lambda _name: "skip"), lambda _name: "skip"), [])
        self.run_import([archive])
        self.assertEqual((self.source / "mod.pak").read_bytes(), b"old")
        self.assertEqual((self.source / "mod (1).pak").read_bytes(), b"new")
        self.run_import([archive], "replace")
        self.assertEqual((self.source / "mod.pak").read_bytes(), b"new")

    def test_group_rename_avoids_existing_secondary_member(self):
        (self.source / "mod.ucas").write_bytes(b"old")
        archive = self.prepare(self.archive({"mod.pak": b"p", "mod.ucas": b"c"}), archive_import_mode="separate")
        plans = self.run_import([archive])
        self.assertEqual(plans[0].name, "mod (1).pak")
        self.assertEqual((self.source / "mod (1).ucas").read_bytes(), b"c")
        self.assertEqual((self.source / "mod.ucas").read_bytes(), b"old")

    def test_ignore_filter_normalizes_extensions_and_overrides_group_extensions(self):
        archive = self.prepare(self.archive({"a.pak": b"p", "a.ucas": b"c", "readme.TXT": b"t", "readme.md": b"m"}), mod_extensions="", import_ignore_extensions="TXT, .Md,.UCAS")
        self.assertEqual([unit.name for unit in archive.units], ["a.pak"])

    def test_normal_folder_import_filters_nested_files_without_changing_existing_sources(self):
        folder = self.root / "folder"
        (folder / "Data").mkdir(parents=True)
        (folder / "Empty").mkdir()
        (folder / "Data" / "a.pak").write_bytes(b"a")
        (folder / "Data" / "readme.TXT").write_bytes(b"readme")
        cfg = {**self.cfg, "import_ignore_extensions": "txt"}
        self.assertTrue(import_mod_file(cfg, folder)[0])
        self.assertEqual((self.source / "folder" / "Data" / "a.pak").read_bytes(), b"a")
        self.assertFalse((self.source / "folder" / "Data" / "readme.TXT").exists())
        self.assertTrue((self.source / "folder" / "Empty").is_dir())
        self.assertTrue((folder / "Data" / "readme.TXT").exists())
        self.assertFalse(import_mod_file(cfg, folder / "Data" / "readme.TXT")[0])

    def test_replacement_failure_restores_previous_folder(self):
        old = self.source / "archive"
        old.mkdir()
        (old / "original.pak").write_bytes(b"original")
        archive = self.prepare(self.archive())
        plans = resolve_plans(self.cfg, create_plans([archive], lambda _name: "replace"), lambda _name: "replace")
        with patch("mod_manager.imports.register_directory_mod", side_effect=OSError("storage unavailable")):
            imported, failed = execute_plans(self.cfg, plans)
        self.assertEqual(imported, [])
        self.assertIn("storage unavailable", failed[0])
        self.assertEqual((old / "original.pak").read_bytes(), b"original")
        self.assertFalse((old / "actualModFile.pak").exists())
        self.assertEqual(list(self.source.glob(".mod-import-*")), [])

    def test_read_only_new_file_does_not_prevent_restoring_old_mod_after_failure(self):
        (self.source / "mod.pak").write_bytes(b"original")
        incoming = self.root / "mod.pak"
        incoming.write_bytes(b"new")
        incoming.chmod(stat.S_IREAD)
        with patch("mod_manager.imports.ensure_mod_records", side_effect=OSError("metadata failed")):
            ok, message = import_mod_file(self.cfg, incoming, replace=True)
        self.assertFalse(ok)
        self.assertIn("metadata failed", message)
        self.assertEqual((self.source / "mod.pak").read_bytes(), b"original")
        self.assertEqual(incoming.read_bytes(), b"new")
        self.assertEqual(list(self.source.glob(".mod-import-*")), [])

    def test_failed_rollback_retains_original_data_for_recovery(self):
        (self.source / "mod.pak").write_bytes(b"original")
        incoming = self.root / "mod.pak"
        incoming.write_bytes(b"new")
        with patch("mod_manager.imports.ensure_mod_records", side_effect=OSError("metadata failed")), patch(
            "mod_manager.imports._remove_import_path", side_effect=PermissionError("file is locked")
        ):
            ok, message = import_mod_file(self.cfg, incoming, replace=True)
        self.assertFalse(ok)
        self.assertIn("Original data retained", message)
        recovery = list(self.source.glob(".mod-import-*"))
        self.assertEqual(len(recovery), 1)
        self.assertEqual((recovery[0] / "backup-0").read_bytes(), b"original")
        self.assertEqual((self.source / "mod.pak").read_bytes(), b"new")

    def test_image_failure_does_not_undo_mod_import(self):
        archive = self.prepare(self.archive(), archive_import_mode="separate")
        archive.images[0] = self.root / "missing.png"
        imported, failed = execute_plans(self.cfg, create_plans([archive], lambda _name: "skip"))
        self.assertEqual(len(imported), 1)
        self.assertEqual(failed, [])
        self.assertIn("preview failed", imported[0])
        self.assertTrue((self.source / "actualModFile.pak").exists())

    def test_directory_registration_is_scoped_to_source_and_profile(self):
        self.run_import([self.prepare(self.archive())])
        self.assertEqual(directory_mods({**self.cfg, "active_game_profile_id": "other"}), set())
        self.assertEqual(directory_mods({**self.cfg, "mods_source_dir": str(self.root / "other")}), set())

    def test_real_seven_zip_nested_payload(self):
        staging = self.root / "staging"
        (staging / "nested" / "more").mkdir(parents=True)
        (staging / "nested" / "more" / "Тест.pak").write_bytes(b"seven zip payload")
        archive_path = self.root / "test.7z"
        result = subprocess.run([str(seven_zip_path()), "a", str(archive_path), "nested"], cwd=staging, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stderr)
        archive = self.prepare(archive_path)
        self.run_import([archive])
        self.assertEqual((self.source / "test" / "Тест.pak").read_bytes(), b"seven zip payload")

    def test_password_protected_seven_zip_fails_without_waiting_for_input(self):
        payload = self.root / "a.pak"
        payload.write_bytes(b"a")
        archive_path = self.root / "password.7z"
        result = subprocess.run([str(seven_zip_path()), "a", "-ptest", "-mhe=on", str(archive_path), str(payload)], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0)
        with self.assertRaises(ArchiveError):
            self.prepare(archive_path)

    def test_real_rar_with_nested_unicode_paths(self):
        fixture = Path(__file__).parent / "fixtures" / "rar5-subdirs.rar"
        archive = self.prepare(fixture, mod_extensions=".txt", archive_preserve_structure=True)
        self.assertEqual(len(archive.units), 4)
        self.run_import([archive])
        target = self.source / "rar5-subdirs" / "sub"
        self.assertEqual((target / "dir1" / "file1.txt").read_bytes(), b"file1\n")
        self.assertEqual((target / "with space" / "long fn.txt").read_bytes(), b"long fn\n")
        self.assertEqual(len(list(target.rglob("*.txt"))), 4)

    def test_regular_related_files_are_renamed_as_one_group(self):
        (self.source / "mod.pak").write_bytes(b"old")
        incoming = self.root / "incoming"
        incoming.mkdir()
        paths = []
        for extension in (".ucas", ".utoc", ".pak"):
            path = incoming / f"mod{extension}"
            path.write_bytes(extension.encode())
            paths.append(path)
        tasks = regular_import_tasks(self.cfg, paths, set(), lambda _name: "keep_both")
        self.assertEqual(_run_import_batch(self.cfg, tasks), (["mod (1).pak"], []))
        self.assertEqual((self.source / "mod (1).pak").read_bytes(), b".pak")
        self.assertEqual((self.source / "mod (1).ucas").read_bytes(), b".ucas")
        self.assertEqual((self.source / "mod.pak").read_bytes(), b"old")
        self.assertEqual(len(discover_mods(self.cfg)), 2)

    def test_cancelled_import_does_not_publish_or_replace_anything(self):
        (self.source / "actualModFile.pak").write_bytes(b"old")
        archive = self.prepare(self.archive(), archive_import_mode="separate")
        plans = resolve_plans(self.cfg, create_plans([archive], lambda _name: "replace"), lambda _name: "replace")
        cancelled = Event()
        cancelled.set()
        imported, failed = execute_plans(self.cfg, plans, cancelled)
        self.assertEqual(imported, [])
        self.assertEqual(failed, ["Import cancelled."])
        self.assertEqual((self.source / "actualModFile.pak").read_bytes(), b"old")

    def test_imported_folder_installs_and_uninstalls_by_link_and_copy(self):
        self.run_import([self.prepare(self.archive(), archive_preserve_structure=True)])
        game = Path(self.cfg["game_mods_dir"])
        game.mkdir()
        for mode in ("link", "copy"):
            with self.subTest(mode=mode):
                cfg = {**self.cfg, "install_mode": mode}
                self.assertEqual(apply_mods_batch(discover_mods(cfg)), [(True, "OK")])
                installed_payload = game / "archive" / "someFolder" / "someFolder" / "actualModFile.pak"
                self.assertEqual(installed_payload.read_bytes(), b"pak payload")
                self.assertTrue(discover_mods(cfg)[0].installed)
                self.assertTrue(deactivate_mod(discover_mods(cfg)[0])[0])
                self.assertFalse((game / "archive").exists())
                self.assertEqual((self.source / "archive" / "someFolder" / "someFolder" / "actualModFile.pak").read_bytes(), b"pak payload")

    def test_imported_folder_stays_available_to_saved_presets_after_reload(self):
        self.run_import([self.prepare(self.archive())])
        cfg = {**self.cfg, "install_mode": "copy"}
        Path(cfg["game_mods_dir"]).mkdir()
        self.assertEqual(apply_mods_batch(discover_mods(cfg)), [(True, "OK")])
        self.assertTrue(save_preset_from_installed(cfg, "archive preset")[0])
        self.assertTrue(deactivate_mod(discover_mods(cfg)[0])[0])
        self.assertEqual(apply_preset(dict(cfg), "archive preset")[:2], (1, 0))
        self.assertEqual((Path(cfg["game_mods_dir"]) / "archive" / "actualModFile.pak").read_bytes(), b"pak payload")

    def test_unsafe_windows_paths_rejected_before_writing(self):
        for path in ("../escape.pak", "/escape.pak", "C:/escape.pak", "a/../b.pak", "a:stream", "NUL.pak", "a /b.pak", "a/./b.pak", "a//b.pak"):
            with self.subTest(path=path), self.assertRaises(ArchiveError):
                safe_relative_path(path)

    def test_zip_path_traversal_and_duplicate_paths_are_rejected(self):
        for members in ({"../escape.pak": b"escape"}, {"A.pak": b"A", "a.pak": b"a"}, {"a": b"file", "a/mod.pak": b"nested"}):
            with self.subTest(members=members), self.assertRaises(ArchiveError):
                self.prepare(self.archive(members))
        self.assertFalse((self.root / "escape.pak").exists())

    def test_zip_symlink_is_rejected(self):
        path = self.root / "symlink.zip"
        with zipfile.ZipFile(path, "w") as archive:
            entry = zipfile.ZipInfo("linked.pak")
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(entry, "outside")
        with self.assertRaises(ArchiveError):
            self.prepare(path)

    def test_empty_and_unsupported_archives_are_reported(self):
        with self.assertRaisesRegex(ArchiveError, "No supported"):
            self.prepare(self.archive({"readme.txt": b"readme"}))
        corrupt = self.root / "corrupt.zip"
        corrupt.write_bytes(b"invalid")
        with self.assertRaises(ArchiveError):
            self.prepare(corrupt)
