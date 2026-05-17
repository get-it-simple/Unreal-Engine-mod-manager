from __future__ import annotations

import ctypes
from pathlib import Path
from typing import Callable, List

from .platform_utils import is_windows


WM_DROPFILES = 0x0233
GWL_WNDPROC = -4


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class WindowsDropTarget:
    def __init__(self, widget, callback: Callable[[List[Path], int, int], None]):
        self.widget = widget
        self.callback = callback
        self.enabled = False
        self.hwnd = None
        self.old_proc = None
        self.proc = None
        if is_windows():
            self.enable()

    def enable(self) -> None:
        if self.enabled:
            return
        hwnd = self.widget.winfo_id()
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        try:
            LONG_PTR = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
            WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p)
            user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, LONG_PTR]
            user32.SetWindowLongPtrW.restype = LONG_PTR
            user32.CallWindowProcW.argtypes = [LONG_PTR, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
            user32.CallWindowProcW.restype = ctypes.c_longlong
        except AttributeError:
            WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p)
            user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
            user32.SetWindowLongW.restype = ctypes.c_long
            user32.CallWindowProcW.argtypes = [ctypes.c_long, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
            user32.CallWindowProcW.restype = ctypes.c_long

        def wndproc(h, msg, wparam, lparam):
            if msg == WM_DROPFILES:
                self._handle_drop(wparam)
                return 0
            return user32.CallWindowProcW(self.old_proc, h, msg, wparam, lparam)

        self.proc = WNDPROC(wndproc)
        if hasattr(user32, "SetWindowLongPtrW"):
            self.old_proc = user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, LONG_PTR(ctypes.cast(self.proc, ctypes.c_void_p).value))
        else:
            self.old_proc = user32.SetWindowLongW(hwnd, GWL_WNDPROC, ctypes.cast(self.proc, ctypes.c_void_p).value)
        shell32.DragAcceptFiles(hwnd, True)
        self.hwnd = hwnd
        self.enabled = True

    def _handle_drop(self, drop) -> None:
        shell32 = ctypes.windll.shell32
        count = shell32.DragQueryFileW(drop, 0xFFFFFFFF, None, 0)
        paths = []
        for index in range(count):
            size = shell32.DragQueryFileW(drop, index, None, 0) + 1
            buffer = ctypes.create_unicode_buffer(size)
            shell32.DragQueryFileW(drop, index, buffer, size)
            paths.append(Path(buffer.value))
        point = POINT()
        shell32.DragQueryPoint(drop, ctypes.byref(point))
        shell32.DragFinish(drop)
        self.widget.after(0, lambda: self.callback(paths, point.x, point.y))
