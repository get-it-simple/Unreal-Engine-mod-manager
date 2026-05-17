from __future__ import annotations

import base64
import ctypes
from pathlib import Path

import tkinter as tk

_GDI_TOKEN = ctypes.c_size_t(0)
_GDI_READY = False

_PF_32ARGB = 0x0026200A


class _CLSID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

_PNG_CLSID = _CLSID(
    0x557CF406, 0x1A04, 0x11D3,
    (ctypes.c_ubyte * 8)(0x9A, 0x73, 0x00, 0x00, 0xF8, 0x1E, 0xF3, 0x2E),
)
_LOCK_READ = 1
_INTERP_HQ_BICUBIC = 7
_UNIT_PIXEL = 2


class _StartupInput(ctypes.Structure):
    _fields_ = [
        ("Version", ctypes.c_uint32),
        ("DebugCallback", ctypes.c_void_p),
        ("SuppressBgThread", ctypes.c_int),
        ("SuppressCodecs", ctypes.c_int),
    ]


class _BitmapData(ctypes.Structure):
    _fields_ = [
        ("Width", ctypes.c_uint),
        ("Height", ctypes.c_uint),
        ("Stride", ctypes.c_int),
        ("PixelFormat", ctypes.c_int),
        ("Scan0", ctypes.c_void_p),
        ("Reserved", ctypes.c_size_t),
    ]


class _Rect(ctypes.Structure):
    _fields_ = [("X", ctypes.c_int), ("Y", ctypes.c_int), ("W", ctypes.c_int), ("H", ctypes.c_int)]


def _init() -> bool:
    global _GDI_READY
    if _GDI_READY:
        return True
    try:
        inp = _StartupInput(1, None, 0, 0)
        status = ctypes.windll.gdiplus.GdiplusStartup(ctypes.byref(_GDI_TOKEN), ctypes.byref(inp), None)
        _GDI_READY = (status == 0)
    except Exception:
        pass
    return _GDI_READY


def load_scaled(path: Path, max_w: int, max_h: int) -> tk.PhotoImage | None:
    if not _init():
        return None
    try:
        gdi = ctypes.windll.gdiplus

        src = ctypes.c_void_p()
        if gdi.GdipCreateBitmapFromFile(str(path), ctypes.byref(src)) != 0:
            return None
        try:
            ow, oh = ctypes.c_uint(), ctypes.c_uint()
            gdi.GdipGetImageWidth(src, ctypes.byref(ow))
            gdi.GdipGetImageHeight(src, ctypes.byref(oh))
            orig_w, orig_h = ow.value, oh.value
            if not orig_w or not orig_h:
                return None

            scale = min(max_w / orig_w, max_h / orig_h)
            tw = max(1, int(orig_w * scale))
            th = max(1, int(orig_h * scale))

            dst = ctypes.c_void_p()
            gdi.GdipCreateBitmapFromScan0(tw, th, 0, _PF_32ARGB, None, ctypes.byref(dst))
            try:
                gfx = ctypes.c_void_p()
                gdi.GdipGetImageGraphicsContext(dst, ctypes.byref(gfx))
                try:
                    gdi.GdipSetInterpolationMode(gfx, _INTERP_HQ_BICUBIC)
                    gdi.GdipDrawImageRectRectI(gfx, src, 0, 0, tw, th, 0, 0, orig_w, orig_h, _UNIT_PIXEL, None, None, None)
                finally:
                    gdi.GdipDeleteGraphics(gfx)

                rect = _Rect(0, 0, tw, th)
                bd = _BitmapData()
                if gdi.GdipBitmapLockBits(dst, ctypes.byref(rect), _LOCK_READ, _PF_32ARGB, ctypes.byref(bd)) != 0:
                    return None
                try:
                    abs_stride = abs(bd.Stride)
                    raw = (ctypes.c_uint8 * (abs_stride * th)).from_address(bd.Scan0)
                    rgb = bytearray(tw * th * 3)
                    for y in range(th):
                        row = y * abs_stride if bd.Stride >= 0 else (th - 1 - y) * abs_stride
                        for x in range(tw):
                            s = row + x * 4
                            d = (y * tw + x) * 3
                            rgb[d], rgb[d + 1], rgb[d + 2] = raw[s + 2], raw[s + 1], raw[s]
                finally:
                    gdi.GdipBitmapUnlockBits(dst, ctypes.byref(bd))

                ppm = f"P6\n{tw} {th}\n255\n".encode() + bytes(rgb)
                return tk.PhotoImage(data=base64.b64encode(ppm).decode(), format="ppm")
            finally:
                gdi.GdipDisposeImage(dst)
        finally:
            gdi.GdipDisposeImage(src)
    except Exception:
        return None


def save_as_png(src: Path, dst: Path) -> bool:
    if not _init():
        return False
    try:
        gdi = ctypes.windll.gdiplus
        bmp = ctypes.c_void_p()
        if gdi.GdipCreateBitmapFromFile(str(src), ctypes.byref(bmp)) != 0:
            return False
        try:
            return gdi.GdipSaveImageToFile(bmp, str(dst), ctypes.byref(_PNG_CLSID), None) == 0
        finally:
            gdi.GdipDisposeImage(bmp)
    except Exception:
        return False
