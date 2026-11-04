"""@voltar after the hunt and the mount for trips, learned from the player's own packets."""
import asyncio
import os
import struct
import time
from nrobot import quest_extras
from nrobot.quest_extras import Body, Errand, chat_frame
from nrobot.quest_routes import QuestRoutes

OWN, MOB = 2000001, 110000500
FRAME = (b'\xf3\x00'+(4+len(b'Shinobi : @voltar\0')).to_bytes(2, 'little')+b'Shinobi : @voltar\0').hex()
CONFIG = dict(quest_extras.DEFAULTS, voltar_enabled=True, voltar_frame=FRAME, calm_seconds=5, cast_timeout=10,
              mount_enabled=True, mount=dict(item_id=9001, location=0x100, displaced=[dict(item_id=2301, position=0x10)]))


def hit(source, target, kind='normal_attack', damage=10):
    return dict(kind=kind, source_id=source, target_id=target, damage_raw=damage)


def test_voltar_kills_around_waits_out_of_combat_retries_when_hit_and_ends_on_teleport():
    body = Body(); errand = Errand('voltar', CONFIG, 0)
    body.observe([hit(MOB, OWN)], OWN, 10)
    assert errand.step(body, [(MOB, 1139)], 10) == ('clear', [1139])
    assert errand.step(body, [], 12)[0] == 'wait'  # monster dead, still in combat (5 s)
    action, frame = errand.step(body, [], 15.5)
    assert action == 'chat' and frame == bytes.fromhex(FRAME) and errand.attempts == 1
    body.observe([hit(MOB+1, OWN)], OWN, 17)  # physical hit while casting
    assert errand.step(body, [(MOB+1, 1139)], 17) == ('wait', None) and 'cancelada' in errand.reason
    assert errand.step(body, [(MOB+1, 1139)], 17.1) == ('clear', [1139])
    assert errand.step(body, [], 23)[0] == 'chat' and errand.attempts == 2
    body.observe([dict(kind='map_change', map='konoha', position=[1, 1])], OWN, 26)
    assert errand.step(body, [], 26) == ('done', None)


def test_voltar_needs_to_be_learned_and_gives_up_after_the_attempts():
    errand = Errand('voltar', dict(CONFIG, voltar_frame=''), 0)
    assert errand.step(Body(), [], 100)[0] == 'fail'
    errand = Errand('voltar', dict(CONFIG, attempts=1), 0); body = Body()
    assert errand.step(body, [], 100)[0] == 'chat'
    errand.step(body, [], 111)  # no teleport within 10 s
    assert errand.step(body, [], 112)[0] == 'fail'


def test_speaker_of_the_learned_frame_follows_the_character_playing():
    frame = chat_frame(FRAME, 'Uadaweu2')
    assert frame[4:] == b'Uadaweu2 : @voltar\0' and int.from_bytes(frame[2:4], 'little') == len(frame)
    assert chat_frame(FRAME) == bytes.fromhex(FRAME)


def gear_body():
    body = Body()
    body.observe([dict(kind='inventory_list', stackable=False, items=[
        dict(index=5, item_id=9001, equip_location=0x100, equipped=0),
        dict(index=6, item_id=2301, equip_location=0x10, equipped=0x10)])], OWN, 0)
    return body


def test_mount_is_equipped_out_of_combat_and_remembers_what_it_took_off():
    body = gear_body(); errand = Errand('mount', CONFIG, 0)
    body.observe([hit(OWN, MOB)], OWN, 1)
    assert errand.step(body, [], 2)[0] == 'wait'
    assert errand.step(body, [], 7) == ('equip', (5, 0x100))
    body.observe([dict(kind='equipment_ack', index=6, position=0x10, success=True, equipped=False),
                  dict(kind='equipment_ack', index=5, position=0x100, success=True, equipped=True)], OWN, 7.3)
    assert errand.step(body, [], 7.4) == ('done', None)
    assert errand.displaced == [dict(item_id=2301, position=0x10)] and body.wearing(9001)


def test_mount_refused_in_combat_tries_again():
    body = gear_body(); errand = Errand('mount', CONFIG, 0)
    assert errand.step(body, [], 10)[0] == 'equip'
    body.observe([dict(kind='equipment_ack', index=5, position=0x100, success=False, equipped=True)], OWN, 10.2)
    errand.step(body, [], 10.3)
    assert 'recusou' in errand.reason and errand.step(body, [], 10.4)[0] == 'wait'
    assert errand.step(body, [], 11.4) == ('equip', (5, 0x100))


def test_combat_equipment_goes_back_on_before_the_hunt():
    body = gear_body(); body.gear[6]['worn'] = 0; body.gear[5]['worn'] = 0x100
    errand = Errand('gear', dict(CONFIG, displaced=CONFIG['mount']['displaced']), 0)
    assert errand.step(body, [], 1) == ('equip', (6, 0x10))
    body.observe([dict(kind='equipment_ack', index=6, position=0x10, success=True, equipped=True)], OWN, 1.2)
    assert errand.step(body, [], 1.3) == ('done', None)


def test_route_queues_mount_for_trips_gear_for_the_hunt_and_voltar_after_it():
    q = QuestRoutes(); q.extras = CONFIG
    q.start([dict(id='R', name='R', target_map='field', species=[1139], kills=1,
                  steps=[dict(kind='walk', map='field', position=[1, 1])])], 0)
    assert [e.kind for e in q.errands] == ['mount']  # first trip
    q.errand_done(); q.plan('field', [1, 1], None, None, 1)
    assert q.phase == 'hunt' and [e.kind for e in q.errands] == ['gear']
    q.errand_done(); q.finish_hunt(2)
    assert q.errands[0].kind == 'voltar'
    q.stop('x'); assert q.errands == []


def test_learning_from_the_players_own_packets():
    q = QuestRoutes(); q.learning = dict(what='voltar')
    q.native(0xf3, bytes.fromhex(FRAME), 'konoha')
    assert q.learned_extras == dict(voltar_frame=FRAME, voltar_enabled=True) and q.learning is None  # learning turns it on
    q = QuestRoutes(); q.body = gear_body(); q.learning = dict(what='mount')
    q.native(0xa9, struct.pack('<HHH', 0xa9, 5, 0x100), 'konoha')
    at = q.learning['captured']['at']
    q.observe([dict(kind='equipment_ack', index=6, position=0x10, success=True, equipped=False),
               dict(kind='equipment_ack', index=5, position=0x100, success=True, equipped=True)], OWN, 'konoha', at+0.2)
    q.observe([], OWN, 'konoha', at+3.5)
    assert q.learned_extras == dict(mount=dict(item_id=9001, location=0x100, displaced=[dict(item_id=2301, position=0x10)]))


def test_relay_runs_the_errand_with_the_hunt_and_native_packets(tmp_path, monkeypatch):
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_hunt import PacketHunt
    from nrobot.network_targets import Entity
    monkeypatch.setattr(quest_extras, 'FILE', tmp_path/'extras.json')

    class Upstream:
        def __init__(self): self.sent = []
        def write(self, data): self.sent.append(bytes(data))
        async def drain(self): pass

    async def scenario():
        r = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True); r.hunt = PacketHunt(); r.apply_settings({})
        r.upstream = Upstream(); r.native_frames.buffer = b''
        o = r.tracker.observer; o.player_id = OWN; o.player = [50, 50]; o.player_at = time.monotonic(); o.map_name = 'field'
        q = r.quests; q.phase = 'delivery'; q.routes = [dict(id='R', name='R', mission_ids=[], kill_targets=[], kills=1)]; q.index = 0
        q.errands = [Errand('voltar', CONFIG, 0)]
        r.inventory.observe([dict(kind='appearance', entity_id=MOB, species_id=1139, position=[52, 50]),
                             dict(kind='appearance', entity_id=MOB+1, species_id=1294, position=[51, 50])], time.monotonic())
        # neither is a hunt target (registry empty): before @voltar both are fought, the one attacking
        # and the one just standing within the radius
        q.body.attackers[MOB] = time.monotonic()
        assert await r.quest_errand(time.monotonic(), lambda: True) is False  # hunting the one attacking
        assert r.hunt.enabled and r.settings['species'] == [1139, 1294]
        r.inventory.observe([dict(kind='remove', entity_id=MOB, reason=1), dict(kind='remove', entity_id=MOB+1, reason=1)], time.monotonic())
        q.body.last_combat = -100
        assert await r.quest_errand(time.monotonic(), lambda: True) is True
        assert not r.hunt.enabled and r.upstream.sent and r.upstream.sent[-1][:2] == b'\xf3\x00'
    asyncio.run(scenario())


def test_panel_box_saves_the_options(tmp_path, monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from nrobot.quest_panel import ExtrasBox
    monkeypatch.setattr(quest_extras, 'FILE', tmp_path/'extras.json')
    app = QApplication.instance() or QApplication([])
    box = ExtrasBox(); box.voltar.setChecked(True); box.calm.setValue(8)
    saved = quest_extras.load()
    assert saved['voltar_enabled'] and saved['calm_seconds'] == 8 and 'nao aprendido' in box.status.text()
    box.close()


def test_monster_attacking_during_the_quest_hunt_is_fought_too():
    q = QuestRoutes(); q.phase = 'hunt'
    q.observe([dict(kind='appearance', entity_id=MOB, species_id=1294, position=[1, 1]),
               dict(kind='appearance', entity_id=2000999, species_id=4016, position=[1, 2]),
               hit(MOB, OWN), hit(2000999, OWN)], OWN, 'anthell02', 1)
    assert q.aggressors == {1294}  # Inseto Assassino in; a player who hit us is not a monster target


def test_relay_adds_the_aggressor_to_the_hunt(tmp_path):
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_hunt import PacketHunt

    async def scenario():
        r = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True); r.hunt = PacketHunt(); r.apply_settings({})
        r.upstream = object()
        o = r.tracker.observer; o.player_id = OWN; o.player = [5, 5]; o.player_at = time.monotonic(); o.map_name = 'anthell02'
        q = r.quests; q.phase = 'hunt'; q.index = 0
        q.routes = [dict(id='R', name='R', target_map='anthell02', species=[1632], kill_targets=[dict(name='Gremlin', count=50, species=[1632])], kills=1)]
        await r.quest_tick(lambda: True)
        assert r.settings['species'] == [1632]
        r.inventory.observe([dict(kind='appearance', entity_id=MOB, species_id=1294, position=[6, 5])], time.monotonic())
        r.hunt.aggressors[MOB] = time.monotonic()  # an Inseto Assassino hits the character
        await r.quest_tick(lambda: True)
        assert r.settings['species'] == [1294, 1632] and r.hunt.enabled
    asyncio.run(scenario())


def test_game_combat_messages_are_read():
    from nrobot.packet_reader import decode
    def message(text):
        body = text.encode('cp1252')+b'\0'
        return struct.pack('<HH', 0x8e, 4+len(body))+body
    entered = decode(message('[Combate] Você entrou em combate!'))
    left = decode(message('[Combate] Você saiu de combate.'))
    wait = decode(message('Você está em combate, aguarde 8 segundos.'))
    assert (entered['kind'], entered['state']) == ('combat_notice', 'in')
    assert left['state'] == 'out' and wait['seconds'] == 8
    assert decode(message('Ola pessoal'))['kind'] == 'other'


def test_leaving_combat_message_lets_voltar_go_at_once_and_a_refusal_restarts_it():
    body = Body(); errand = Errand('voltar', dict(CONFIG, calm_seconds=30), 0)
    body.observe([hit(MOB, OWN)], OWN, 10)
    assert errand.step(body, [], 11)[0] == 'wait'
    body.observe([dict(kind='combat_notice', text='Você saiu de combate.', state='out', seconds=None)], OWN, 12)
    assert errand.step(body, [], 12)[0] == 'chat'  # no 30 s wait: the game said so
    body.observe([dict(kind='combat_notice', text='Você está em combate, aguarde 5 segundos.', state='in', seconds=5)], OWN, 12.5)
    errand.step(body, [], 12.6)
    assert errand.state == 'clear' and 'recusado' in errand.reason
    assert errand.step(body, [], 13)[0] == 'wait' and errand.step(body, [], 17.6)[0] == 'chat'


def inventory_body():
    body = Body()
    body.observe([dict(kind='inventory_list', stackable=False, items=[
        dict(index=5, item_id=9001, type=5, equip_location=0x100, equipped=0),
        dict(index=6, item_id=1224, type=4, equip_location=0x2, equipped=0x2),
        dict(index=7, item_id=2301, type=5, equip_location=0x10, equipped=0)]),
        dict(kind='inventory_list', stackable=True, items=[
        dict(index=20, item_id=13250, type=10, amount=500, equipped=0),
        dict(index=21, item_id=501, type=0, amount=30, equipped=0)])], OWN, 0)
    return body


def test_whole_inventory_is_kept_for_the_panel():
    body = inventory_body()
    assert [i['item_id'] for i in body.items()] == [9001, 1224, 2301, 13250, 501]
    body.observe([dict(kind='inventory_removed', inventory_index=21, amount=30),
                  dict(kind='inventory_list', stackable=True, items=[dict(index=20, item_id=13250, type=10, amount=499, equipped=0)])], OWN, 1)
    assert [i['item_id'] for i in body.items()] == [9001, 1224, 2301, 13250]  # the equipment list stays


def test_items_chosen_for_this_character_are_used():
    config = dict(CONFIG, mount=None, characters={'Shinobi': dict(mount_item=9001, combat_items=[2301, 13250])})
    mine, other = quest_extras.for_character(config, 'Shinobi'), quest_extras.for_character(config, 'Outro')
    assert mine['mount']['item_id'] == 9001 and mine['combat_items'] == [2301, 13250]
    assert other['combat_items'] == [] and other['mount'] is None
    body = inventory_body()
    assert Errand('mount', mine, 0).step(body, [], 100) == ('equip', (5, 0x100))  # position from the inventory
    gear = Errand('gear', mine, 0)
    assert gear.step(body, [], 1) == ('equip', (7, 0x10))
    body.observe([dict(kind='equipment_ack', index=7, position=0x10, success=True, equipped=True)], OWN, 1.1)
    assert gear.step(body, [], 1.2) == ('equip', (20, 0x8000))  # kunai/shuriken go in the ammo slot
    body.observe([dict(kind='ammo_equipped', index=20)], OWN, 1.3)
    assert gear.step(body, [], 1.4) == ('done', None) and body.wearing(13250)


def test_combat_items_alone_are_equipped_before_the_hunt_even_without_mount():
    q = QuestRoutes(); q.extras = quest_extras.for_character(dict(quest_extras.DEFAULTS, characters={'S': dict(combat_items=[1224])}), 'S')
    q.queue('gear', 0); q.queue('mount', 0)
    assert [e.kind for e in q.errands] == ['gear']


def test_mounts_and_combat_items_are_told_apart():
    from nrobot import item_names
    items = [dict(item_id=2643, type=5, equip_location=0x23, worn=0), dict(item_id=16813, type=5, equip_location=0x20, worn=0x20),
             dict(item_id=27895, type=4, equip_location=0x2, worn=0), dict(item_id=19207, type=5, equip_location=0x1, worn=0x1),
             dict(item_id=13254, type=10, equip_location=0, worn=0x8000), dict(item_id=2301, type=5, equip_location=0x10, worn=0x10),
             dict(item_id=9100, type=5, equip_location=0x1, worn=0)]
    descriptions = {9100: 'Montaria: Lobo do deserto.'}
    assert [i['item_id'] for i in item_names.mount_choices(items, descriptions)] == [2643, 9100]
    assert [i['item_id'] for i in item_names.combat_choices(items, descriptions)] == [16813, 27895, 19207, 13254]


def test_switch_lists_every_mount_and_the_combat_equipment_in_two_tabs():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QHeaderView
    from PySide6.QtCore import Qt
    from nrobot.quest_panel import SwitchDialog
    app = QApplication.instance() or QApplication([])
    inventory = [dict(item_id=2643, type=5, equip_location=0x23, worn=0), dict(item_id=9100, type=5, equip_location=0x1, worn=0),
                 dict(item_id=16813, type=5, equip_location=0x20, worn=0x20), dict(item_id=13254, type=10, equip_location=0, worn=0x8000),
                 dict(item_id=2301, type=5, equip_location=0x10, worn=0x10)]
    dialog = SwitchDialog('Uadaweu2', inventory, dict(mount_item=2643), {2643: 'Montaria - Raposa'}, {9100: 'Montaria: Lobo.'})
    assert dialog.mounts.rowCount() == 2 and dialog.mounts.item(0, 2).text() == 'Montaria - Raposa'
    assert [dialog.combat.item(r, 1).text() for r in range(dialog.combat.rowCount())] == ['16813', '13254']
    assert dialog.combat.chosen() == [16813, 13254]  # what is worn now comes ticked the first time
    assert dialog.mounts.verticalHeader().sectionResizeMode(0) == QHeaderView.Fixed and not dialog.mounts.wordWrap()
    dialog.mounts.item(1, 0).setCheckState(Qt.Checked)
    dialog.combat.item(1, 0).setCheckState(Qt.Unchecked)
    assert dialog.selection() == dict(mount_item=9100, combat_items=[16813])


def test_voltar_refused_by_the_server_skill_waits_the_whole_combat_time_again():
    body = Body(); errand = Errand('voltar', dict(CONFIG, calm_seconds=10), 0)
    assert errand.step(body, [], 100)[0] == 'chat'
    body.observe([dict(kind='skill_failed', skill_id=960, cause_raw=0, flag_raw=0)], OWN, 100.2)
    errand.step(body, [], 100.3)
    assert errand.state == 'clear' and 'recusado' in errand.reason
    assert errand.step(body, [], 105)[0] == 'wait' and errand.step(body, [], 110.4)[0] == 'chat'


def test_voltar_casting_time_comes_from_the_server():
    body = Body(); errand = Errand('voltar', dict(CONFIG, cast_timeout=5), 0)
    errand.step(body, [], 100)
    body.observe([dict(kind='skill_cast', skill_id=960, source_id=OWN, target_id=OWN, duration_ms=8000)], OWN, 100.3)
    assert errand.step(body, [], 110)[0] == 'wait' and errand.state == 'cast'  # 8 s cast + margin, not 5 s
    body.observe([dict(kind='map_change', map='konoha', position=[1, 1])], OWN, 108.5)
    assert errand.step(body, [], 110) == ('done', None)


def test_equip_buttons_run_outside_the_queue_and_learning_is_saved_at_once(tmp_path, monkeypatch):
    from nrobot.session_relay import SessionRelay
    monkeypatch.setattr(quest_extras, 'FILE', tmp_path/'extras.json')
    quest_extras.save(dict(quest_extras.DEFAULTS, characters={'Shinobi': dict(mount_item=9001, combat_items=[2301])}))

    class Upstream:
        def __init__(self): self.sent = []
        def write(self, data): self.sent.append(bytes(data))
        async def drain(self): pass

    async def scenario():
        r = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True); r.upstream = Upstream(); r.native_frames.buffer = b''
        r.own_look = {'name': 'Shinobi'}
        o = r.tracker.observer; o.player_id = OWN; o.player = [5, 5]; o.player_at = time.monotonic(); o.map_name = 'konoha'
        r.quests.body = gear_body()
        r.quest_control('quest_extras_equip', dict(what='mount'), lambda: True)
        assert await r.quest_tick(lambda: True) is True
        assert r.upstream.sent[-1] == struct.pack('<HHH', 0xa9, 5, 0x100)
        r.quests.learning = dict(what='voltar'); r.quests.native(0xf3, bytes.fromhex(FRAME), 'konoha')
        r.quest_events([], time.monotonic())  # saved right away, queue or not
        assert quest_extras.load()['voltar_frame'] == FRAME
        r.quest_events([dict(kind='skill_failed', opcode='0110', skill_id=960)], time.monotonic())
        assert '960' in (tmp_path/'respostas_voltar.jsonl').read_text(encoding='utf-8')
    asyncio.run(scenario())


def test_switch_button_only_saves_the_choice_for_this_character(tmp_path, monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    import nrobot.quest_panel as panel
    monkeypatch.setattr(quest_extras, 'FILE', tmp_path/'extras.json')
    app = QApplication.instance() or QApplication([])

    class Dialog:
        def __init__(self, *a, **k): pass
        def exec(self): return True
        def selection(self): return dict(mount_item=2643, combat_items=[16813, 13254])
    monkeypatch.setattr(panel, 'SwitchDialog', Dialog)
    box = panel.ExtrasBox(); sent = []
    box.command_requested.connect(lambda c, v: sent.append((c, v)))
    box.item_tables = ({}, {})
    box.state = {'own_look': {'name': 'Uadaweu2'}, 'quests': {'inventory': [dict(item_id=2643, type=5, equip_location=0x23, worn=0)]}}
    box.choose_items()
    assert sent == []  # nothing is equipped now; the queue uses the choice
    saved = quest_extras.load()
    assert saved['characters']['Uadaweu2'] == dict(mount_item=2643, combat_items=[16813, 13254]) and saved['mount_enabled']


def test_mount_received_this_session_is_listed_by_its_name_with_the_mount_slots():
    from nrobot import item_names
    items = [dict(index=60, item_id=2643, type=5, equip_location=35, worn=35),
             dict(index=79, item_id=2642, type=5, equip_location=0, worn=0),  # 0A0A: slots not sent
             dict(index=80, item_id=999, type=5, equip_location=0, worn=0)]
    names = {2643: 'Montaria - Raposa', 2642: 'Montaria - Lobo', 999: 'Chapeu'}
    descriptions = {2642: 'Um lobo muito veloz, perfeito para longas viagens'}
    mounts = item_names.mount_choices(items, descriptions, names)
    assert [(m['item_id'], m['equip_location']) for m in mounts] == [(2643, 35), (2642, 35)]
    assert item_names.combat_choices(items, descriptions, names) == []
