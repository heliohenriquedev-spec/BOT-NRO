"""Leitor somente-leitura de arquivos GRF 0x200 (RF-03)."""
from __future__ import annotations

import configparser
import os
import struct
import zlib
from dataclasses import dataclass

HEADER_SIZE = 46
MAGIC = b"Master of Magic"
FLAG_FILE = 1
FLAG_ENCRYPTED = 6


class GrfError(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    path: str
    name: str
    compressed: int
    aligned: int
    size: int
    flags: int
    offset: int


def read_index(path: str) -> dict[str, Entry]:
    """Devolve as entradas do GRF, indexadas pelo nome em minúsculas."""
    with open(path, "rb") as f:
        header = f.read(HEADER_SIZE)
        if not header.startswith(MAGIC):
            raise GrfError(f"{path}: não é um GRF")
        table_offset, _seed, _count, version = struct.unpack("<IIII", header[30:46])
        if version != 0x200:
            raise GrfError(f"{path}: versão {version:#x} não suportada")
        f.seek(HEADER_SIZE + table_offset)
        compressed, _size = struct.unpack("<II", f.read(8))
        table = zlib.decompress(f.read(compressed))

    entries: dict[str, Entry] = {}
    pos = 0
    while pos < len(table):
        end = table.index(b"\0", pos)
        name = table[pos:end].decode("cp949", "replace")
        pos = end + 1
        comp, aligned, size, flags, offset = struct.unpack("<IIIBI", table[pos:pos + 17])
        pos += 17
        if flags & FLAG_FILE:
            entries[name.lower()] = Entry(path, name, comp, aligned, size, flags, offset)
    return entries


class GrfSet:
    """GRFs do jogo, respeitando a prioridade definida em DATA.INI."""

    def __init__(self, game_dir: str):
        ini = os.path.join(game_dir, "DATA.INI")
        if not os.path.isfile(ini):
            raise GrfError(f"DATA.INI não encontrado em {game_dir}")
        parser = configparser.ConfigParser()
        parser.read(ini, encoding="latin-1")
        data = parser["Data"]
        names = [data[k] for k in sorted(data, key=int)]
        self.entries: dict[str, Entry] = {}
        for name in names:
            grf = os.path.join(game_dir, name)
            if not os.path.isfile(grf):
                continue
            for key, entry in read_index(grf).items():
                self.entries.setdefault(key, entry)

    def __contains__(self, name: str) -> bool:
        return name.lower() in self.entries

    def read(self, name: str) -> bytes:
        entry = self.entries[name.lower()]
        with open(entry.path, "rb") as f:
            f.seek(HEADER_SIZE + entry.offset)
            raw = f.read(entry.aligned)
        if entry.flags & 2:
            from .grf_header import decode_mixed
            raw = decode_mixed(raw, entry.compressed)
        elif entry.flags & 4:
            from .grf_header import decode_header
            raw = decode_header(raw)
        try:
            return zlib.decompress(raw)[:entry.size]
        except zlib.error as error:
            if entry.compressed == entry.size:
                return raw[:entry.size]
            raise GrfError(f"{name}: dados inválidos em {os.path.basename(entry.path)}") from error

    def find(self, prefix: str, suffix: str = "") -> list[str]:
        prefix, suffix = prefix.lower(), suffix.lower()
        return [k for k in self.entries if k.startswith(prefix) and k.endswith(suffix)]
