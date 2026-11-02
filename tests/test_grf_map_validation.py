import struct
import zlib
import pytest

from nrobot.grf_header import decode_header
from nrobot.grf import GrfSet
from nrobot.map_navigation import CollisionMap, MapRepository
from nrobot.packet_settings import DEFAULTS
from nrobot.session_relay import SessionRelay
from nrobot.packet_hunt import PacketHunt


def test_standard_grf_header_format_reads_gat_without_changing_archive(tmp_path):
    gat = b'GRAT\x01\x02'+struct.pack('<II', 4, 4)+struct.pack('<4fI', 0, 0, 0, 0, 0)*16
    packed = zlib.compress(gat)
    aligned = packed+bytes((-len(packed))%8)
    coded = decode_header(aligned)
    assert decode_header(coded) == aligned
    entry = b'data\\test.gat\0'+struct.pack('<IIIBI', len(packed), len(coded), len(gat), 5, 0)
    table = zlib.compress(entry)
    header = b'Master of Magic\0'+bytes(14)+struct.pack('<IIII', len(coded), 0, 8, 0x200)
    path = tmp_path/'test.grf'
    original = header+coded+struct.pack('<II', len(table), len(entry))+table
    path.write_bytes(original)
    (tmp_path/'DATA.INI').write_text('[Data]\n0=test.grf\n')
    assert GrfSet(str(tmp_path)).read('data\\test.gat') == gat
    assert path.read_bytes() == original


def test_reachable_components_and_strict_start_reject_invalid_position(tmp_path):
    cells = [1]*64
    for y in range(8): cells[y*8+4] = 0
    collision = CollisionMap(8, 8, cells)
    reachable = collision.reachable([1, 1])
    assert (3, 3) in reachable and (5, 3) not in reachable
    assert not collision.line_clear([2, 2], [6, 2])
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.hunt = PacketHunt()
    relay.apply_settings(DEFAULTS)
    relay.collision_map = lambda: collision
    relay.tracker.observer.player = [4, 2]
    with pytest.raises(ValueError, match='célula livre'):
        relay.validate_navigation_start()
    relay.tracker.observer.player = [1, 1]
    relay.validate_navigation_start()
    assert relay.map_validation['reachable_cells'] == len(reachable)


def test_standard_mixed_grf_decodes_des_and_shuffled_blocks(tmp_path):
    import random
    from nrobot.grf_header import decode_block, decode_header
    original=random.Random(42).randbytes(5000)
    packed=zlib.compress(original)
    coded=bytearray(packed+bytes((-len(packed))%8))
    digits=len(str(len(packed)))
    cycle=1 if digits<3 else digits+1 if digits<5 else digits+9 if digits<7 else digits+15
    substitutions={0:43,43:0,108:128,128:108,1:104,104:1,72:119,119:72,96:255,255:96,185:192,192:185,254:235,235:254}
    plain_index=-1
    for block in range(len(coded)//8):
        offset=block*8
        raw=coded[offset:offset+8]
        if block<20 or block%cycle==0:
            coded[offset:offset+8]=decode_block(raw)
        else:
            plain_index+=1
            if plain_index and plain_index%7==0:
                coded[offset:offset+8]=bytes([raw[3],raw[4],raw[5],raw[0],raw[1],raw[6],raw[2],substitutions.get(raw[7],raw[7])])
    entry=b'data\\test.bin\0'+struct.pack('<IIIBI',len(packed),len(coded),len(original),3,0)
    table=zlib.compress(entry)
    header=b'Master of Magic\0'+bytes(14)+struct.pack('<IIII',len(coded),0,8,0x200)
    archive=header+coded+struct.pack('<II',len(table),len(entry))+table
    path=tmp_path/'mixed.grf';path.write_bytes(archive)
    (tmp_path/'DATA.INI').write_text('[Data]\n0=mixed.grf\n')
    assert GrfSet(str(tmp_path)).read('data\\test.bin')==original
    assert path.read_bytes()==archive
