import struct

from nrobot import titan_settings
from nrobot.rcx_client import MODE_MANAGER
from nrobot.titan import Titan, decode_destination, decode_position, encode_movement, encode_position
from nrobot.titan_zoom import ZoomWriter, desired_scales

OWN = 2_000_123
MONSTER = 110_660_192
PLAYER = 2_500_000


def spawn_78(identity, species, x, y, object_type=5):
    packet = bytearray(55)
    struct.pack_into('<HBI', packet, 0, 0x78, object_type, identity)
    struct.pack_into('<H', packet, 15, species)
    packet[47:50] = encode_position(x, y, 3)
    return bytes(packet)


def spawn_22a(identity, x, y):
    packet = bytearray(58)
    struct.pack_into('<HI', packet, 0, 0x22a, identity)
    struct.pack_into('<H', packet, 16, 1)
    packet[50:53] = encode_position(x, y, 0)
    return bytes(packet)


def move_86(identity, sx, sy, dx, dy):
    return struct.pack('<HI', 0x86, identity)+encode_movement(sx, sy, dx, dy)+b'\0'*4


def name_95(identity, name):
    return struct.pack('<HI', 0x95, identity)+name.encode('cp1252').ljust(24, b'\0')


def config(**kw):
    kw.setdefault('hide_groups', [])
    return titan_settings.validate(kw)


def hide(what, active=True, except_ids=(), mode='except', names=()):
    return dict(what=what, key='F9', active=active, except_ids=list(except_ids), mode=mode, except_names=list(names))


def make(cfg, summons=()):
    box = {'cfg': cfg}
    titan = Titan(None, lambda: box['cfg'], lambda: set(summons))
    titan.player_id = OWN
    titan.feed(struct.pack('<HI3sBB', 0x73, 0, b'\0\0\0', 5, 5))  # map loaded
    return titan, box


def ops(data):
    from nrobot.packet_reader import message_length
    result, offset = [], 0
    while offset < len(data):
        size = message_length(data, offset)
        result.append((struct.unpack_from('<H', data, offset)[0], bytes(data[offset:offset+size])))
        offset += size
    return result


def ids(data, op=0x78, at=3):
    return [struct.unpack_from('<I', p, at)[0] for o, p in ops(data) if o == op]


def test_position_encoding_round_trip():
    assert decode_position(encode_position(301, 157, 6)) == (301, 157, 6)
    assert decode_destination(encode_movement(10, 20, 301, 157)) == (301, 157)


def test_size_is_not_sent_as_packets():
    titan, _ = make(config(rules=[dict(kind='species', value='1051', scale=2.0)]))
    assert [op for op, _ in ops(titan.feed(spawn_78(MONSTER, 1051, 50, 60)))] == [0x78]


def test_colour_by_name_picks_only_the_right_bikouchuu():
    titan, _ = make(config(rules=[dict(kind='name', value='Bikouchuu Dourado', color='red')]))
    other, right = MONSTER, MONSTER+1
    titan.feed(spawn_78(other, 1051, 10, 10)+spawn_78(right, 1051, 12, 12))
    assert [op for op, _ in ops(titan.feed(name_95(other, 'Bikouchuu')))] == [0x95]
    out = ops(titan.feed(name_95(right, 'Bikouchuu dourado')))
    assert [op for op, _ in out] == [0x95, 0x229, 0x28a]
    assert struct.unpack_from('<I', out[2][1], 14)[0] & 0x80


def test_colour_kept_on_server_updates_and_removed_when_rule_goes():
    titan, box = make(config(rules=[dict(kind='species', value='1051', color='red')]))
    titan.feed(spawn_78(MONSTER, 1051, 50, 60))
    (op, packet), = ops(titan.feed(struct.pack('<HIIII', 0x28a, MONSTER, 0, 0, 0)))
    assert struct.unpack_from('<I', packet, 14)[0] == 0x80
    box['cfg'] = config(rules=[])
    out = ops(titan.tick())
    assert [p for o, p in out if o == 0x28a] and struct.unpack_from('<I', [p for o, p in out if o == 0x28a][0], 14)[0] == 0


def test_disabled_rule_by_key_does_not_colour():
    titan, _ = make(config(rules=[dict(kind='entity', value=str(MONSTER), color='red', key='1', enabled=False)]))
    assert [op for op, _ in ops(titan.feed(spawn_78(MONSTER, 1051, 50, 60)))] == [0x78]


def test_blue_uses_frozen_body_state():
    titan, _ = make(config(rules=[dict(kind='species', value='1051', color='blue')]))
    state = [p for op, p in ops(titan.feed(spawn_78(MONSTER, 1051, 50, 60))) if op == 0x229][0]
    assert struct.unpack_from('<h', state, 6)[0] == 2


def test_hide_players_toggle_and_restore_at_latest_cell():
    titan, box = make(config(hide_groups=[hide('players', active=False)]))
    titan.feed(spawn_22a(PLAYER, 30, 30)+spawn_78(MONSTER, 1051, 10, 10))
    box['cfg'] = config(hide_groups=[hide('players')])
    out = ops(titan.tick())
    assert [(op, struct.unpack_from('<I', p, 2)[0]) for op, p in out] == [(0x80, PLAYER)]
    assert titan.feed(move_86(PLAYER, 30, 30, 31, 31)) == b''  # withheld while hidden
    box['cfg'] = config(hide_groups=[hide('players', active=False)])
    out = ops(titan.tick())
    assert out[0][0] == 0x22a and decode_position(out[0][1][50:53])[:2] == (31, 31)


def test_selected_id_stays_visible_while_everyone_else_hides():
    friend = PLAYER+7
    titan, _ = make(config(hide_groups=[hide('all', except_ids=[friend])]))
    out = titan.feed(spawn_22a(PLAYER, 1, 1)+spawn_22a(friend, 2, 2)+spawn_78(MONSTER, 1051, 3, 3))
    assert ids(out, 0x22a, 2) == [friend] and ids(out) == []


def test_two_shortcuts_with_different_exceptions():
    a, b = PLAYER+1, PLAYER+2
    titan, box = make(config(hide_groups=[hide('players', False, [a]), hide('players', False, [b])]))
    titan.feed(spawn_22a(a, 1, 1)+spawn_22a(b, 2, 2))
    box['cfg'] = config(hide_groups=[hide('players', True, [a]), hide('players', False, [b])])
    assert [struct.unpack_from('<I', p, 2)[0] for op, p in ops(titan.tick()) if op == 0x80] == [b]


def test_summons_only_leaves_monsters_visible():
    summon = MONSTER+5
    titan, _ = make(config(hide_groups=[hide('summons')]), summons=[summon])
    assert ids(titan.feed(spawn_78(MONSTER, 1051, 10, 10)+spawn_78(summon, 1500, 11, 11))) == [MONSTER]


def test_summon_species_and_pet_type_count_as_summons():
    titan, _ = make(config(summon_species=[1999], hide_groups=[hide('summons')]))
    out = titan.feed(spawn_78(MONSTER, 1999, 10, 10)+spawn_78(MONSTER+1, 1002, 10, 10, object_type=7)
                     + spawn_78(MONSTER+2, 1002, 10, 10))
    assert ids(out) == [MONSTER+2]


def test_own_character_is_never_hidden():
    titan, _ = make(config(hide_groups=[hide('all')]))
    assert ops(titan.feed(spawn_22a(OWN, 5, 5)))[0][0] == 0x22a


def test_disabled_titan_changes_nothing():
    titan, _ = make(config(enabled=False, rules=[dict(kind='species', value='1051', color='red')],
                           hide_groups=[hide('monsters')]))
    data = spawn_78(MONSTER, 1051, 50, 60)
    assert titan.feed(data) == data


def test_settings_migrate_old_sizes_and_drop_free_groups():
    cfg = titan_settings.validate(dict(
        rules=[dict(kind='species', value='abc', size=2), dict(kind='name', value='x', size=2, color='rainbow'),
               dict(kind='entity', value='5', size=0)],
        hide_groups=[dict(name='Grupo 1', key='F10', active=True), dict(preset='summons', key='1', active=True)]))
    assert cfg['rules'] == [dict(kind='name', value='x', scale=2.0, color='none', key='Nenhuma', enabled=True, label='')]
    assert [(g['what'], g['key'], g['summons'], g['players']) for g in cfg['hide_groups']] == [('summons', '1', True, False)]


# ---- size (client zoom) ----

def test_desired_scales_priority_and_keys():
    cfg = config(rules=[dict(kind='species', value='1051', scale=1.5), dict(kind='name', value='Ishida', scale=3.0),
                        dict(kind='entity', value=str(PLAYER), scale=0.5, key='2', enabled=False)])
    rows = [dict(id=1, species=1051, name='Bikouchuu'), dict(id=2, species=1051, name='ishida'),
            dict(id=PLAYER, species=1, name='Low Profile')]
    assert desired_scales(cfg, rows) == {1: 1.5, 2: 3.0}
    assert desired_scales(dict(cfg, enabled=False), rows) == {}


class FakeMemory:
    def __init__(self, units):
        self.mem = {}
        mode, world, head = 0x1000, 0x2000, 0x3000
        self.put(MODE_MANAGER+4, mode)
        self.put(MODE_MANAGER+88, 1)
        self.put(mode+0xb4, world)
        self.put(world+0x3c, 0)
        self.put(world+0x18, head)
        nodes = [0x4000+i*16 for i in range(len(units))]
        self.put(head, nodes[0] if nodes else head)
        for i, (node, (address, gid)) in enumerate(zip(nodes, units)):
            self.put(node, nodes[i+1] if i+1 < len(nodes) else head)
            self.put(node+8, address)
            self.put(address+0x210, gid)
            self.mem[address+0x3c] = struct.pack('<ff', 1.0, 1.0)

    def put(self, address, value):
        self.mem[address] = struct.pack('<I', value)

    def read(self, address, size):
        return self.mem.get(address, b'\0'*size)[:size]

    def write(self, address, data):
        self.mem[address] = data

    def zoom(self, address):
        return struct.unpack('<f', self.mem[address+0x3c][:4])[0]

    def close(self):
        pass


def test_zoom_writer_sets_and_restores():
    memory = FakeMemory([(0x9000, MONSTER), (0x9100, PLAYER)])
    writer = ZoomWriter(memory_for=lambda pid: memory, pid_finder=lambda: 1, verify=False)
    assert writer.step({MONSTER: 2.0}) == 1
    assert memory.zoom(0x9000) == 2.0 and memory.zoom(0x9100) == 1.0
    assert writer.step({MONSTER: 2.0}) == 0  # already right: nothing written
    writer.step({})
    assert memory.zoom(0x9000) == 1.0 and writer.touched == {}


def test_zoom_writer_leaves_unexpected_values_alone():
    memory = FakeMemory([(0x9000, MONSTER)])
    memory.mem[0x9000+0x3c] = struct.pack('<ff', 1e9, 1e9)
    writer = ZoomWriter(memory_for=lambda pid: memory, pid_finder=lambda: 1, verify=False)
    assert writer.step({MONSTER: 2.0}) == 0


def test_zoom_writer_reports_missing_game():
    writer = ZoomWriter(memory_for=None, pid_finder=lambda: None, verify=False)
    assert writer.step({MONSTER: 2.0}) == 0 and writer.error == 'Jogo não encontrado.'


# ---- panel and config file (regressions) ----

def test_config_file_changes_are_seen_even_if_python_reuses_the_object(tmp_path):
    from nrobot.titan import TitanConfig
    path = tmp_path/'titan.json'
    titan_settings.save(dict(hide_groups=[hide('players', active=False)]), path)
    cfg = TitanConfig(path)
    first = cfg.version, cfg()
    titan_settings.save(dict(hide_groups=[hide('players', active=True)]), path)
    cfg.next_poll = 0
    assert cfg()['hide_groups'][0]['active'] and cfg.version != first[0]


def test_panel_hide_shortcut_edits_reach_the_file_after_a_save(tmp_path, monkeypatch):
    import json
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(titan_settings, 'FILE', tmp_path/'titan.json')
    monkeypatch.setattr(titan_settings, 'SCREEN_FILE', tmp_path/'tela.json')
    from nrobot import titan_panel
    monkeypatch.setattr(titan_panel, 'known_players', lambda: {PLAYER: 'Ishida', PLAYER+1: 'Low Profile'})
    panel = titan_panel.TitanPanel()
    panel.add_hide()
    panel.save_now()  # the old panel replaced its config here and lost every later edit
    panel.hides.selectRow(len(panel.config['hide_groups'])-1)
    panel.hide_key.setCurrentText('3')
    panel.fill_keep()
    for row in range(panel.keep_list.count()):
        entry = panel.keep_list.item(row)
        if entry.data(0x0100) == ('id', PLAYER):
            entry.setCheckState(titan_panel.Qt.Checked)
    panel.toggle_selected_hide()
    saved = json.loads((tmp_path/'titan.json').read_text(encoding='utf-8'))['hide_groups'][-1]
    assert (saved['what'], saved['key'], saved['active'], saved['except_ids']) == ('players', '3', True, [PLAYER])
    app.processEvents()


def test_monsters_only_marked_by_id_hides_just_that_bikouchuu():
    right, other = MONSTER, MONSTER+1
    titan, _ = make(config(hide_groups=[hide('monsters', mode='only', except_ids=[right])]))
    out = titan.feed(spawn_78(right, 1051, 1, 1)+spawn_78(other, 1051, 2, 2)+spawn_22a(PLAYER, 3, 3))
    assert ids(out) == [other] and ids(out, 0x22a, 2) == [PLAYER]


def test_capture_event_wrong_named_bikouchuu_never_shows():
    """Event: many Bikouchuu (same species), only one with the right name. Shortcut "Monstros,
    todos menos os marcados" with the name marked: none shows before its name is known."""
    titan, _ = make(config(hide_groups=[hide('monsters', names=['Bikouchuu'])]))
    right, wrong = MONSTER, MONSTER+1
    assert ids(titan.feed(spawn_78(right, 1051, 1, 1)+spawn_78(wrong, 1051, 2, 2))) == []
    assert titan.take_name_requests() == [right, wrong]  # the relay asks the server right away
    assert titan.take_name_requests() == []
    assert [op for op, _ in ops(titan.feed(name_95(wrong, 'Bikouchu')))] == [0x95]  # stays hidden
    out = titan.feed(name_95(right, 'Bikouchuu'))
    assert [op for op, _ in ops(out)][:2] == [0x95, 0x78] and ids(out) == [right]


def test_names_are_not_asked_when_no_shortcut_uses_them():
    titan, _ = make(config(hide_groups=[hide('monsters', active=False, names=['Bikouchuu'])]))
    titan.feed(spawn_78(MONSTER, 1051, 1, 1))
    assert titan.take_name_requests() == []


def test_name_request_packet_matches_the_client_layout():
    from nrobot.packet_encoder import name_request
    packet = name_request(MONSTER, ticks=lambda: 0x1234)
    assert len(packet) == 14 and packet[:2] == b'\x94\x00'
    assert struct.unpack_from('<I', packet, 10)[0] == MONSTER


def test_monster_shortcut_is_separate_from_players():
    titan, _ = make(config(hide_groups=[hide('monsters')]))
    out = titan.feed(spawn_78(MONSTER, 1051, 1, 1)+spawn_22a(PLAYER, 3, 3))
    assert ids(out) == [] and ids(out, 0x22a, 2) == [PLAYER]


def test_overlay_lists_keyed_shortcuts_with_state():
    from nrobot.titan_overlay import shortcut_rows
    cfg = config(rules=[dict(kind='entity', value='5', scale=2.0, key='1', label='Ishida')],
                 hide_groups=[hide('monsters', mode='only', except_ids=[MONSTER]), dict(hide('players', False), key='2')])
    assert shortcut_rows(cfg) == [('1', 'Ishida: 200%', True), ('2', 'Esconder jogadores', False),
                                  ('F9', 'Esconder 1 marcado(s) (monstros)', True)]


def test_hiding_uses_the_instant_vanish_type():
    titan, box = make(config(hide_groups=[hide('players', active=False)]))
    titan.feed(spawn_22a(PLAYER, 1, 1))
    box['cfg'] = config(hide_groups=[hide('players')])
    (op, packet), = ops(titan.tick())
    assert op == 0x80 and packet[6] == 4  # types 0-3 fade, die or play an effect in this client


def test_player_who_teleported_in_comes_back_standing():
    titan, box = make(config(hide_groups=[hide('players')]))
    arrived = bytearray(57)
    struct.pack_into('<HI', arrived, 0, 0x22b, PLAYER)
    struct.pack_into('<H', arrived, 16, 1)
    arrived[50:53] = encode_position(7, 8, 2)
    struct.pack_into('<H', arrived, 55, 99)
    assert titan.feed(bytes(arrived)) == b''
    box['cfg'] = config(hide_groups=[hide('players', active=False)])
    (op, packet), = ops(titan.tick())
    assert op == 0x22a and len(packet) == 58 and packet[55] == 0 and struct.unpack_from('<H', packet, 56)[0] == 99
    assert decode_position(packet[50:53]) == (7, 8, 2)
