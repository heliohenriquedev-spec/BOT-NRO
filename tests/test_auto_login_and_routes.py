"""Automatic login (protected password, character by name) and routes saved for every map passed."""
import asyncio
import os
import struct
import time
import pytest
from nrobot import auto_login, map_routes


def char_list(*characters):
    """006B with classic 106-byte entries: id, ..., class @52, name @74, slot @104."""
    body = b''
    for identity, name, slot in characters:
        entry = bytearray(106)
        struct.pack_into('<I', entry, 0, identity)
        struct.pack_into('<H', entry, 52, 4010)
        entry[74:74+len(name)] = name.encode('cp1252')
        entry[104] = slot
        body += bytes(entry)
    return struct.pack('<HH', 0x6b, 4+len(body))+body


@pytest.mark.skipif(os.name != 'nt', reason='DPAPI is Windows only')
def test_password_is_kept_protected_and_read_back():
    token = auto_login.protect('senha secreta')
    assert 'senha' not in token and auto_login.unprotect(token) == 'senha secreta'


def test_config_is_saved_without_the_plain_password(tmp_path):
    auto_login.save(dict(auto_login.DEFAULTS, enabled=True, user='conta', password='TOKEN', character='Uadaweu2'))
    text = auto_login.FILE.read_text(encoding='utf-8')
    assert auto_login.load()['character'] == 'Uadaweu2' and 'TOKEN' in text


def test_character_is_found_by_name_in_the_server_list():
    data = char_list((150001, 'Shinobi', 0), (150002, 'Uadaweu2', 2))
    assert auto_login.character_slot(data, 'Uadaweu2') == 2
    assert auto_login.character_slot(data, 'Shinobi') == 0
    assert auto_login.character_slot(data, 'Ninguem') is None
    assert auto_login.select_packet(2) == b'\x66\x00\x02'


def test_relay_picks_the_character_from_the_list(tmp_path):
    from nrobot.session_relay import SessionRelay

    class Upstream:
        def __init__(self): self.sent = []
        def write(self, data): self.sent.append(bytes(data))
        async def drain(self): pass

    async def scenario():
        auto_login.save(dict(auto_login.DEFAULTS, enabled=True, character='Uadaweu2'))
        r = SessionRelay('127.0.0.1', folder=tmp_path)
        upstream = Upstream()
        r.schedule_character_choice(char_list((150002, 'Uadaweu2', 2)), upstream)
        await asyncio.sleep(1.7)
        assert upstream.sent == [b'\x66\x00\x02']
    asyncio.run(scenario())


def test_recording_through_several_maps_saves_a_route_to_each_one(tmp_path):
    from nrobot.session_relay import SessionRelay
    r = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True); r.upstream = object()
    monkey = map_routes.FILE
    map_routes.FILE = tmp_path/'maps.json'
    try:
        o = r.tracker.observer; o.player_id = 1; o.player = [5, 5]; o.player_at = time.monotonic(); o.map_name = 'town'
        r.quest_control('quest_map_record', {}, lambda: True)
        q = r.quests
        for source, target, cell in (('town', 'field1', [3, 3]), ('field1', 'field2', [4, 4]), ('field2', 'dungeon', [9, 9])):
            q.append(dict(kind='portal', map=source, position=[1, 1]))
            q.observe([dict(kind='map_change', map=target, position=cell)], 1, source, time.monotonic())
        o.map_name = 'dungeon'; o.player = [9, 9]
        r.quest_control('quest_map_save', dict(name=''), lambda: True)
        targets = sorted(e['target_map'] for e in map_routes.load())
        assert targets == ['dungeon', 'field1', 'field2']
        o.map_name = 'town'; o.player = [5, 5]
        r.quest_control('quest_map_record', {}, lambda: True)  # recorded again: updated, not duplicated
        q.append(dict(kind='portal', map='town', position=[1, 1]))
        q.observe([dict(kind='map_change', map='field1', position=[3, 3])], 1, 'town', time.monotonic())
        o.map_name = 'field1'; o.player = [3, 3]
        r.quest_control('quest_map_save', dict(name=''), lambda: True)
        assert sorted(e['target_map'] for e in map_routes.load()) == ['dungeon', 'field1', 'field2']  # updated, no copy
    finally:
        map_routes.FILE = monkey
