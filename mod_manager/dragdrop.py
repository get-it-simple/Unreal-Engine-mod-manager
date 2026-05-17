from __future__ import annotations

import ctypes
from pathlib import Path
from typing import Callable, List

from .platform_utils import is_windows


S_OK = 0
E_NOINTERFACE = 0x80004002
CF_HDROP = 15
DVASPECT_CONTENT = 1
TYMED_HGLOBAL = 1
DROPEFFECT_COPY = 1


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class FORMATETC(ctypes.Structure):
    _fields_ = [
        ("cfFormat", ctypes.c_ushort),
        ("ptd", ctypes.c_void_p),
        ("dwAspect", ctypes.c_ulong),
        ("lindex", ctypes.c_long),
        ("tymed", ctypes.c_ulong),
    ]


class STGMEDIUM(ctypes.Structure):
    _fields_ = [
        ("tymed", ctypes.c_ulong),
        ("hGlobal", ctypes.c_void_p),
        ("pUnkForRelease", ctypes.c_void_p),
    ]


class POINTL(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


IID_IUNKNOWN = GUID(0x00000000, 0x0000, 0x0000, (ctypes.c_ubyte * 8)(0xC0, 0, 0, 0, 0, 0, 0, 0x46))
IID_IDROPTARGET = GUID(0x00000122, 0x0000, 0x0000, (ctypes.c_ubyte * 8)(0xC0, 0, 0, 0, 0, 0, 0, 0x46))


def _same_guid(a, b) -> bool:
    return ctypes.string_at(a, ctypes.sizeof(GUID)) == ctypes.string_at(ctypes.byref(b), ctypes.sizeof(GUID))


class WindowsDropTarget:
    def __init__(self, widget, callback: Callable[[List[Path], int, int], None]):
        self.widget = widget
        self.callback = callback
        self.enabled = False
        self.ref_count = 1
        self.vtable = None
        self.com_object = None
        self._callbacks = []
        if is_windows():
            self.enable()

    def enable(self) -> None:
        if self.enabled:
            return
        self.widget.update_idletasks()
        hwnd = self.widget.winfo_id()
        ctypes.windll.ole32.OleInitialize(None)

        QUERY = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
        ADDREF = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
        RELEASE = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
        DRAGENTER = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, POINTL, ctypes.POINTER(ctypes.c_ulong))
        DRAGOVER = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_ulong, POINTL, ctypes.POINTER(ctypes.c_ulong))
        DRAGLEAVE = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)
        DROP = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, POINTL, ctypes.POINTER(ctypes.c_ulong))

        def query_interface(_this, riid, ppv):
            if _same_guid(riid, IID_IUNKNOWN) or _same_guid(riid, IID_IDROPTARGET):
                ppv[0] = ctypes.cast(ctypes.pointer(self.com_object), ctypes.c_void_p)
                self.add_ref()
                return S_OK
            ppv[0] = None
            return E_NOINTERFACE

        def add_ref(_this=None):
            self.ref_count += 1
            return self.ref_count

        def release(_this=None):
            self.ref_count = max(1, self.ref_count - 1)
            return self.ref_count

        def drag_enter(_this, data_object, _key_state, _point, effect):
            effect[0] = DROPEFFECT_COPY if self._has_files(data_object) else 0
            return S_OK

        def drag_over(_this, _key_state, _point, effect):
            effect[0] = DROPEFFECT_COPY
            return S_OK

        def drag_leave(_this):
            return S_OK

        def drop(_this, data_object, _key_state, point, effect):
            paths = self._read_files(data_object)
            effect[0] = DROPEFFECT_COPY if paths else 0
            if paths:
                self.widget.after(0, lambda: self.callback(paths, point.x, point.y))
            return S_OK

        self.add_ref = add_ref
        self._callbacks = [
            QUERY(query_interface),
            ADDREF(add_ref),
            RELEASE(release),
            DRAGENTER(drag_enter),
            DRAGOVER(drag_over),
            DRAGLEAVE(drag_leave),
            DROP(drop),
        ]
        VTABLE = ctypes.c_void_p * len(self._callbacks)
        self.vtable = VTABLE(*[ctypes.cast(cb, ctypes.c_void_p).value for cb in self._callbacks])

        class COMObject(ctypes.Structure):
            _fields_ = [("lpVtbl", ctypes.POINTER(VTABLE))]

        self.com_object = COMObject(ctypes.pointer(self.vtable))
        result = ctypes.windll.ole32.RegisterDragDrop(hwnd, ctypes.byref(self.com_object))
        self.enabled = result == S_OK

    def _get_data(self, data_object):
        format_etc = FORMATETC(CF_HDROP, None, DVASPECT_CONTENT, -1, TYMED_HGLOBAL)
        medium = STGMEDIUM()
        vtable = ctypes.cast(data_object, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        get_data = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(FORMATETC), ctypes.POINTER(STGMEDIUM))(vtable[3])
        result = get_data(data_object, ctypes.byref(format_etc), ctypes.byref(medium))
        if result != S_OK:
            return None
        return medium

    def _has_files(self, data_object) -> bool:
        medium = self._get_data(data_object)
        if not medium:
            return False
        ctypes.windll.ole32.ReleaseStgMedium(ctypes.byref(medium))
        return True

    def _read_files(self, data_object) -> List[Path]:
        medium = self._get_data(data_object)
        if not medium:
            return []
        shell32 = ctypes.windll.shell32
        count = shell32.DragQueryFileW(medium.hGlobal, 0xFFFFFFFF, None, 0)
        paths = []
        for index in range(count):
            size = shell32.DragQueryFileW(medium.hGlobal, index, None, 0) + 1
            buffer = ctypes.create_unicode_buffer(size)
            shell32.DragQueryFileW(medium.hGlobal, index, buffer, size)
            paths.append(Path(buffer.value))
        ctypes.windll.ole32.ReleaseStgMedium(ctypes.byref(medium))
        return paths
