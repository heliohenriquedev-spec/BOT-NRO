import struct

from nrobot.bg_damage import BgDamage, skill_names
from nrobot.packet_reader import decode


def hit(damage, **fields):
    return dict(kind='skill_damage', target_id=1, source_id=2, skill_id=5,
                level=10, damage=damage, **fields)


def observe(log, *events, character=10):
    log.observe(events, 1, character, lambda identity: '')


def test_top_50_are_individual_hits_sorted_and_persisted_per_character(tmp_path):
    path = tmp_path/'bg_danos.json'
    log = BgDamage(path)
    observe(log, dict(kind='map_change', map='bat_nro.gat'),
            dict(kind='bg_team', entity_id=2, team=2, name='Adversário'),
            *(hit(amount) for amount in range(1, 101)))
    rows = log.snapshot(10)['rows']
    assert len(rows) == 50
    assert [row['damage'] for row in rows] == list(range(100, 50, -1))
    assert rows[0]['source_name'] == 'Adversário'
    assert rows[0]['skill_id'] == 5 and rows[0]['level'] == 10
    assert rows[0]['map'] == 'bat_nro.gat' and rows[0]['at']
    reloaded = BgDamage(path)
    assert reloaded.snapshot(10)['rows'] == rows
    assert reloaded.snapshot(11)['rows'] == []
    assert not reloaded.active
    assert reloaded.snapshot(10)['rows'] == rows


def test_only_bg_damage_received_counts_even_when_queued_or_pvp(tmp_path):
    log = BgDamage(tmp_path/'bg.json')
    observe(log, dict(kind='map_change', map='kakashi'),
            dict(kind='bg_team', entity_id=1, team=1),
            dict(kind='bg_team', entity_id=2, team=2), hit(999999))
    assert log.snapshot(10)['rows'] == []
    observe(log, dict(kind='map_change', map='arena_custom'),
            dict(kind='map_type', value=19), hit(999999))
    assert log.snapshot(10)['rows'] == []
    observe(log, dict(kind='bg_team', entity_id=1, team=1),
            dict(kind='bg_team', entity_id=2, team=2), hit(100),
            {**hit(999999), 'target_id': 2}, {**hit(999999), 'source_id': 1},
            hit(0), hit(-1), hit(-2),
            dict(kind='map_transfer', map='kakashi'), hit(999999))
    assert [row['damage'] for row in log.snapshot(10)['rows']] == [100]
    assert not log.active


def test_delayed_name_updates_history_and_repeated_hits_are_kept(tmp_path):
    path = tmp_path/'bg.json'
    log = BgDamage(path)
    observe(log, dict(kind='map_change', map='bat_nro'), hit(100), hit(100))
    assert len(log.snapshot(10)['rows']) == 2
    observe(log, dict(kind='name', entity_id=2, name='Nome recebido depois'))
    assert all(row['source_name'] == 'Nome recebido depois' for row in BgDamage(path).snapshot(10)['rows'])


def test_packet_damage_excludes_misses_and_includes_offhand_without_multiplying_hits(tmp_path):
    log = BgDamage(tmp_path/'bg.json')
    observe(log, dict(kind='map_change', map='bat_nro'))
    basic = bytearray(29)
    struct.pack_into('<HII', basic, 0, 0x8a, 2, 1)
    struct.pack_into('<hhBh', basic, 22, 100, 2, 0, 50)
    event = decode(bytes(basic))
    observe(log, event)
    assert log.snapshot(10)['rows'][0]['damage'] == 150
    assert log.snapshot(10)['rows'][0]['skill_id'] == 0
    for opcode, size, fmt in ((0x114, 31, '<h'), (0x1de, 33, '<i')):
        packet = bytearray(size)
        struct.pack_into('<HHII', packet, 0, opcode, 5, 2, 1)
        struct.pack_into(fmt, packet, 24, -1)
        event = decode(bytes(packet))
        assert event['damage'] == -1 and event['damage_raw'] > 0
        observe(log, event)
        struct.pack_into(fmt, packet, 24, 20000 if opcode == 0x114 else 100000)
        observe(log, decode(bytes(packet)))
    assert [row['damage'] for row in log.snapshot(10)['rows']] == [100000, 20000, 150]


def test_bg_panel_shows_local_skill_name_and_author_and_keeps_history(tmp_path):
    from nrobot.bg_entry import BgPanel
    log = BgDamage(tmp_path/'bg.json')
    observe(log, dict(kind='map_change', map='bat_nro'), hit(12345),
            dict(kind='name', entity_id=2, name='Adversário'))
    panel = BgPanel()
    assert skill_names()[5] == 'Kage Buyou'
    panel.update_state({'bg_damage': log.snapshot(10)})
    assert panel.damage_table.rowCount() == 1
    assert panel.damage_table.item(0, 1).text() == '12.345'
    assert panel.damage_table.item(0, 2).text() == 'Kage Buyou (Nv. 10)'
    assert panel.damage_table.item(0, 3).text() == 'Adversário'
    observe(log, dict(kind='map_transfer', map='kakashi'))
    panel.update_state({'bg_damage': log.snapshot(10)})
    assert panel.damage_table.rowCount() == 1 and 'preservado' in panel.damage_status.text()
    panel.close()


def test_relay_receives_packet_and_publishes_bg_ranking(tmp_path):
    from test_bg_entry import relay
    r = relay(tmp_path)
    r.select_character(10)
    r.tracker.observer.player_id = 1
    r.mirror_ready = True
    map_packet = struct.pack('<H16sHH', 0x91, b'bat_nro.gat', 50, 50)
    packet = bytearray(33)
    struct.pack_into('<HHII', packet, 0, 0x1de, 5, 2, 1)
    struct.pack_into('<iH', packet, 24, 123456, 10)
    r.mirror_map(map_packet + bytes(packet))
    assert not r.tracker.failed
    assert r.status()['bg_damage']['rows'][0]['damage'] == 123456
    assert r.status()['bg_damage']['active']
    assert (tmp_path/'bg_danos.json').exists()
