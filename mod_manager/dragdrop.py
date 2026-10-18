from __future__ import annotations

import ctypes
import ctypes.wintypes
import queue
import tempfile
from pathlib import Path
from typing import Callable, List

from .platform_utils import is_windows
from .log import logger
from .archive_backend import ArchiveError, safe_relative_path

_POLL_MS = 50


class TransferredPaths(list):
    def __init__(self, paths, owner: tempfile.TemporaryDirectory):
        super().__init__(paths)
        self.owner = owner
        self.temporary_root = Path(owner.name)

    def close(self) -> None:
        if self.owner is not None:
            self.owner.cleanup()
            self.owner = None

# COM constants
S_OK = 0
E_NOINTERFACE = ctypes.c_long(0x80004002).value
DROPEFFECT_NONE = 0
DROPEFFECT_COPY = 1
DVASPECT_CONTENT = 1
TYMED_HGLOBAL = 1
TYMED_ISTREAM = 4
CF_HDROP = 15

# IDropTarget IID: {00000122-0000-0000-C000-000000000046}
_IID_IDropTarget = bytes([
    0x22, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46,
])
# IUnknown IID: {00000000-0000-0000-C000-000000000046}
_IID_IUnknown = bytes([
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46,
])


# ---------- COM structures ----------

class POINTL(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class FORMATETC(ctypes.Structure):
    _fields_ = [
        ("cfFormat", ctypes.c_ushort),
        ("ptd",      ctypes.c_void_p),
        ("dwAspect", ctypes.c_ulong),
        ("lindex",   ctypes.c_long),
        ("tymed",    ctypes.c_ulong),
    ]


class STGMEDIUM(ctypes.Structure):
    _fields_ = [
        ("tymed",          ctypes.c_ulong),
        ("hGlobal",        ctypes.c_void_p),   # union – only hGlobal / pstm used
        ("pUnkForRelease", ctypes.c_void_p),
    ]


class FILEDESCRIPTORW(ctypes.Structure):
    _fields_ = [
        ("dwFlags",          ctypes.c_ulong),
        ("clsid",            ctypes.c_byte * 16),
        ("sizel",            ctypes.c_long * 2),
        ("pointl",           ctypes.c_long * 2),
        ("dwFileAttributes", ctypes.c_ulong),
        ("ftCreationTime",   ctypes.c_ulonglong),
        ("ftLastAccessTime", ctypes.c_ulonglong),
        ("ftLastWriteTime",  ctypes.c_ulonglong),
        ("nFileSizeHigh",    ctypes.c_ulong),
        ("nFileSizeLow",     ctypes.c_ulong),
        ("cFileName",        ctypes.c_wchar * 260),
    ]


# ---------- vtable types ----------

_F = ctypes.WINFUNCTYPE

_QI_T   = _F(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
_REF_T  = _F(ctypes.c_ulong,  ctypes.c_void_p)
_ENTER_T = _F(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, POINTL, ctypes.POINTER(ctypes.c_ulong))
_OVER_T  = _F(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_ulong,  POINTL, ctypes.POINTER(ctypes.c_ulong))
_LEAVE_T = _F(ctypes.HRESULT, ctypes.c_void_p)
_DROP_T  = _F(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, POINTL, ctypes.POINTER(ctypes.c_ulong))


class _Vtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", _QI_T),
        ("AddRef",         _REF_T),
        ("Release",        _REF_T),
        ("DragEnter",      _ENTER_T),
        ("DragOver",       _OVER_T),
        ("DragLeave",      _LEAVE_T),
        ("Drop",           _DROP_T),
    ]


class _COMObj(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(_Vtbl))]


# IDataObject.GetData is vtable slot 3
# Use c_long (not HRESULT) so ctypes returns the value instead of raising OSError on failure HRESULTs
_GETDATA_T = _F(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(FORMATETC), ctypes.POINTER(STGMEDIUM))
# IStream.Read is vtable slot 3
_STREAMREAD_T = _F(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong))


def _vtbl_slot(com_ptr, index, fn_type):
    vtbl = ctypes.cast(ctypes.cast(com_ptr, ctypes.POINTER(ctypes.c_void_p)).contents, ctypes.POINTER(ctypes.c_void_p))
    return fn_type(vtbl[index])


def _setup_apis():
    ole32   = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32
    kernel32 = ctypes.windll.kernel32
    user32  = ctypes.windll.user32

    ole32.OleInitialize.argtypes  = [ctypes.c_void_p]
    ole32.OleInitialize.restype   = ctypes.HRESULT
    ole32.RegisterDragDrop.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    ole32.RegisterDragDrop.restype  = ctypes.HRESULT
    ole32.RevokeDragDrop.argtypes   = [ctypes.c_void_p]
    ole32.RevokeDragDrop.restype    = ctypes.HRESULT
    ole32.ReleaseStgMedium.argtypes = [ctypes.POINTER(STGMEDIUM)]
    ole32.ReleaseStgMedium.restype  = None

    shell32.DragQueryFileW.restype  = ctypes.c_uint
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]

    kernel32.GlobalLock.argtypes   = [ctypes.c_void_p]
    kernel32.GlobalLock.restype    = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalSize.argtypes   = [ctypes.c_void_p]
    kernel32.GlobalSize.restype    = ctypes.c_size_t

    user32.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
    user32.RegisterClipboardFormatW.restype  = ctypes.c_uint

    return ole32, shell32, kernel32, user32


def _read_hglobal(kernel32, hglobal):
    size = kernel32.GlobalSize(ctypes.c_void_p(hglobal))
    if hglobal and size == 0:
        return b""
    ptr = kernel32.GlobalLock(ctypes.c_void_p(hglobal))
    if not ptr:
        return None
    try:
        return ctypes.string_at(ptr, size)
    finally:
        kernel32.GlobalUnlock(ctypes.c_void_p(hglobal))


def _read_istream(pstm):
    read_fn = _vtbl_slot(pstm, 3, _STREAMREAD_T)
    chunks = []
    buf = ctypes.create_string_buffer(65536)
    while True:
        n = ctypes.c_ulong(0)
        hr = read_fn(pstm, buf, len(buf), ctypes.byref(n))
        if n.value:
            chunks.append(bytes(buf[:n.value]))
        if hr != S_OK or n.value == 0:
            break
    return b"".join(chunks)


def _get_data(ole32, pDataObj, cf_format, lindex=-1, tymed=TYMED_HGLOBAL):
    get_fn = _vtbl_slot(pDataObj, 3, _GETDATA_T)
    fmt = FORMATETC(cfFormat=cf_format, ptd=None, dwAspect=DVASPECT_CONTENT, lindex=lindex, tymed=tymed)
    medium = STGMEDIUM()
    hr = get_fn(pDataObj, ctypes.byref(fmt), ctypes.byref(medium))
    if hr != S_OK:
        return None
    return medium


def _extract_hdrop(shell32, medium):
    hdrop = ctypes.c_void_p(medium.hGlobal)
    count = shell32.DragQueryFileW(hdrop, ctypes.c_uint(0xFFFFFFFF), None, 0)
    paths = []
    for i in range(count):
        size = shell32.DragQueryFileW(hdrop, ctypes.c_uint(i), None, 0) + 1
        buf = ctypes.create_unicode_buffer(size)
        shell32.DragQueryFileW(hdrop, ctypes.c_uint(i), buf, ctypes.c_uint(size))
        paths.append(Path(buf.value))
    return paths


def _extract_virtual(ole32, kernel32, pDataObj, cf_filedesc, cf_filecontents):
    medium = _get_data(ole32, pDataObj, cf_filedesc)
    if medium is None:
        return []
    try:
        data = _read_hglobal(kernel32, medium.hGlobal)
    finally:
        ole32.ReleaseStgMedium(ctypes.byref(medium))
    if not data or len(data) < 4:
        return []

    count = ctypes.c_uint.from_buffer_copy(data).value
    desc_size = ctypes.sizeof(FILEDESCRIPTORW)
    if count > (len(data) - 4) // desc_size:
        raise ArchiveError("The transferred archive file list is incomplete.")
    descriptors = [FILEDESCRIPTORW.from_buffer_copy(data[4 + i * desc_size:4 + (i + 1) * desc_size]) for i in range(count)]
    relatives = [safe_relative_path(desc.cFileName) for desc in descriptors]
    if len({path.as_posix().casefold() for path in relatives}) != len(relatives):
        raise ArchiveError("Duplicate transferred archive paths.")
    owner = tempfile.TemporaryDirectory(prefix="mods-drop-")
    root = Path(owner.name)
    try:
        for i, (desc, relative) in enumerate(zip(descriptors, relatives)):
            dest = root / relative
            if desc.dwFileAttributes & 0x400:
                raise ArchiveError("Linked transferred files are unsupported.")
            if desc.dwFileAttributes & 0x10:
                dest.mkdir(parents=True, exist_ok=True)
                continue
            medium = _get_data(ole32, pDataObj, cf_filecontents, lindex=i, tymed=TYMED_HGLOBAL)
            if medium is not None:
                try:
                    file_data = _read_hglobal(kernel32, medium.hGlobal) if medium.tymed == TYMED_HGLOBAL else None
                finally:
                    ole32.ReleaseStgMedium(ctypes.byref(medium))
            else:
                file_data = None
            if file_data is None:
                medium = _get_data(ole32, pDataObj, cf_filecontents, lindex=i, tymed=TYMED_ISTREAM)
                if medium is None:
                    raise ArchiveError(f"Cannot read transferred file: {relative}")
                try:
                    file_data = _read_istream(medium.hGlobal) if medium.tymed == TYMED_ISTREAM else None
                finally:
                    ole32.ReleaseStgMedium(ctypes.byref(medium))
            if file_data is None:
                raise ArchiveError(f"Cannot read transferred file: {relative}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(file_data)
        return TransferredPaths(sorted(root.iterdir(), key=lambda path: path.name.casefold()), owner)
    except Exception:
        owner.cleanup()
        raise


def read_virtual_clipboard_paths() -> List[Path]:
    ole32, _shell32, kernel32, user32 = _setup_apis()
    ole32.OleGetClipboard.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    ole32.OleGetClipboard.restype = ctypes.c_long
    ole32.OleUninitialize.argtypes = []
    ole32.OleUninitialize.restype = None
    initialized = ole32.OleInitialize(None) in (S_OK, 1)
    data_object = ctypes.c_void_p()
    try:
        if ole32.OleGetClipboard(ctypes.byref(data_object)) != S_OK or not data_object.value:
            return []
        descriptors = user32.RegisterClipboardFormatW("FileGroupDescriptorW")
        contents = user32.RegisterClipboardFormatW("FileContents")
        return _extract_virtual(ole32, kernel32, data_object, descriptors, contents)
    finally:
        if data_object.value:
            _vtbl_slot(data_object, 2, _REF_T)(data_object)
        if initialized:
            ole32.OleUninitialize()


def clipboard_has_files() -> bool:
    if not is_windows():
        return False
    user32 = ctypes.windll.user32
    user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
    user32.IsClipboardFormatAvailable.restype = ctypes.c_bool
    user32.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
    user32.RegisterClipboardFormatW.restype = ctypes.c_uint
    virtual = user32.RegisterClipboardFormatW("FileGroupDescriptorW")
    return bool(user32.IsClipboardFormatAvailable(CF_HDROP) or user32.IsClipboardFormatAvailable(virtual))


def read_clipboard_paths() -> List[Path]:
    """Read CF_HDROP file paths from Windows clipboard."""
    if not is_windows():
        return []
    try:
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32

        user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
        user32.IsClipboardFormatAvailable.restype = ctypes.c_bool
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.restype = ctypes.c_bool
        user32.GetClipboardData.argtypes = [ctypes.c_uint]
        user32.GetClipboardData.restype = ctypes.c_void_p
        user32.CloseClipboard.restype = ctypes.c_bool
        shell32.DragQueryFileW.restype = ctypes.c_uint
        shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]

        if not user32.IsClipboardFormatAvailable(CF_HDROP):
            return read_virtual_clipboard_paths()
        if not user32.OpenClipboard(None):
            return []
        try:
            hdrop = ctypes.c_void_p(user32.GetClipboardData(CF_HDROP))
            if not hdrop:
                return []
            count = shell32.DragQueryFileW(hdrop, ctypes.c_uint(0xFFFFFFFF), None, 0)
            paths = []
            for i in range(count):
                size = shell32.DragQueryFileW(hdrop, ctypes.c_uint(i), None, 0) + 1
                buf = ctypes.create_unicode_buffer(size)
                shell32.DragQueryFileW(hdrop, ctypes.c_uint(i), buf, ctypes.c_uint(size))
                paths.append(Path(buf.value))
            return paths
        finally:
            user32.CloseClipboard()
    except Exception as exc:
        logger.error("clipboard: read failed: %s", exc)
        return []


def read_clipboard_image() -> Path | None:
    """Read raw image data from Windows clipboard (browser Copy Image).

    Tries the named 'PNG' format first (Chrome/Edge, lossless), then falls
    back to CF_DIB via Pillow.  Returns a temp .png Path, or None.
    """
    if not is_windows():
        return None
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        user32.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
        user32.RegisterClipboardFormatW.restype = ctypes.c_uint
        user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
        user32.IsClipboardFormatAvailable.restype = ctypes.c_bool
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.restype = ctypes.c_bool
        user32.GetClipboardData.argtypes = [ctypes.c_uint]
        user32.GetClipboardData.restype = ctypes.c_void_p
        user32.CloseClipboard.restype = ctypes.c_bool
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
        kernel32.GlobalSize.restype = ctypes.c_size_t

        CF_DIB = 8
        cf_png = user32.RegisterClipboardFormatW("PNG")

        # Prefer named PNG format (Chrome/Edge puts full PNG bytes here)
        for fmt, suffix in [(cf_png, ".png"), (CF_DIB, ".bmp")]:
            if not user32.IsClipboardFormatAvailable(fmt):
                continue
            if not user32.OpenClipboard(None):
                continue
            data = None
            try:
                handle = user32.GetClipboardData(fmt)
                if handle:
                    data = _read_hglobal(kernel32, handle)
            finally:
                user32.CloseClipboard()
            if not data:
                continue

            if fmt == cf_png:
                tmp = Path(tempfile.mktemp(suffix=".png", prefix="mods_clip_"))
                tmp.write_bytes(data)
                return tmp

            # CF_DIB: raw DIB bytes → convert via Pillow
            try:
                import io
                from PIL import Image
                img = Image.open(io.BytesIO(data))
                tmp = Path(tempfile.mktemp(suffix=".png", prefix="mods_clip_"))
                img.save(str(tmp), format="PNG")
                return tmp
            except Exception:
                pass

        # Last resort: Pillow ImageGrab handles CF_DIB / CF_BITMAP natively
        try:
            from PIL import ImageGrab
            img = ImageGrab.grabclipboard()
            if img is not None and not isinstance(img, list):
                tmp = Path(tempfile.mktemp(suffix=".png", prefix="mods_clip_"))
                img.save(str(tmp), format="PNG")
                return tmp
        except Exception:
            pass

        return None
    except Exception as exc:
        logger.error("clipboard: read_clipboard_image failed: %s", exc)
        return None
