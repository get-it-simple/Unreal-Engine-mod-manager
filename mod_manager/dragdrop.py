from __future__ import annotations

import ctypes
import queue
from pathlib import Path
from typing import Callable, List

from .platform_utils import is_windows
from .log import logger

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4
_POLL_MS = 50

_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.c_void_p,
    ctypes.c_uint,
    ctypes.c_void_p,
    ctypes.c_void_p,
)


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int)]


def _configure_apis() -> tuple:
    shell32 = ctypes.windll.shell32
    user32 = ctypes.windll.user32

    shell32.DragAcceptFiles.restype = None
    shell32.DragAcceptFiles.argtypes = [ctypes.c_void_p, ctypes.c_bool]
    shell32.DragQueryFileW.restype = ctypes.c_uint
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
    shell32.DragFinish.restype = None
    shell32.DragFinish.argtypes = [ctypes.c_void_p]

    user32.GetCursorPos.restype = ctypes.c_bool
    user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    user32.CallWindowProcW.restype = ctypes.c_ssize_t
    user32.CallWindowProcW.argtypes = [
        ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
        ctypes.c_void_p, ctypes.c_void_p,
    ]

    return shell32, user32


class WindowsDropTarget:
    def __init__(self, widget, callback: Callable[[List[Path], int, int], None]):
        self.widget = widget
        self.callback = callback
        self._proc_ref = None
        self._old_proc = 0
        self._pending: queue.SimpleQueue = queue.SimpleQueue()
        self.enabled = False
        if is_windows():
            self.enable()

    def enable(self) -> None:
        if self.enabled:
            return
        try:
            self.widget.update_idletasks()
            hwnd = self.widget.winfo_id()
            shell32, user32 = _configure_apis()

            shell32.DragAcceptFiles(ctypes.c_void_p(hwnd), True)
            self._old_proc = user32.GetWindowLongPtrW(ctypes.c_void_p(hwnd), GWLP_WNDPROC)
            if not self._old_proc:
                logger.error("dragdrop: GetWindowLongPtrW returned 0 for hwnd=%s", hwnd)
                return

            pending = self._pending

            def wnd_proc(h, msg, wparam, lparam):
                if msg == WM_DROPFILES:
                    try:
                        hdrop = ctypes.c_void_p(wparam)
                        count = shell32.DragQueryFileW(hdrop, ctypes.c_uint(0xFFFFFFFF), None, 0)
                        paths = []
                        for i in range(count):
                            size = shell32.DragQueryFileW(hdrop, ctypes.c_uint(i), None, 0) + 1
                            buf = ctypes.create_unicode_buffer(size)
                            shell32.DragQueryFileW(hdrop, ctypes.c_uint(i), buf, ctypes.c_uint(size))
                            paths.append(Path(buf.value))
                        shell32.DragFinish(hdrop)
                        if paths:
                            cursor = _POINT()
                            user32.GetCursorPos(ctypes.byref(cursor))
                            logger.info("dragdrop: %d file(s): %s", len(paths), [p.name for p in paths])
                            pending.put((paths, cursor.x, cursor.y))
                    except Exception as exc:
                        logger.error("dragdrop: WM_DROPFILES error: %s", exc, exc_info=True)
                    return 0
                try:
                    return user32.CallWindowProcW(self._old_proc, h, msg, wparam, lparam)
                except Exception as exc:
                    logger.error("dragdrop: CallWindowProcW msg=0x%x error: %s", msg, exc)
                    return 0

            self._proc_ref = _WNDPROC(wnd_proc)
            proc_ptr = ctypes.cast(self._proc_ref, ctypes.c_void_p)
            user32.SetWindowLongPtrW(ctypes.c_void_p(hwnd), GWLP_WNDPROC, proc_ptr)
            self.enabled = True
            logger.info("dragdrop: registered hwnd=%s", hwnd)
            self._start_poll()
        except Exception as exc:
            logger.error("dragdrop: enable failed: %s", exc, exc_info=True)

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
