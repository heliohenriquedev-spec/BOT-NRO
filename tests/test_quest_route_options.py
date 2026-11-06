"""Ignore options, presence only in combat, @voltar when no way is recorded, manual movement, in-game counter."""
import asyncio
import os
import time
from nrobot import quest_extras
from nrobot.quest_routes import QuestRoutes

OWN = 2000001
FRAME = (b'\xf3\x00\x17\x00'+b'Uadaweu2 : @voltar\0').hex()


def relay_with(tmp_path, route, phase='hunt'):
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_hunt import PacketHunt
    r = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True); r.hunt = PacketHunt(); r.apply_settings({})
    r.upstream = object()
    o = r.tracker.observer; o.player_id = OWN; o.player = [5, 5]; o.player_at = time.monotonic(); o.map_name = route['target_map']
    q = r.quests; q.routes = [route]; q.index = 0; q.phase = phase
    return r, q


def counted_route(**extra):
    return dict(id='R', name='R', target_map='field', species=[1, 2], kills=1, mission_ids=[], steps=[],
                kill_targets=[dict(name='Gremlin', count=2, species=[1]), dict(name='Gorila', count=2, species=[2])], **extra)


def test_ignoring_finished_and_other_monsters_but_not_the_marked_one(tmp_path):
    r, q = relay_with(tmp_path, counted_route(ignore_finished=True, always_attack=[3]))
    assert r.quest_species(q) == [1, 2, 3]
    q.kill_counts = {1: 2}
    assert r.quest_species(q) == [2, 3]  # Gremlin done: left alone
    q.kill_counts = {1: 2, 2: 2}
    assert r.quest_species(q) == []  # all done: the hunt ends even with the marked one around
    r, q = relay_with(tmp_path, counted_route())
    q.kill_counts = {1: 2}
    assert r.quest_species(q) == [1, 2]  # default: finished ones are fought too


def test_monsters_attacking_are_fought_above_the_ignore_limit(tmp_path):
    r, q = relay_with(tmp_path, counted_route(ignore_finished=True))
    now = time.monotonic()
    r.inventory.observe([dict(kind='appearance', entity_id=110000001, species_id=1294, position=[6, 5]),
                         dict(kind='appearance', entity_id=110000002, species_id=1294, position=[4, 5])], now)
    r.hunt.aggressors[110000001] = now
    assert r.quest_species(q) == [1, 2, 1294]  # limit 0: any monster attacking is fought
    r.settings = {**r.settings, 'ignore_attackers': 1}
    assert r.quest_species(q) == [1, 2]  # one attacker, up to 1 ignored
    r.hunt.aggressors[110000002] = now
    assert r.quest_species(q) == [1, 2, 1294]  # two: above the limit, all of them


def test_hunted_monsters_hitting_back_do_not_count_toward_the_ignore_limit(tmp_path):
    r, q = relay_with(tmp_path, counted_route())
    now = time.monotonic()
    r.settings = {**r.settings, 'ignore_attackers': 3}
    r.inventory.observe([dict(kind='appearance', entity_id=110000000+i, species_id=s, position=[5, 5])
                         for i, s in enumerate((1, 1, 1294, 1294))], now)
    for i in range(4):
        r.hunt.aggressors[110000000+i] = now
    assert r.quest_species(q) == [1, 2]  # 2 targets + 2 others: only 2 count, both ignored


def test_players_around_do_not_hold_the_trip_only_the_combat(tmp_path):
    async def scenario():
        r, q = relay_with(tmp_path, counted_route(), phase='travel')
        calls = []
        async def hold():
            calls.append(q.phase); return True
        r.update_presence_hold = hold
        q.steps = []; q.validation = None
        await r.quest_tick(lambda: True)
        assert calls == []  # trip between maps: presence ignored
        q.phase = 'hunt'
        await r.quest_tick(lambda: True)
        assert calls == ['hunt']
    asyncio.run(scenario())


def test_no_recorded_way_back_uses_voltar_then_goes_on(tmp_path):
    q = QuestRoutes(); q.extras = dict(quest_extras.DEFAULTS, voltar_frame=FRAME)  # learned, option off
    q.start([dict(id='R', name='R', target_map='field', species=[1], kills=1, steps=[dict(kind='walk', map='field', position=[1, 1])],
                  lifecycle_enabled=True, pickup_steps=[dict(kind='npc', map='town', position=[1, 1])], pickup_confirmation='ok',
                  delivery_steps=[dict(kind='npc', map='town', position=[1, 1])], delivery_confirmation='ok')], 0)
    q.errands = []; q.phase = 'hunt'; q.finish_hunt(1)
    assert q.phase == 'delivery'
    q.plan('field', [5, 5], None, None, 2)  # no way from the hunting map to town
    assert q.phase == 'delivery' and [e.kind for e in q.errands] == ['voltar']
    q.errands = []
    q.plan('field', [5, 5], None, None, 3)  # same map again (voltar failed): stop, waiting to be moved
    assert q.phase == 'paused' and q.resume
    assert q.resume_after_move('town', 4) and q.phase == 'delivery'  # moved by hand (@voltar): carries on


def test_manual_movement_keeps_combat_and_never_yields_to_clicks(tmp_path):
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_hunt import PacketHunt
    from nrobot.packet_settings import validate
    r = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True); r.hunt = PacketHunt()
    r.apply_settings(validate(dict(manual_movement=True, auto_movement=True, patrol=True)))
    assert not r.hunt.auto_movement and r.hunt.patrol is None
    r.manual_active = False
    assert r.manual_movement and not r.manual_control(time.monotonic())


def test_in_game_counter_shows_done_and_missing_and_can_be_dragged():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from nrobot.game_overlay import QuestCounter, GameOverlay
    app = QApplication.instance() or QApplication([])
    counter = QuestCounter()
    state = {'quests': dict(phase='hunt', quest='Kami 2', kill_progress=[
        dict(name='Gremlin', count=50, done=12, complete=False), dict(name='Gorila', count=10, done=10, complete=True)])}
    counter.update_state(state)
    shadow = GameOverlay(); shadow.update_state(state)
    assert counter.has_content() and not shadow.has_content()  # the counter is no longer drawn by the shadow layer
    assert [text for text, _ in counter.lines()] == ['Gremlin: 12/50 (faltam 38)', 'Gorila: 10/10 ✓ concluido']
    counter.restore_layout({'offset': [400, 30]})
    assert counter.layout_state() == {'offset': [400, 30]}  # where it was dragged to, kept by the panel
    counter.update_state({'quests': dict(phase='idle', kill_progress=[dict(name='Gremlin', count=50, done=1, complete=False)])})
    assert not counter.has_content()


def test_after_the_hunt_voltar_lands_elsewhere_then_mount_then_the_delivery_trip(tmp_path, monkeypatch):
    import struct
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_hunt import PacketHunt
    from nrobot.quest_extras import Body
    monkeypatch.setattr(quest_extras, 'FILE', tmp_path/'extras.json')

    class Upstream:
        def __init__(self): self.sent = []
        def write(self, data): self.sent.append(bytes(data))
        async def drain(self): pass

    async def scenario():
        r = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True); r.hunt = PacketHunt(); r.apply_settings({})
        r.upstream = Upstream(); r.native_frames.buffer = b''; r.own_look = {'name': 'Uadaweu2'}
        o = r.tracker.observer; o.player_id = OWN; o.player = [50, 50]; o.player_at = time.monotonic(); o.map_name = 'field'
        q = r.quests
        q.extras = quest_extras.for_character(dict(quest_extras.DEFAULTS, voltar_enabled=True, voltar_frame=FRAME, mount_enabled=True,
                                                   characters={'Uadaweu2': dict(mount_item=2643)}), 'Uadaweu2')
        q.start([dict(id='R', name='R', target_map='field', species=[1632], kills=1, steps=[dict(kind='walk', map='field', position=[50, 50])],
                      lifecycle_enabled=True, pickup_steps=[dict(kind='npc', map='town', position=[1, 1])], pickup_confirmation='ok',
                      delivery_steps=[dict(kind='npc', map='town', position=[1, 1])], delivery_confirmation='ok')], time.monotonic())
        q.errands = []; q.phase = 'hunt'; q.kills = 1; r.quest_hunt_id = None
        q.body = Body(); q.body.map = 'field'
        q.body.observe([dict(kind='inventory_list', stackable=False, items=[dict(index=38, item_id=2643, type=5, equip_location=0x23, equipped=0)])], OWN, 0)
        tick = lambda: r.quest_tick(lambda: True)

        await tick()  # counters closed: delivery comes after @voltar and the mount
        assert q.phase == 'delivery' and [e.kind for e in q.errands] == ['voltar', 'mount']
        await tick()
        assert r.upstream.sent[-1] == bytes.fromhex(FRAME)  # @voltar typed
        sent = len(r.upstream.sent)
        q.observe([dict(kind='map_change', map='field.gat', position=[10, 10])], OWN, 'field', time.monotonic())
        await tick(); await tick()
        assert q.errands[0].kind == 'voltar' and len(r.upstream.sent) == sent  # same map: not back yet, nothing else sent
        q.observe([dict(kind='map_change', map='town', position=[1, 3])], OWN, 'field', time.monotonic())
        o.map_name = 'town'; o.player = [1, 3]; o.player_at = time.monotonic()
        await tick()  # @voltar confirmed by arriving in another map
        assert [e.kind for e in q.errands] == ['mount']
        await tick()
        assert r.upstream.sent[-1] == struct.pack('<HHH', 0xa9, 38, 0x23)  # mount only after arriving
        q.observe([dict(kind='equipment_ack', index=38, position=0x23, success=True, equipped=True)], OWN, 'town', time.monotonic())
        await tick()
        assert q.errands == [] and q.phase == 'delivery'
        q.actors[110000001] = dict(position=[1, 1], species_id=100)
        await tick()  # only now the delivery trip runs
        assert r.upstream.sent[-1][:2] == b'\x90\x00'
    asyncio.run(scenario())


def test_a_moment_without_position_during_the_hunt_does_not_stop_the_queue(tmp_path):
    async def scenario():
        route = {**counted_route(), 'species': [1632], 'kill_targets': [dict(name='Gremlin', count=50, species=[1632])]}
        r, q = relay_with(tmp_path, route)
        q.progress_at = time.monotonic()-500  # long hunt: no trip progress for minutes
        o = r.tracker.observer
        o.player = None  # own character briefly out of the view
        await r.quest_tick(lambda: True)
        assert q.phase == 'hunt'
        q.position_lost_at = time.monotonic()-31
        await r.quest_tick(lambda: True)
        assert q.phase == 'paused' and '30 s' in q.reason
    asyncio.run(scenario())


def test_quest_hunt_enables_exploration_even_if_normal_patrol_is_off(tmp_path):
    r, q = relay_with(tmp_path, counted_route())
    q.route['species'] = [1037]
    q.route['kill_targets'] = [dict(name='Filhote de cobra', count=2, species=[1037])]
    r.apply_settings({**r.settings, 'patrol': False})
    assert r.hunt.patrol is None
    assert asyncio.run(r.quest_tick(lambda: True)) is False
    assert r.hunt.enabled and r.hunt.patrol is not None
    assert set(r.tracker.observer.species) == {1037}


def test_route_suspends_observation_without_changing_saved_preference(tmp_path):
    from nrobot import watchlist
    watchlist.save(['Observado'])
    watchlist.set_enabled(True)
    r, q = relay_with(tmp_path, counted_route(), phase='travel')
    r.player_names[2000555] = 'Observado'
    r.registry.players[str(2000555)] = {'name': 'Observado'}
    r.presence.observe([dict(kind='appearance', entity_id=2000555, species_id=25,
                           position=[6, 5], option=0)], OWN, time.monotonic(), own_position=[5, 5])
    r.check_emergency()
    r.observe_chat_alerts([dict(kind='chat_received', channel='private', name='Observado')])
    assert not r.commands_blocked and r.chat_alert is None  # trips between maps go on
    assert watchlist.enabled() and watchlist.load() == ['Observado']
    q.phase = 'hunt'
    r.check_emergency()
    assert r.commands_blocked  # patrolling: stops
