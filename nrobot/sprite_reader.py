"""Leitura de sprites .spr do cliente (primeiro quadro, que é o monstro parado)."""
from __future__ import annotations

import struct

import numpy as np

MONSTER_DIR = 'data\\sprite\\'+chr(0xBAAC)+chr(0xC2A4)+chr(0xD130)+'\\'  # pasta "monstro" em coreano


def decode_first_frame(data: bytes) -> np.ndarray | None:
    """RGBA image (h, w, 4) of the first frame of an SPR file, or None."""
    if len(data) < 8 or data[:2] != b'SP':
        return None
    minor, major = data[2], data[3]
    version = major*10+minor
    indexed = struct.unpack_from('<H', data, 4)[0]
    offset = 8 if version >= 20 else 6
    rgba_count = struct.unpack_from('<H', data, 6)[0] if version >= 20 else 0
    if indexed:
        palette = np.frombuffer(data[-1024:], dtype=np.uint8).reshape(256, 4).copy()
        palette[:, 3] = 255
        palette[0, 3] = 0  # index 0 is the transparent background
        width, height = struct.unpack_from('<HH', data, offset)
        offset += 4
        if not width or not height:
            return None
        if version >= 21:  # run-length encoded zeros
            size = struct.unpack_from('<H', data, offset)[0]
            offset += 2
            packed, pixels, i = data[offset:offset+size], bytearray(), 0
            while i < len(packed) and len(pixels) < width*height:
                value = packed[i]
                if value == 0 and i+1 < len(packed):
                    pixels += bytes(max(packed[i+1], 1))
                    i += 2
                else:
                    pixels.append(value)
                    i += 1
            pixels = bytes(pixels[:width*height]).ljust(width*height, b'\0')
        else:
            pixels = data[offset:offset+width*height]
        if len(pixels) < width*height:
            return None
        index = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width)
        return palette[index]
    if rgba_count:
        width, height = struct.unpack_from('<HH', data, offset)
        raw = np.frombuffer(data[offset+4:offset+4+width*height*4], dtype=np.uint8)
        if raw.size < width*height*4:
            return None
        abgr = raw.reshape(height, width, 4)[::-1]
        return abgr[..., ::-1].copy()  # ABGR -> RGBA
    return None


def crop(rgba: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(rgba[..., 3])
    if not len(ys):
        return rgba
    return rgba[ys.min():ys.max()+1, xs.min():xs.max()+1]
