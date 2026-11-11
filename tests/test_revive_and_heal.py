import asyncio
import time

import pytest

from nrobot import map_routes, quest_extras


def relay(tmp_path, monkeypatch):
    from nrobot.packet_hunt import PacketHunt
    from nrobot.session_relay import SessionRelay
    monkeypatch.setattr(quest_extras, 'FILE', tmp_path/'extras.json')
    r = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True); r.hunt = PacketHunt(); r.apply_settings({})
    o = r.tracker.observer; o.player_id = 1; o.player = [150, 150]; o.player_at = time.monotonic(); o.map_name = 'kakashi'
    r.upstream = object()
    return r


class Upstream:
    def __init__(self): self.sent = []
    def write(self, data): self.sent.append(bytes(data))
    async def drain(self): pass


def test_healer_talk_is_recorded_once(tmp_path, monkeypatch):
    r = relay(tmp_path, monkeypatch)
    r.quest_control('quest_heal_record', {}, lambda: True)
    assert r.quests.recording['scope'] == 'heal'
    r.quests.recording['steps'] += [dict(kind='npc', map='kakashi', position=[160, 150], name='Curandeira'),
                                    dict(kind='next', map='kakashi'), dict(kind='close', map='kakashi')]
    r.quest_control('quest_heal_save', {}, lambda: True)
    config = quest_extras.load()
    assert config['heal_map'] == 'kakashi' and [s['kind'] for s in config['heal_steps']][:3] == ['npc', 'next', 'close']


def test_death_returns_to_save_point_heals_and_goes_back_to_the_hunt(tmp_path, monkeypatch):
    r = relay(tmp_path, monkeypatch)
    quest_extras.save(dict(quest_extras.load(), revive_enabled=True,
                           heal_steps=[dict(kind='npc', map='kakashi.gat', position=[160, 150], name='Curandeira'),
                                       dict(kind='next', map='kakashi.gat'), dict(kind='close', map='kakashi.gat')],
                           heal_map='kakashi'))
    map_routes.save([dict(id='r1', name='Campo', target_map='campo.gat',
                          steps=[dict(kind='portal', map='kakashi.gat', position=[52, 2]), dict(kind='wait_map', map='campo.gat'),
                                 dict(kind='walk', map='campo.gat', position=[100, 100])])])
    o = r.tracker.observer
    o.map_name = 'campo'; o.player = [100, 100]
    r.quest_control('quest_hunt_database', dict(target_map='campo', species=[1031]), lambda: True)
    r.quests.phase = 'hunt'
    up = r.upstream = Upstream()
    o.player_alive = False
    async def tick():
        return await r.quest_tick(lambda: True)
    assert asyncio.run(tick())
    assert up.sent == [bytes((0xb2, 0, 0))] and r.quests.active  # not paused: back to the save point
    asyncio.run(tick())
    assert up.sent == [bytes((0xb2, 0, 0))]  # not sent again right away
    # The server takes the character to the save point, alive.
    o.player_alive = True; o.map_name = 'kakashi'; o.player = [150, 150]; o.player_at = time.monotonic()
    asyncio.run(tick())
    kinds = [s['kind'] for s in r.quests.steps]
    assert kinds[:3] == ['npc', 'next', 'close'] and ['portal', 'wait_map'] == kinds[3:5]  # heal, then back
    assert r.quests.phase == 'travel' and 'Curandeira' in r.quests.reason


def test_without_the_option_death_still_pauses(tmp_path, monkeypatch):
    r = relay(tmp_path, monkeypatch)
    map_routes.save([dict(id='r1', name='Campo', target_map='campo.gat', steps=[dict(kind='walk', map='campo.gat', position=[1, 1])])])
    o = r.tracker.observer; o.map_name = 'campo'; o.player = [1, 1]
    r.quest_control('quest_hunt_database', dict(target_map='campo', species=[1031]), lambda: True)
    r.quests.phase = 'hunt'; o.player_alive = False
    asyncio.run(r.quest_tick(lambda: True))
    assert not r.quests.active and 'morreu' in r.quests.reason


def test_heal_test_button_walks_to_the_healer_and_talks(tmp_path, monkeypatch):
    r = relay(tmp_path, monkeypatch)
    quest_extras.save(dict(quest_extras.load(), heal_steps=[dict(kind='npc', map='hospital2.gat', position=[50, 60], name='Medica'),
                                                            dict(kind='walk', map='hospital2.gat', position=[50, 58])], heal_map='hospital2'))
    r.tracker.observer.map_name = 'hospital2'
    r.quest_control('quest_heal_test', {}, lambda: True)
    assert r.quests.validation['label'] == 'Teste da cura' and r.quests.steps[0]['kind'] == 'npc'


def test_plain_hunt_death_revives_heals_and_hunts_again_on_the_same_map(tmp_path, monkeypatch):
    r = relay(tmp_path, monkeypatch)
    quest_extras.save(dict(quest_extras.load(), revive_enabled=True,
                           heal_steps=[dict(kind='npc', map='hospital2.gat', position=[50, 60], name='Medica')], heal_map='hospital2'))
    map_routes.save([dict(id='r1', name='Campo', target_map='campo.gat',
                          steps=[dict(kind='portal', map='hospital2.gat', position=[103, 3]), dict(kind='wait_map', map='campo.gat'),
                                 dict(kind='walk', map='campo.gat', position=[10, 10])])])
    o = r.tracker.observer; o.map_name = 'campo'; o.player = [40, 40]
    r.hunt.start()
    up = r.upstream = Upstream()
    o.player_alive = False
    assert asyncio.run(r.quest_tick(lambda: True)) and up.sent == [bytes((0xb2, 0, 0))] and not r.hunt.enabled
    o.player_alive = True; o.map_name = 'hospital2'; o.player = [60, 60]; o.player_at = time.monotonic()
    asyncio.run(r.quest_tick(lambda: True))
    assert [s['kind'] for s in r.quests.steps][:3] == ['npc', 'portal', 'wait_map'] and r.quests.active
    r.quests.complete_validation()  # arrived back on campo
    asyncio.run(r.quest_tick(lambda: True))
    assert r.hunt.enabled and r.hunt_revive is None


def test_plain_hunt_death_puts_the_combat_items_back_on_before_hunting(tmp_path, monkeypatch):
    r = relay(tmp_path, monkeypatch)
    quest_extras.save(dict(quest_extras.load(), revive_enabled=True, characters={'Saga': dict(combat_items=[501])}))
    r.own_look = dict(name='Saga')
    map_routes.save([dict(id='r1', name='Campo', target_map='campo.gat',
                          steps=[dict(kind='portal', map='hospital2.gat', position=[103, 3]), dict(kind='wait_map', map='campo.gat'),
                                 dict(kind='walk', map='campo.gat', position=[10, 10])])])
    o = r.tracker.observer; o.map_name = 'campo'; o.player = [40, 40]
    r.hunt.start()
    up = r.upstream = Upstream()
    o.player_alive = False
    asyncio.run(r.quest_tick(lambda: True))
    o.player_alive = True; o.map_name = 'hospital2'; o.player = [60, 60]; o.player_at = time.monotonic()
    asyncio.run(r.quest_tick(lambda: True))
    r.quests.complete_validation()  # arrived back on campo, mounted
    r.quests.body.gear = {7: dict(item_id=501, type=4, amount=1, worn=0, equip_location=2)}
    asyncio.run(r.quest_tick(lambda: True))
    assert not r.hunt.enabled and r.hunt_revive['stage'] == 'gear'
    assert 'Equipamentos' in r.quests.reason  # the item goes on before the hunt starts
    r.quests.body.gear[7]['worn'] = 2
    r.quests.errands[0].pending = None
    asyncio.run(r.quest_tick(lambda: True))  # equipped: errand done
    asyncio.run(r.quest_tick(lambda: True))
    assert r.hunt.enabled and r.hunt_revive is None


def test_plain_hunt_death_trip_back_is_made_mounted(tmp_path, monkeypatch):
    r = relay(tmp_path, monkeypatch)
    quest_extras.save(dict(quest_extras.load(), revive_enabled=True,
                           mount_enabled=True, characters={'Saga': dict(mount_item=12622)}))
    r.own_look = dict(name='Saga')
    map_routes.save([dict(id='r1', name='Campo', target_map='campo.gat',
                          steps=[dict(kind='portal', map='hospital2.gat', position=[103, 3]), dict(kind='wait_map', map='campo.gat'),
                                 dict(kind='walk', map='campo.gat', position=[10, 10])])])
    o = r.tracker.observer; o.map_name = 'campo'; o.player = [40, 40]
    r.hunt.start()
    r.upstream = Upstream()
    o.player_alive = False
    asyncio.run(r.quest_tick(lambda: True))
    o.player_alive = True; o.map_name = 'hospital2'; o.player = [60, 60]; o.player_at = time.monotonic()
    asyncio.run(r.quest_tick(lambda: True))
    assert [e.kind for e in r.quests.errands] == ['mount']  # the mount goes on before walking back
