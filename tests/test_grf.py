import json
import os
import struct
import zlib

import pytest

from nrobot import catalog
from nrobot.grf import GrfSet, read_index


def write_grf(path, files):
    body = b""
    table = b""
    for name, data in files.items():
        packed = zlib.compress(data)
        table += name.encode("cp949") + b"\0" + struct.pack("<IIIBI", len(packed), len(packed), len(data), 1, len(body))
        body += packed
    packed_table = zlib.compress(table)
    header = b"Master of Magic\0" + bytes(14) + struct.pack("<IIII", len(body), 0, len(files) + 7, 0x200)
    path.write_bytes(header + body + struct.pack("<II", len(packed_table), len(table)) + packed_table)


def test_rf03_grf_priority_follows_data_ini(tmp_path):
    write_grf(tmp_path / "a.grf", {"data\\x.txt": b"novo"})
    write_grf(tmp_path / "b.grf", {"data\\x.txt": b"velho", "data\\y.txt": b"y"})
    (tmp_path / "DATA.INI").write_text("[Data]\n0=a.grf\n1=b.grf\n")
    grf = GrfSet(str(tmp_path))
    assert grf.read("DATA\\X.TXT") == b"novo" and grf.read("data\\y.txt") == b"y"


GAME = catalog.DEFAULT_GAME_DIR


@pytest.mark.skipif(not os.path.isfile(os.path.join(GAME, "DATA.INI")), reason="jogo não instalado")
def test_rf03_real_game_files_unchanged_and_readable():
    grf_path = os.path.join(GAME, "NRO5.grf")
    stamp = os.stat(grf_path).st_mtime_ns
    assert len(read_index(grf_path)) > 100
    assert os.stat(grf_path).st_mtime_ns == stamp


@pytest.mark.skipif(catalog.load() is None, reason="catálogo não gerado")
def test_rf03_built_catalog_has_real_data():
    data = catalog.load()
    assert len(data["monstros"]) > 500 and len(data["habilidades"]) > 500
    assert "abbey01" in data["por_mapa"]
