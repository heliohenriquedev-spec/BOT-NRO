"""Leitor somente-leitura de arquivos GRF 0x200 e 0x300 (RF-03)."""
from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

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
    """Devolve as entradas do GRF, indexadas pelo nome em minúsculas.

    0x200: tabela em offset de 32 bits e entradas com offset de 32 bits.
    0x300 (GRF Editor, arquivos grandes): offset da tabela em 64 bits (sem semente) e
    entradas com offset de 64 bits; a tabela pode vir precedida de 4 bytes. As duas formas
    são conferidas (descompressão e offsets dentro do arquivo) antes de aceitar."""
    size_on_disk = os.path.getsize(path)
    with open(path, "rb") as f:
        header = f.read(HEADER_SIZE)
        if not header.startswith(MAGIC):
            raise GrfError(f"{path}: não é um GRF")
        version = struct.unpack_from("<I", header, 42)[0]
        if version == 0x200:
            table_offset = struct.unpack_from("<I", header, 30)[0]
            layouts = [(0, 4)]
        elif version == 0x300:
            table_offset = struct.unpack_from("<Q", header, 30)[0]
            layouts = [(4, 8), (0, 8)]
        else:
            raise GrfError(f"{path}: versão {version:#x} não suportada")
        for skip, offset_size in layouts:
            try:
                f.seek(HEADER_SIZE + table_offset + skip)
                compressed, _size = struct.unpack("<II", f.read(8))
                table = zlib.decompress(f.read(compressed))
                return _entries(path, table, offset_size, size_on_disk)
            except (struct.error, zlib.error, ValueError, OverflowError):
                continue
    raise GrfError(f"{path}: tabela de arquivos ilegível (versão {version:#x})")


def _entries(path, table, offset_size, size_on_disk):
    entries: dict[str, Entry] = {}
    pos = 0
    record = 13+offset_size
    while pos < len(table):
        end = table.index(b"\0", pos)
        name = table[pos:end].decode("cp949", "replace")
        pos = end + 1
        comp, aligned, size, flags = struct.unpack("<IIIB", table[pos:pos + 13])
        offset = struct.unpack("<Q" if offset_size == 8 else "<I", table[pos+13:pos+record])[0]
        pos += record
        if flags & FLAG_FILE:
            if HEADER_SIZE+offset+aligned > size_on_disk:
                raise ValueError("entrada fora do arquivo")
            entries[name.lower()] = Entry(path, name, comp, aligned, size, flags, offset)
    return entries


WARNED: set[str] = set()


def data_ini_grfs(path: str) -> list[str]:
    """GRFs of DATA.INI in priority order, read the tolerant way the game does.

    Only "number=file" lines of [Data] count: commented lines ("//0=x.grf", ";", "#"), a BOM,
    "[data]" in lower case, repeated numbers (the last one wins) or stray text are ignored,
    where a strict INI reader gave up and no map loaded."""
    with open(path, "rb") as f:
        raw = f.read()
        if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
            text = raw.decode('utf-16')
        else:
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = raw.decode('cp1252')
        text = text.lstrip('\ufeffï»¿')
    section, found, has_sections = None, {}, False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("//", ";", "#")):
            continue
        if line.startswith("[") and "]" in line:
            section = line[1:line.index("]")].strip().lower()
            has_sections = True
            continue
        if has_sections and section != "data":
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.split("//")[0].strip().strip('"')
        if sep and key.isdigit() and value:
            found[int(key)] = value
    return [found[k] for k in sorted(found)]


class GrfSet:
    """GRFs do jogo, respeitando a prioridade definida em DATA.INI."""

    def __init__(self, game_dir: str):
        ini = os.path.join(game_dir, "DATA.INI")
        if not os.path.isfile(ini):
            raise GrfError(f"DATA.INI não encontrado em {game_dir}")
        names = data_ini_grfs(ini)
        if not names:
            raise GrfError(f"DATA.INI sem nenhum GRF na seção [Data] ({ini})")
        self.entries: dict[str, Entry] = {}
        self.alternates: dict[str, list[Entry]] = {}
        self.skipped: list[str] = []
        for name in names:
            grf = os.path.join(game_dir, name)
            if not os.path.isfile(grf):
                self.skipped.append(f'{name}: arquivo nao encontrado na pasta do jogo')
                continue
            try:
                index = read_index(grf)
            except (GrfError, OSError, ValueError) as exc:
                # One unreadable GRF (other format, damaged, locked) must not hide every other one:
                # without them no map collision loads and the hunt cannot move at all.
                self.skipped.append(f"{name}: {exc}")
                if name not in WARNED:
                    WARNED.add(name)
                    print(f"GRF ignorado (os outros continuam valendo): {name} - {exc}")
                continue
            for key, entry in index.items():
                if key in self.entries:
                    self.alternates.setdefault(key, []).append(entry)
                else:
                    self.entries[key] = entry

    def __contains__(self, name: str) -> bool:
        return name.lower() in self.entries

    def read(self, name: str) -> bytes:
        return self.read_entry(self.entries[name.lower()])

    @staticmethod
    def read_entry(entry: Entry) -> bytes:
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
            resource = PureWindowsPath(entry.name)
            if (not resource.anchor and '..' not in resource.parts
                    and resource.parts and resource.parts[0].lower() == 'data'):
                suffix = resource.suffix.lower()
                category = ('mapas' if suffix in ('.gat', '.gnd', '.rsw') else
                            'monstros' if suffix in ('.spr', '.act') else 'outros')
                base = Path(__file__).resolve().parents[1]/'Arquivos_grf'
                recovered = base/Path(entry.path).name/category/Path(*resource.parts)
                if recovered.is_file():
                    data = recovered.read_bytes()
                    if len(data) == entry.size:
                        return data
            if entry.compressed == entry.size:
                return raw[:entry.size]
            raise GrfError(f"{entry.name}: dados inválidos em {os.path.basename(entry.path)}") from error

    def find(self, prefix: str, suffix: str = "") -> list[str]:
        prefix, suffix = prefix.lower(), suffix.lower()
        return [k for k in self.entries if k.startswith(prefix) and k.endswith(suffix)]
