from __future__ import annotations

import ctypes
import queue
from pathlib import Path
from typing import Callable, List

from PySide6 import QtCore

from ...dragdrop import (
    CF_HDROP,
    DROPEFFECT_COPY,
    DROPEFFECT_NONE,
    E_NOINTERFACE,
    S_OK,
    _COMObj,
    _ENTER_T,
    _DROP_T,
    _LEAVE_T,
    _OVER_T,
    _QI_T,
    _REF_T,
    _Vtbl,
    _extract_hdrop,
    _extract_virtual,
    _get_data,
    _IID_IDropTarget,
    _IID_IUnknown,
    _setup_apis,
)
from ...log import logger
from ...platform_utils import is_windows
from ..theme import tokens

DRAGDROP_E_ALREADYREGISTERED = ctypes.c_long(0x80040102).value


class QtWindowsDropTarget:
    """COM IDropTarget for a PySide6 viewport.

    Registers a raw OLE drop target on the widget's HWND so that both
    regular file paths (CF_HDROP) and virtual files extracted from a zip
    opened in Windows 11 Explorer (FileGroupDescriptorW + FileContents)
    are delivered to the callback.
    """

    def __init__(self, viewport, callback: Callable[[List[Path], int, int], None]):
        self.viewport = viewport
        self.callback = callback
        self._pending: queue.SimpleQueue = queue.SimpleQueue()
        self._com_obj = None
        self._vtbl = None
        self._fn_refs = []
        self._hwnd = None
        self._ole32 = None
        self._timer = None
        self.enabled = False
        self._disposed = False
        self._ole_initialized = False
        if is_windows():
            QtCore.QTimer.singleShot(tokens.IMMEDIATE_MS, self.enable)

    def enable(self) -> None:
        if self.enabled or self._disposed:
            return
        try:
            hwnd = int(self.viewport.winId())
            ole32, shell32, kernel32, user32 = _setup_apis()
            self._ole32 = ole32

            hr = ole32.OleInitialize(None)
            self._ole_initialized = hr in (S_OK, 1)
            if hr not in (S_OK, 1):
                logger.warning("dragdrop: OleInitialize returned 0x%x", hr & 0xFFFFFFFF)

            cf_filedesc = user32.RegisterClipboardFormatW("FileGroupDescriptorW")
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

            fn_qi = _QI_T(_qi)
            fn_add = _REF_T(_addref)
            fn_rel = _REF_T(_release)
            fn_enter = _ENTER_T(_drag_enter)
            fn_over = _OVER_T(_drag_over)
            fn_leave = _LEAVE_T(_drag_leave)
            fn_drop = _DROP_T(_drop)

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
            if hr == DRAGDROP_E_ALREADYREGISTERED:
                ole32.RevokeDragDrop(ctypes.c_void_p(hwnd))
                hr = ole32.RegisterDragDrop(ctypes.c_void_p(hwnd), obj_ptr)
            if hr != S_OK:
                logger.error("dragdrop: RegisterDragDrop failed hr=0x%x", hr & 0xFFFFFFFF)
                return

            self.enabled = True
            logger.info("dragdrop: COM drop target registered hwnd=%s", hwnd)
            self._start_poll()
        except Exception as exc:
            logger.error("dragdrop: QtWindowsDropTarget.enable failed: %s", exc, exc_info=True)

    def disable(self) -> None:
        self._disposed = True
        if self.enabled and self._hwnd and self._ole32:
            try:
                self._ole32.RevokeDragDrop(ctypes.c_void_p(self._hwnd))
            except Exception as exc:
                logger.error("dragdrop: RevokeDragDrop failed: %s", exc)
            self.enabled = False
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if self._ole_initialized and self._ole32:
            self._ole32.OleUninitialize()
            self._ole_initialized = False
        while not self._pending.empty():
            paths, _x, _y = self._pending.get_nowait()
            close = getattr(paths, "close", None)
            if close:
                close()

    def _start_poll(self) -> None:
        timer = QtCore.QTimer()
        timer.setInterval(tokens.WORKER_POLL_MS)
        timer.timeout.connect(self._poll)
        timer.start()
        self._timer = timer

    def _poll(self) -> None:
        while not self._pending.empty():
            try:
                paths, x, y = self._pending.get_nowait()
                self.callback(paths, x, y)
            except Exception as exc:
                logger.error("dragdrop: callback error: %s", exc, exc_info=True)


def dropped_paths(mime) -> list[Path]:
    return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]


def has_urls(mime) -> bool:
    return bool(mime is not None and mime.hasUrls())
