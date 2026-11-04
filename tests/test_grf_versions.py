"""GRF 0x200 and 0x300 are read; one unreadable GRF no longer hides all the others."""
import struct
import zlib

from nrobot.grf import GrfSet, read_index


def make_grf(path, files, version=0x200, skip=4):
    body, table = b'', b''
    for name, content in files.items():
        packed = zlib.compress(content)
        offset = len(body)
        body += packed
        table += name.encode('cp949')+b'\0'+struct.pack('<IIIB', len(packed), len(packed), len(content), 1)
        table += struct.pack('<Q' if version == 0x300 else '<I', offset)
    packed_table = zlib.compress(table)
    if version == 0x300:
        header = b'Master of Magic\0'+bytes(14)+struct.pack('<QII', len(body), len(files), 0x300)
        tail = bytes(skip)+struct.pack('<II', len(packed_table), len(table))+packed_table
    else:
        header = b'Master of Magic\0'+bytes(14)+struct.pack('<IIII', len(body), 0, len(files)+7, 0x200)
        tail = struct.pack('<II', len(packed_table), len(table))+packed_table
    path.write_bytes(header+body+tail)


def test_both_versions_are_read(tmp_path):
    make_grf(tmp_path/'a.grf', {'data\mapa.gat': b'GAT'})
    make_grf(tmp_path/'b.grf', {'data\outro.gat': b'NOVO'}, version=0x300)
    make_grf(tmp_path/'c.grf', {'data\c.gat': b'C'}, version=0x300, skip=0)
    assert set(read_index(str(tmp_path/'b.grf'))) == {'data\outro.gat'}
    (tmp_path/'DATA.INI').write_text('[Data]\n0=b.grf\n1=c.grf\n2=a.grf\n', encoding='latin-1')
    grfs = GrfSet(str(tmp_path))
    assert grfs.read('data\outro.gat') == b'NOVO' and grfs.read('data\c.gat') == b'C' and grfs.read('data\mapa.gat') == b'GAT'


def test_an_unreadable_grf_is_skipped_and_the_others_still_load(tmp_path):
    make_grf(tmp_path/'bom.grf', {'data\mapa.gat': b'GAT'})
    (tmp_path/'quebrado.grf').write_bytes(b'Master of Magic\0'+bytes(14)+struct.pack('<IIII', 999, 0, 0, 0x103))
    (tmp_path/'DATA.INI').write_text('[Data]\n0=quebrado.grf\n1=bom.grf\n', encoding='latin-1')
    grfs = GrfSet(str(tmp_path))
    assert grfs.read('data\mapa.gat') == b'GAT'
    assert grfs.skipped and grfs.skipped[0].startswith('quebrado.grf')


def test_data_ini_written_by_hand_is_read_like_the_game_does(tmp_path):
    from nrobot.grf import data_ini_grfs
    ini = tmp_path/'DATA.INI'
    ini.write_bytes('﻿[data]\r\n//0=antigo.grf\r\n; comentario\r\n0=NRO - Mapas limpos sem dano.grf\r\n'
                    '1=NRO.grf // principal\r\n1=NRO5.grf\r\nlixo sem igual\r\n2=data.grf\r\n[Outra]\r\n3=nao.grf\r\n'.encode('utf-8'))
    assert data_ini_grfs(str(ini)) == ['NRO - Mapas limpos sem dano.grf', 'NRO5.grf', 'data.grf']


def test_a_commented_grf_line_no_longer_hides_every_map(tmp_path):
    make_grf(tmp_path/'bom.grf', {'data\mapa.gat': b'GAT'})
    (tmp_path/'DATA.INI').write_text('[Data]\n//0=velho.grf\n0=bom.grf\n', encoding='latin-1')
    assert GrfSet(str(tmp_path)).read('data\mapa.gat') == b'GAT'
