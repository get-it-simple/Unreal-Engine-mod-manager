from __future__ import annotations

import ctypes
import struct
import unittest
from unittest.mock import Mock, patch

from mod_manager import dragdrop
from mod_manager.archive_backend import ArchiveError


class VirtualArchiveTransferTests(unittest.TestCase):
    def descriptors(self, entries):
        records = []
        for name, directory in entries:
            descriptor = dragdrop.FILEDESCRIPTORW()
            descriptor.cFileName = name
            descriptor.dwFileAttributes = 0x10 if directory else 0x80
            records.append(bytes(descriptor))
        return struct.pack("<I", len(records)) + b"".join(records)

    def test_virtual_folders_keep_paths_and_empty_files(self):
        ole32 = Mock()
        medium = Mock(tymed=dragdrop.TYMED_HGLOBAL)
        listing = self.descriptors([("Folder", True), ("Folder/nested/a.pak", False), ("Folder/nested/empty.pak", False)])
        with patch.object(dragdrop, "_get_data", return_value=medium), patch.object(dragdrop.ctypes, "byref", side_effect=lambda value: value), patch.object(
            dragdrop, "_read_hglobal", side_effect=[listing, b"payload", b""]
        ):
            paths = dragdrop._extract_virtual(ole32, Mock(), Mock(), 1, 2)
        try:
            self.assertEqual([path.name for path in paths], ["Folder"])
            self.assertEqual((paths[0] / "nested" / "a.pak").read_bytes(), b"payload")
            self.assertEqual((paths[0] / "nested" / "empty.pak").read_bytes(), b"")
        finally:
            root = paths.temporary_root
            paths.close()
        self.assertFalse(root.exists())

    def test_virtual_duplicate_names_and_traversal_are_rejected(self):
        for entries in ([("../escape.pak", False)], [("A.pak", False), ("a.pak", False)]):
            medium = Mock(tymed=dragdrop.TYMED_HGLOBAL)
            with self.subTest(entries=entries), patch.object(dragdrop, "_get_data", return_value=medium), patch.object(
                dragdrop.ctypes, "byref", side_effect=lambda value: value
            ), patch.object(dragdrop, "_read_hglobal", return_value=self.descriptors(entries)), self.assertRaises(ArchiveError):
                dragdrop._extract_virtual(Mock(), Mock(), Mock(), 1, 2)

    def test_missing_content_aborts_transfer_instead_of_creating_incomplete_mod(self):
        medium = Mock(tymed=dragdrop.TYMED_HGLOBAL)
        with patch.object(dragdrop, "_get_data", side_effect=[medium, None, None]), patch.object(
            dragdrop.ctypes, "byref", side_effect=lambda value: value
        ), patch.object(dragdrop, "_read_hglobal", return_value=self.descriptors([("missing.pak", False)])), self.assertRaises(ArchiveError):
            dragdrop._extract_virtual(Mock(), Mock(), Mock(), 1, 2)

    def test_virtual_clipboard_is_checked_when_hdrop_is_unavailable(self):
        user32 = Mock()
        user32.IsClipboardFormatAvailable.return_value = False
        with patch.object(dragdrop.ctypes, "windll", Mock(user32=user32)), patch.object(dragdrop, "read_virtual_clipboard_paths", return_value=["virtual.pak"]) as read:
            self.assertEqual(dragdrop.read_clipboard_paths(), ["virtual.pak"])
        read.assert_called_once()

    def test_empty_windows_hglobal_is_read_as_an_empty_file(self):
        _ole32, _shell32, kernel32, _user32 = dragdrop._setup_apis()
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        handle = kernel32.GlobalAlloc(2, 0)
        self.assertTrue(handle)
        try:
            self.assertEqual(dragdrop._read_hglobal(kernel32, handle), b"")
        finally:
            kernel32.GlobalFree(handle)
