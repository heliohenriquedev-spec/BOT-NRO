"""REDE-05/06: duplicatas, lacunas e mensagens reais mínimas da captura."""
import struct

import pytest

from nrobot.packet_reader import Segment, decode, message_length, read_pcapng, reassemble


def segment(seq, data, time=1):
    return Segment(time, ('10.0.0.1', 5121), ('10.0.0.2', 50000), seq, data)


def test_reassemble_reorder_duplicate_and_gap():
    runs, quality = reassemble([segment(100, b'abc'), segment(103, b'def'),
                               segment(100, b'abc'), segment(110, b'ijk')])
    assert [r[0] for r in runs] == [b'abcdef', b'ijk']
    assert quality == {'segments': 4, 'duplicate_segments': 1, 'gaps': 1, 'missing_bytes': 4}
    runs, _ = reassemble([segment(103, b'def'), segment(100, b'abc')])
    assert runs[0][0] == b'abcdef'


def test_partial_overlap_and_conflict():
    assert reassemble([segment(1, b'abcd'), segment(3, b'cdef')])[0][0][0] == b'abcdef'
    with pytest.raises(ValueError, match='conflitantes'):
        reassemble([segment(1, b'abcd'), segment(3, b'XXef')])


def test_actor_identity_and_coordinates_from_capture():
    message = bytes.fromhex('78 00 00 55 8a 98 06 c8 00 00 00 00 00 00 00 0d 04 '
                            '00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 '
                            '00 00 00 00 00 00 00 00 00 00 00 11 41 84 00 00 00 0f 00')
    e = decode(message)
    assert e['entity_id'] == 110660181
    assert e['species_id'] == 1037
    assert e['position'] == [69, 24]
    with pytest.raises(ValueError):
        decode(message[:-1])


def test_name_and_hp_without_hover_or_external_lookup():
    message = bytearray(102)
    struct.pack_into('<HI', message, 0, 0x195, 123)
    message[6:12] = b'Akino\0'
    message[30:48] = b'HP: 50/50 | HP: 10'
    e = decode(bytes(message))
    assert (e['entity_id'], e['name'], e['hp'], e['max_hp']) == (123, 'Akino', 50, 50)


def test_variable_length_and_unknown_opcode():
    assert message_length(bytes.fromhex('7f013400')) == 52
    assert message_length(b'\x7f\x01') is None
    with pytest.raises(ValueError):
        message_length(b'\xff\xff')


def test_npc_chat_title_does_not_desynchronize_following_messages():
    from nrobot.network_observer import LiveStream
    room = bytes.fromhex('d7001c003247970619861c0000000000035b496e73747275746f725d')
    removed = bytes.fromhex('8000288b980601')
    stream = LiveStream()
    assert message_length(room) == 28
    events = stream.feed(100, room+removed, 0)
    assert [e['kind'] for e in events] == ['other', 'remove']
    assert events[1]['entity_id'] == 110660392
    assert not stream.buffer
    with pytest.raises(ValueError, match='variável'):
        message_length(bytes.fromhex('d7000400'))


def test_system_broadcast_split_across_tcp_segments_keeps_following_actor():
    from nrobot.network_observer import LiveStream
    text = b'Server announcement\0'
    notice = struct.pack('<HH', 0x9a, 4+len(text)) + text
    removed = bytes.fromhex('8000288b980601')
    stream = LiveStream()
    assert stream.feed(100, notice[:7], 0) == []
    events = stream.feed(107, notice[7:]+removed, 0.1)
    assert [e['kind'] for e in events] == ['other', 'remove']
    assert events[1]['entity_id'] == 110660392
    assert not stream.buffer


def test_actual_skill_cast_packet_keeps_following_status_aligned():
    from nrobot.network_observer import LiveStream
    payload = bytes.fromhex('8800c1901e006d0091003e01c1901e00c1901e00000000001d000000000073030000b0000000e2000000')
    stream = LiveStream()
    events = stream.feed(100, payload, 0)
    assert [e['opcode'] for e in events] == ['0088', '013E', '00B0']
    assert events[0]['position'] == [109, 145]
    assert events[1]['kind'] == 'skill_cast'
    assert events[1]['duration_ms'] == 883
    assert not stream.buffer


def test_actual_status_effect_keeps_following_skill_aligned():
    from nrobot.network_observer import LiveStream
    payload = bytes.fromhex('b000000070000000b00007009e030000b0000500830b000096010c00c1901e00011a011d000500c1901e00c1901e0001')
    stream = LiveStream()
    assert stream.feed(100, payload[:29], 0) == [decode(payload[i:i+8]) for i in (0, 8, 16)]
    events = stream.feed(129, payload[29:], 0.1)
    assert [e['opcode'] for e in events] == ['0196', '011A']
    assert events[0]['kind'] == 'status_effect'
    assert events[0]['effect_id'] == 12
    assert events[0]['active'] is True
    assert not stream.buffer


def test_ground_effect_burst_is_not_monster_and_does_not_remove_monster():
    from nrobot.network_observer import LiveStream, Observer
    from nrobot.network_targets import Entity
    first = bytes.fromhex('1f011dc61400c1901e0052008a008601')
    removed = struct.pack('<HI', 0x120, 0x14c61d)
    stream = LiveStream()
    events = stream.feed(100, first*49+removed, 0)
    assert len(events) == 50
    assert events[0]['kind'] == 'ground_effect'
    assert events[0]['position'] == [82, 138]
    assert events[-1]['kind'] == 'ground_effect_removed'
    assert not stream.buffer
    observer = Observer({1051})
    observer.registry.update(Entity(0x14c61d, 1051, 1, 1, 0, 'monster'))
    for event in events:
        observer.apply(event, 0)
    assert 0x14c61d in observer.registry.entities


def test_actual_extended_skill_damage_fragment_preserves_next_message():
    from nrobot.network_observer import LiveStream
    skill = bytes.fromhex('de010402e5d81400e38b9806c2da962e2102000000000000357301000500010004')
    removed = bytes.fromhex('8000288b980601')
    stream = LiveStream()
    assert message_length(skill) == 33
    assert stream.feed(100, skill[:20], 0) == []
    events = stream.feed(120, skill[20:]+removed, 0.1)
    assert [e['opcode'] for e in events] == ['01DE', '0080']
    assert events[1]['entity_id'] == 110660392
    assert not stream.buffer


def test_actual_item_consumption_does_not_interrupt_attribute_update():
    from nrobot.network_observer import LiveStream
    payload = bytes.fromhex('b0000700c50300008800c1901e0081007c00de010c02c1901e00b18a98067300982e2102000000030000747000000a000d0008af000c000100b00018005b2c0000')
    stream = LiveStream()
    events = stream.feed(100, payload, 0)
    assert [e['opcode'] for e in events] == ['00B0', '0088', '01DE', '00AF', '00B0']
    assert events[3]['kind'] == 'inventory_removed'
    assert events[3]['inventory_index'] == 12
    assert events[3]['amount'] == 1
    assert 'entity_id' not in events[3]
    assert not stream.buffer


def test_map_entry_identity_stats_inventory_and_target_in_one_stream():
    from nrobot.network_observer import LiveStream, Observer
    account = struct.pack('<HI', 0x283, 2003137)
    auth = struct.pack('<HI', 0x73, 0) + bytes([2, 128, 160, 0, 0])
    stats = struct.pack('<H', 0xbd) + bytes(42)
    skills = struct.pack('<HH', 0x10f, 4)
    monster = bytearray(55)
    struct.pack_into('<HBI', monster, 0, 0x78, 0, 777)
    struct.pack_into('<H', monster, 15, 1051)
    monster[47:50] = bytes([3, 0, 160])
    stream, observer = LiveStream(), Observer({1051})
    raw = account+auth+stats+skills+monster
    events = stream.feed(100, raw[:19], 0) + stream.feed(119, raw[19:], 0.1)
    for event in events:
        observer.apply(event, .1)
    assert observer.player_id == 2003137
    assert observer.player == [10, 10]
    assert observer.choose(.1).entity_id == 777
    observer.apply(decode(struct.pack('<HIHH', 0x88, 2003137, 11, 12)), .2)
    assert observer.player == [11, 12]
    assert observer.registry.entities[777].x == 12
    assert not stream.buffer


def test_pcapng_truncation(tmp_path):
    path = tmp_path / 'bad.pcapng'
    path.write_bytes(b'\x0a\x0d\x0d\x0a')
    with pytest.raises(ValueError, match='truncado'):
        read_pcapng(path)


def test_pcapng_packet_timestamp_and_ethernet_padding(tmp_path):
    def block(kind, body):
        size = len(body)+12
        return struct.pack('<II', kind, size) + body + struct.pack('<I', size)
    payload = bytes.fromhex('8000288b980601')
    tcp = struct.pack('!HHII', 5121, 50000, 100, 0) + bytes.fromhex('5018000000000000') + payload
    ip = bytearray(20)
    ip[0], ip[9] = 0x45, 6
    struct.pack_into('!H', ip, 2, 20+len(tcp))
    ip[12:16], ip[16:20] = bytes([10, 0, 0, 1]), bytes([10, 0, 0, 2])
    frame = bytes(12) + b'\x08\x00' + ip + tcp
    section = block(0x0a0d0d0a, struct.pack('<IHHq', 0x1a2b3c4d, 1, 0, -1))
    interface = block(1, struct.pack('<HHI', 1, 0, 65535))
    epb = block(6, struct.pack('<IIIII', 0, 0, 1250000, len(frame), len(frame))
                + frame + bytes(-len(frame) % 4))
    path = tmp_path/'sample.pcapng'
    path.write_bytes(section+interface+epb)
    segments = read_pcapng(path)
    assert len(segments) == 1
    assert segments[0].time == 1.25
    assert segments[0].payload == payload
    assert segments[0].sequence == 100


def test_disconnect_notification_is_retained_as_numeric_reason():
    from nrobot.packet_reader import decode
    assert decode(b'\x81\x00\x08')=={'opcode':'0081','kind':'server_disconnect','reason_raw':8}
