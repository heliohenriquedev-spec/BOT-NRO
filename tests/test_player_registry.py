import struct
from datetime import datetime

from nrobot.lua_tables import tables
from nrobot.packet_reader import character_look, decode
from nrobot.player_registry import PlayerRegistry, load


def test_players_are_recorded_on_sight_and_kept_between_sessions(tmp_path):
    path = tmp_path/'registro.json'
    registry = PlayerRegistry(path)
    now = datetime(2026, 11, 3, 20, 0)
    registry.observe([{'kind': 'appearance', 'entity_id': 2003137, 'species_id': 25, 'position': [10, 20], 'option': 0},
                      {'kind': 'name', 'entity_id': 2003137, 'name': 'Itachi', 'guild': 'Akatsuki'},
                      {'kind': 'appearance', 'entity_id': 110000001, 'species_id': 1002, 'position': [1, 1]},
                      {'kind': 'option_change', 'entity_id': 2003137, 'option': 0x40}], 2000001, 'konoha', now)
    registry.observe([{'kind': 'appearance', 'entity_id': 2003137, 'species_id': 25, 'position': [11, 20]}], 2000001, 'konoha', now)
    registry.save()
    entry = load(path)['2003137']
    assert set(load(path)) == {'2003137'}  # monsters are not players
    assert entry['name'] == 'Itachi' and entry['guild'] == 'Akatsuki' and entry['job'] == 25
    assert entry['sightings'] == 1 and entry['hidden_seen'] == 'gm' and entry['maps'] == ['konoha']
    registry.observe([{'kind': 'remove', 'entity_id': 2003137, 'reason': 0},
                      {'kind': 'appearance', 'entity_id': 2003137, 'species_id': 25, 'position': [11, 20]}], 2000001, 'suna', now)
    assert registry.players['2003137']['sightings'] == 2
    assert PlayerRegistry(path).players['2003137']['name'] == 'Itachi'


def test_own_class_and_hair_come_from_the_character_list():
    entry = bytearray(106)
    struct.pack_into('<I', entry, 0, 150001)
    struct.pack_into('<HH', entry, 52, 25, 7)
    entry[74:80] = b'Naruto'
    packet = struct.pack('<HH', 0x6b, 4+20+106) + bytes(20) + bytes(entry)
    assert character_look(packet, 150001) == {'job': 25, 'hair': 7, 'name': 'Naruto'}
    assert character_look(packet, 999) is None


def test_look_change_is_decoded():
    assert decode(struct.pack('<HIBHH', 0x1d7, 2000001, 1, 12, 0))['value'] == 12
    assert decode(struct.pack('<HIBB', 0xc3, 2000001, 0, 25)) == {'opcode': '00C3', 'kind': 'look_change',
                                                                   'entity_id': 2000001, 'look_type': 0, 'value': 25}


def lua50_chunk():
    """`T = {}; T[Ids.JT_NINJA] = "Ninja"` compiled by Lua 5.0 (hand-assembled)."""
    def string(text):
        raw = text.encode()+b'\0'
        return struct.pack('<I', len(raw))+raw

    def word(op, a=0, b=0, c=0, bx=None):
        return op | ((bx << 6) if bx is not None else (c << 6) | (b << 15)) | (a << 24)
    constants = ['T', 'Ids', 'JT_NINJA', 'Ninja']
    code = [word(10, 0), word(7, 0, bx=0),  # NEWTABLE 0; SETGLOBAL T
            word(5, 0, bx=0), word(5, 1, bx=1),  # GETGLOBAL T, Ids
            word(6, 1, 1, 250+2),  # GETTABLE r1 = Ids.JT_NINJA
            word(9, 0, 1, 250+3)]  # SETTABLE T[r1] = "Ninja"
    header = b'\x1bLua\x50\x01\x04\x04\x04\x06\x08\x09\x09\x08'+struct.pack('<d', 3.14159265358979323846e7)
    body = string('@t.lua')+struct.pack('<i', 0)+bytes([0, 0, 0, 2])
    body += struct.pack('<iii', 0, 0, 0)  # line info, locals, upvalues
    body += struct.pack('<i', len(constants))+b''.join(b'\x04'+string(c) for c in constants)
    body += struct.pack('<i', 0)+struct.pack('<i', len(code))+struct.pack(f'<{len(code)}I', *code)
    return header+body


def test_compiled_lua_tables_are_read_without_running_them():
    assert tables(lua50_chunk()) == {'T': {'JT_NINJA': 'Ninja'}}


def test_players_tab_is_not_rebuilt_when_nothing_visible_changed(tmp_path, monkeypatch):
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QHeaderView
    from nrobot import player_registry
    from nrobot.player_panel import PlayerPanel
    app = QApplication.instance() or QApplication([])
    panel = PlayerPanel()
    panel.players = {str(i): dict(entity_id=2000000+i, name=f'P{i}', sightings=1) for i in range(30)}
    panel.show(); panel.fill()
    assert panel.table.rowCount() == 30
    assert panel.table.horizontalHeader().sectionResizeMode(0) == QHeaderView.Interactive
    first = panel.table.item(0, 2)
    panel.fill()
    assert panel.table.item(0, 2) is first  # same rows: table left as it was
    panel.present = {2000005}; panel.fill()
    assert panel.table.item(0, 0).text() == '● sim'
    panel.close()


def idle_character(identity, *, level, sex, weapon, shield, top, guild_id):
    message = bytearray(58)
    struct.pack_into('<HIH', message, 0, 0x22a, identity, 150)
    struct.pack_into('<HH', message, 16, 4010, 12)  # class, hair
    struct.pack_into('<HHHHH', message, 20, weapon, shield, 0, top, 0)
    struct.pack_into('<I', message, 36, guild_id)
    message[49] = sex
    message[50:53] = bytes([25, 1, 0x40])  # cell (100,20)
    struct.pack_into('<H', message, 56, level)
    return bytes(message)


def name_all(identity, name, party, guild, title):
    message = bytearray(102)
    struct.pack_into('<HI', message, 0, 0x195, identity)
    for offset, text in ((6, name), (30, party), (54, guild), (78, title)):
        message[offset:offset+len(text)] = text.encode('cp1252')
    return bytes(message)


def test_level_sex_look_party_and_guild_title_are_kept(tmp_path):
    from nrobot.packet_reader import decode
    from nrobot.player_registry import PlayerRegistry
    registry = PlayerRegistry(tmp_path/'r.json')
    events = [decode(idle_character(2000555, level=812, sex=0, weapon=1224, shield=0, top=5038, guild_id=77)),
              decode(name_all(2000555, 'Sakura', 'Time 7', 'Konoha', 'Lider'))]
    registry.observe(events, 2000001, 'konoha')
    entry = registry.players['2000555']
    assert (entry['level'], entry['sex'], entry['guild_id']) == (812, 'F', 77)
    assert entry['look']['weapon'] == 1224 and entry['look']['head_top'] == 5038
    assert (entry['name'], entry['party'], entry['guild'], entry['guild_title']) == ('Sakura', 'Time 7', 'Konoha', 'Lider')


def test_public_chat_names_the_speaker_and_a_rename_is_remembered(tmp_path):
    from nrobot.player_registry import PlayerRegistry
    registry = PlayerRegistry(tmp_path/'r.json')
    registry.observe([dict(kind='actor_signal', signal='chat', entity_id=2000556, name='Naruto')], 2000001, 'konoha')
    registry.observe([dict(kind='name', entity_id=2000556, name='Naruto2')], 2000001, 'konoha')
    entry = registry.players['2000556']
    assert entry['name'] == 'Naruto2' and entry['former_names'] == ['Naruto']
