"""A weapon breaks while hunting: to the recorded Reparador, back to the map, the weapon on again."""
import asyncio
import struct
import time

from nrobot import map_routes, quest_extras
from nrobot.packet_reader import decode
from nrobot.quest_extras import Body
from test_revive_and_heal import relay, Upstream


def test_break_packet_and_damaged_flag_are_read():
    event = decode(struct.pack('<HHI', 0x2bb, 2, 2003137))
    assert event['kind'] == 'equip_damaged' and event['location'] == 2
    body = Body()
    body.observe([dict(kind='inventory_list', stackable=False,
                       items=[dict(index=7, item_id=1201, type=4, equipped=2, equip_location=2)])], 1, 10)
    body.observe([dict(kind='equip_damaged', location=2, account_id=1)], 1, 11)
    assert body.broken == dict(at=11, location=2, item_id=1201)


def test_repairer_talk_is_recorded_once(tmp_path, monkeypatch):
    r = relay(tmp_path, monkeypatch)
    r.quest_control('quest_repair_record', {}, lambda: True)
    assert r.quests.recording['scope'] == 'repair'
    r.quests.recording['steps'] += [dict(kind='npc', map='kakashi', position=[102, 28], name='Reparador'),
                                    dict(kind='next', map='kakashi'), dict(kind='select', map='kakashi', option='Sim')]
    r.quest_control('quest_repair_save', {}, lambda: True)
    config = quest_extras.load()
    assert config['repair_map'] == 'kakashi' and any(s['kind'] == 'npc' for s in config['repair_steps'])
    assert not config.get('heal_steps')  # the healer is a separate recording


def test_broken_weapon_goes_to_the_repairer_and_back_to_hunt_with_it(tmp_path, monkeypatch):
    r = relay(tmp_path, monkeypatch)
    quest_extras.save(dict(quest_extras.load(), repair_enabled=True,
                           repair_steps=[dict(kind='npc', map='campo.gat', position=[50, 60], name='Reparador'),
                                         dict(kind='select', map='campo.gat', option='Sim')]))
    o = r.tracker.observer; o.map_name = 'campo'; o.player = [40, 40]; o.player_at = time.monotonic()
    r.hunt.start()
    r.upstream = Upstream()
    r.quests.body.broken = dict(at=1, location=2, item_id=1201)
    assert asyncio.run(r.quest_tick(lambda: True))
    assert not r.hunt.enabled and r.hunt_revive['stage'] == 'trip' and 'Reparador' in r.quests.reason
    assert [s['kind'] for s in r.quests.steps][:2] == ['npc', 'select'] and r.quests.reequip == [1201]
    r.quests.complete_validation()  # repaired and back on campo
    r.quests.body.gear = {7: dict(item_id=1201, type=4, amount=1, worn=0, equip_location=2)}
    asyncio.run(r.quest_tick(lambda: True))
    assert r.hunt_revive['stage'] == 'gear'
    assert 1201 in r.quests.errands[0].config['combat_items']  # the repaired weapon goes back on


def test_without_a_recorded_repair_the_hunt_goes_on(tmp_path, monkeypatch):
    r = relay(tmp_path, monkeypatch)
    o = r.tracker.observer; o.map_name = 'campo'; o.player = [40, 40]; o.player_at = time.monotonic()
    r.hunt.start()
    r.quests.body.broken = dict(at=1, location=2, item_id=1201)
    asyncio.run(r.quest_tick(lambda: True))
    assert r.hunt.enabled and r.quests.body.broken is None


def test_any_broken_item_in_the_list_counts_even_not_worn():
    body = Body()
    body.observe([dict(kind='inventory_list', stackable=False,
                       items=[dict(index=56, item_id=27886, type=4, equipped=0, equip_location=2, damaged=True),
                              dict(index=95, item_id=27234, type=4, equipped=2, equip_location=2, damaged=False)])], 1, 10)
    assert body.broken['item_id'] == 27886 and body.damaged_items() == [27886]
    assert next(i for i in body.items() if i['index'] == 56)['damaged']


def test_damaged_flag_is_read_from_the_equipment_list():
    item = struct.pack('<HHBBHHBB', 56, 27886, 4, 1, 2, 0, 1, 0)+bytes(16)  # 28-byte EQUIPITEM_INFO, IsDamaged=1
    message = struct.pack('<HH', 0x2d0, 4+len(item))+item
    event = decode(message)
    assert event['kind'] == 'inventory_list' and event['items'][0]['damaged'] is True


def test_a_repair_that_did_not_fix_it_is_not_repeated_at_once(tmp_path, monkeypatch):
    r = relay(tmp_path, monkeypatch)
    quest_extras.save(dict(quest_extras.load(), repair_enabled=True,
                           repair_steps=[dict(kind='npc', map='campo.gat', position=[50, 60], name='Reparador')]))
    o = r.tracker.observer; o.map_name = 'campo'; o.player = [40, 40]; o.player_at = time.monotonic()
    r.hunt.start()
    r.repair_started_at = time.monotonic()
    r.quests.body.broken = dict(at=1, location=2, item_id=27886)
    asyncio.run(r.quest_tick(lambda: True))
    assert r.hunt.enabled and getattr(r, 'hunt_revive', None) is None


def test_without_a_way_out_of_the_hunting_map_it_uses_voltar_first(tmp_path, monkeypatch):
    r = relay(tmp_path, monkeypatch)
    quest_extras.save(dict(quest_extras.load(), repair_enabled=True, voltar_frame='00f3', voltar_enabled=False,
                           repair_steps=[dict(kind='portal', map='hospital2.gat', position=[103, 3]),
                                         dict(kind='wait_map', map='areia.gat'),
                                         dict(kind='npc', map='areia.gat', position=[50, 60], name='Reparador')]))
    map_routes.save([dict(id='r1', name='Campo', target_map='campo.gat',
                          steps=[dict(kind='portal', map='areia.gat', position=[10, 10]), dict(kind='wait_map', map='campo.gat'),
                                 dict(kind='walk', map='campo.gat', position=[40, 40])])])
    o = r.tracker.observer; o.map_name = 'campo'; o.player = [40, 40]; o.player_at = time.monotonic()
    r.hunt.start()
    r.upstream = Upstream()
    r.quests.body.broken = dict(at=1, location=2, item_id=27886)
    assert asyncio.run(r.quest_tick(lambda: True))
    assert [s['map'] for s in r.quests.steps if s['kind'] == 'wait_map'] == ['areia.gat', 'campo.gat']  # and back
    assert r.quests.errands and r.quests.errands[0].kind == 'voltar' and '@voltar' in r.quests.reason
    assert r.quests.steps[0] == dict(kind='portal', map='hospital2.gat', position=[103, 3])


def test_event_npcs_are_not_transports():
    from nrobot.npc_transports import as_entries, harmful
    steps = [dict(kind='npc', map='areia.gat', position=[177, 105], name='Entrada - Bikouchuu#1'),
             dict(kind='wait_map', map='poring_w01.gat')]
    assert harmful(steps)
    known = {'areia': {'177,105>poring_w01>': dict(steps=steps, to='poring_w01')},
             'poring_w01': {'100,127>hospital2>': dict(steps=[dict(kind='npc', map='poring_w01.gat', position=[100, 127],
                                                                   name='Poring Catcher#evnt2'),
                                                              dict(kind='wait_map', map='hospital2.gat')], to='hospital2')}}
    assert as_entries(known) == []


def test_repair_is_joined_at_the_furthest_reachable_map():
    from nrobot.quest_relay import QuestRelay
    steps = [dict(kind='portal', map='hospital2.gat', position=[103, 3]), dict(kind='wait_map', map='areia.gat'),
             dict(kind='npc', map='areia.gat', position=[174, 160], name='Teleportador'),
             dict(kind='portal', map='areia.gat', position=[96, 234]), dict(kind='wait_map', map='ama_in01.gat'),
             dict(kind='npc', map='ama_in01.gat', position=[102, 28], name='Reparador')]

    class Q:
        def connection(self, here, there):
            if there == 'hospital2' or here == 'areia':
                raise ValueError('sem caminho')
            return [dict(kind='portal', map=here+'.gat', position=[1, 1]), dict(kind='wait_map', map=there+'.gat')]
    path = QuestRelay.repair_join(Q(), 'campo', steps)
    assert path[1] == dict(kind='wait_map', map='ama_in01.gat') and path[2]['name'] == 'Reparador'  # straight to it
    assert QuestRelay.repair_join(Q(), 'areia', steps)[0]['name'] == 'Teleportador'  # already on the way, no shortcut known


def test_routes_ignore_finished_monsters_by_default():
    from nrobot.quest_routes import validate_routes
    route = validate_routes([dict(name='Nova', target_map='campo.gat', steps=[dict(kind='walk', map='campo.gat', position=[1, 1])])])[0]
    assert route['ignore_finished'] is True
