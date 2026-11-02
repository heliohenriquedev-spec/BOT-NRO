"""Captura de um pedaço da tela (o monstro sob o mouse) e gravação em PNG, sem Qt."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import struct
import zlib

import numpy as np


def write_png(path, rgba: np.ndarray):
    """Minimal RGBA PNG encoder."""
    height, width = rgba.shape[:2]
    raw = b''.join(b'\0'+rgba[row].astype(np.uint8).tobytes() for row in range(height))

    def chunk(kind, data):
        return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data) & 0xffffffff)
    png = (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(raw, 9))+chunk(b'IEND', b''))
    with open(path, 'wb') as stream:
        stream.write(png)


def cursor():
    point = wintypes.POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
        return None
    return point.x, point.y


def grab(left, top, width, height) -> np.ndarray | None:
    """RGBA pixels of a screen rectangle (physical pixels)."""
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    screen = user32.GetDC(0)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
    try:
        gdi32.SelectObject(memory, bitmap)
        if not gdi32.BitBlt(memory, 0, 0, width, height, screen, left, top, 0x00CC0020):  # SRCCOPY
            return None

        class Header(ctypes.Structure):
            _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG),
                        ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                        ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG),
                        ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)]
        header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        buffer = ctypes.create_string_buffer(width*height*4)
        if not gdi32.GetDIBits(memory, bitmap, 0, height, buffer, ctypes.byref(header), 0):
            return None
        bgra = np.frombuffer(buffer.raw, dtype=np.uint8).reshape(height, width, 4)
        rgba = bgra[..., [2, 1, 0, 3]].copy()
        rgba[..., 3] = 255
        return rgba
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(0, screen)


def capture_under_cursor(path, width=110, height=130):
    """Save the area around the mouse (a monster the player points at); True on success."""
    try:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # physical pixels, like GetCursorPos
        except OSError:
            pass
        point = cursor()
        if point is None:
            return False
        # The pointer rests on the body: keep more room above it (head) than below (feet).
        image = grab(point[0]-width//2, point[1]-int(height*.62), width, height)
        if image is None:
            return False
        write_png(path, image)
        return True
    except (OSError, AttributeError, ValueError):
        return False
