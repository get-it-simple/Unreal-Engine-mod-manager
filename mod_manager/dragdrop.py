from __future__ import annotations

import ctypes
import ctypes.wintypes
import queue
import tempfile
from pathlib import Path
from typing import Callable, List

from .platform_utils import is_windows
from .log import logger

_POLL_MS = 50

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
    ptr = kernel32.GlobalLock(ctypes.c_void_p(hglobal))
    if not ptr:
        return None
    try:
        size = kernel32.GlobalSize(ctypes.c_void_p(hglobal))
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
    return b"".join(chunks) if chunks else None


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
    data = _read_hglobal(kernel32, medium.hGlobal)
    ole32.ReleaseStgMedium(ctypes.byref(medium))
    if not data or len(data) < 4:
        return []

    count = ctypes.c_uint.from_buffer_copy(data).value
    desc_size = ctypes.sizeof(FILEDESCRIPTORW)
    tmpdir = None
    paths = []

    for i in range(count):
        off = 4 + i * desc_size
        if off + desc_size > len(data):
            break
        desc = FILEDESCRIPTORW.from_buffer_copy(data[off:off + desc_size])
        name = desc.cFileName
        if not name:
            continue

        # Try HGLOBAL first, then IStream
        medium = _get_data(ole32, pDataObj, cf_filecontents, lindex=i, tymed=TYMED_HGLOBAL)
        if medium is not None and medium.tymed == TYMED_HGLOBAL:
            file_data = _read_hglobal(kernel32, medium.hGlobal)
            ole32.ReleaseStgMedium(ctypes.byref(medium))
        else:
            if medium is not None:
                ole32.ReleaseStgMedium(ctypes.byref(medium))
            medium = _get_data(ole32, pDataObj, cf_filecontents, lindex=i, tymed=TYMED_ISTREAM)
            if medium is None:
                continue
            file_data = _read_istream(medium.hGlobal) if medium.tymed == TYMED_ISTREAM else None
            ole32.ReleaseStgMedium(ctypes.byref(medium))

        if not file_data:
            continue

        if tmpdir is None:
            tmpdir = tempfile.mkdtemp(prefix="mods_drop_")
        dest = Path(tmpdir) / Path(name).name
        try:
            dest.write_bytes(file_data)
            paths.append(dest)
        except Exception as exc:
            logger.error("dragdrop: write temp file failed: %s", exc)

    return paths


class WindowsDropTarget:
    def __init__(self, widget, callback: Callable[[List[Path], int, int], None]):
        self.widget = widget
        self.callback = callback
        self._pending: queue.SimpleQueue = queue.SimpleQueue()
        self._com_obj = None
        self._vtbl = None
        self._fn_refs = []
        self._hwnd = None
        self._ole32 = None
        self.enabled = False
        if is_windows():
            self.enable()

    def enable(self) -> None:
        if self.enabled:
            return
        try:
            self.widget.update_idletasks()
            hwnd = self.widget.winfo_id()
            ole32, shell32, kernel32, user32 = _setup_apis()
            self._ole32 = ole32

            hr = ole32.OleInitialize(None)
            if hr not in (S_OK, 1):  # S_FALSE=1 means already initialized
                logger.warning("dragdrop: OleInitialize returned 0x%x", hr & 0xFFFFFFFF)

            cf_filedesc     = user32.RegisterClipboardFormatW("FileGroupDescriptorW")
            cf_filecontents = user32.RegisterClipboardFormatW("FileContents")
            pending = self._pending

            ref_count = ctypes.c_long(1)

            def _qi(this, riid, ppv):
                iid = bytes((ctypes.c_byte * 16).from_address(riid))
                if iid in (_IID_IUnknown, _IID_IDropTarget):
                    ppv[0] = ctypes.cast(ctypes.c_void_p(this), ctypes.c_void_p)
                    return S_OK
                ppv[0] = None
                return E_NOINTERFACE

            def _addref(this):
                ref_count.value += 1
                return ref_count.value

            def _release(this):
                ref_count.value -= 1
                return ref_count.value

            def _drag_enter(this, pDataObj, grfKeyState, pt, pdwEffect):
                pdwEffect[0] = DROPEFFECT_COPY
                return S_OK

            def _drag_over(this, grfKeyState, pt, pdwEffect):
                pdwEffect[0] = DROPEFFECT_COPY
                return S_OK

            def _drag_leave(this):
                return S_OK

            def _drop(this, pDataObj, grfKeyState, pt, pdwEffect):
                try:
                    paths = []
                    medium = _get_data(ole32, pDataObj, CF_HDROP)
                    if medium is not None:
                        paths = _extract_hdrop(shell32, medium)
                        ole32.ReleaseStgMedium(ctypes.byref(medium))
                    if not paths:
                        paths = _extract_virtual(ole32, kernel32, pDataObj, cf_filedesc, cf_filecontents)
                    if paths:
                        logger.info("dragdrop: %d file(s): %s", len(paths), [p.name for p in paths])
                        pending.put((paths, pt.x, pt.y))
                        pdwEffect[0] = DROPEFFECT_COPY
                    else:
                        pdwEffect[0] = DROPEFFECT_NONE
                except Exception as exc:
                    logger.error("dragdrop: Drop error: %s", exc, exc_info=True)
                    pdwEffect[0] = DROPEFFECT_NONE
                return S_OK

            fn_qi    = _QI_T(_qi)
            fn_add   = _REF_T(_addref)
            fn_rel   = _REF_T(_release)
            fn_enter = _ENTER_T(_drag_enter)
            fn_over  = _OVER_T(_drag_over)
            fn_leave = _LEAVE_T(_drag_leave)
            fn_drop  = _DROP_T(_drop)

            # Keep all function objects alive
            self._fn_refs = [fn_qi, fn_add, fn_rel, fn_enter, fn_over, fn_leave, fn_drop]

            vtbl = _Vtbl(
                QueryInterface=fn_qi,
                AddRef=fn_add,
                Release=fn_rel,
                DragEnter=fn_enter,
                DragOver=fn_over,
                DragLeave=fn_leave,
                Drop=fn_drop,
            )
            self._vtbl = vtbl

            obj = _COMObj()
            obj.lpVtbl = ctypes.pointer(vtbl)
            self._com_obj = obj
            self._hwnd = hwnd

            obj_ptr = ctypes.cast(ctypes.pointer(obj), ctypes.c_void_p)
            hr = ole32.RegisterDragDrop(ctypes.c_void_p(hwnd), obj_ptr)
            if hr != S_OK:
                logger.error("dragdrop: RegisterDragDrop failed hr=0x%x", hr & 0xFFFFFFFF)
                return

            self.enabled = True
            logger.info("dragdrop: OLE drop target registered hwnd=%s", hwnd)
            self._start_poll()
        except Exception as exc:
            logger.error("dragdrop: enable failed: %s", exc, exc_info=True)

    def disable(self) -> None:
        if self.enabled and self._hwnd and self._ole32:
            try:
                self._ole32.RevokeDragDrop(ctypes.c_void_p(self._hwnd))
            except Exception as exc:
                logger.error("dragdrop: RevokeDragDrop failed: %s", exc)
            self.enabled = False

    def _start_poll(self) -> None:
        def poll():
            while not self._pending.empty():
                try:
                    paths, x, y = self._pending.get_nowait()
                    self.callback(paths, x, y)
                except Exception as exc:
                    logger.error("dragdrop: callback error: %s", exc, exc_info=True)
            try:
                self.widget.after(_POLL_MS, poll)
            except Exception:
                pass

        self.widget.after(_POLL_MS, poll)
