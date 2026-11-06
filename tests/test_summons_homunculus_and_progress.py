"""Kills by own summons count for quests, the homunculus is fed at the chosen hunger, saving a
setting never stops the hunt, and the quest progress log keeps only the last 2 hours."""
import asyncio
import math
import struct
import time
from datetime import datetime, timedelta

from nrobot.own_summons import OwnSummons, feed_packet
from nrobot.packet_reader import decode
from nrobot.packet_settings import DEFAULTS, validate
from nrobot.quest_progress_log import QuestProgressLog, describe

OWN = 2000001
SUMMON = 111700001
MONSTER = 111700002


def relay(tmp_path, **settings):
    from nrobot.packet_hunt import PacketHunt
    from nrobot.session_relay import SessionRelay
    r = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    r.hunt = PacketHunt()
    r.apply_settings({**DEFAULTS, 'species': [], **settings})
    o = r.tracker.observer
    o.player_id, o.player, o.player_at, o.map_name = OWN, [10, 10], time.monotonic(), 'field'
    return r


def test_homunculus_packets_are_read():
    status = bytearray(71)
    struct.pack_into('<H', status, 0, 0x22e)
    status[2:7] = b'Lif\0\0'
    struct.pack_into('<HH', status, 27, 12, 23)  # level, hunger
    assert decode(bytes(status)).items() >= {'kind': 'homunculus_status', 'name': 'Lif', 'level': 12, 'hunger': 23}.items()
    state = struct.pack('<HBBII', 0x230, 0, 2, 111700009, 18)
    assert decode(state)['kind'] == 'homunculus_state' and decode(state)['value'] == 18 and decode(state)['state'] == 2
    fed = struct.pack('<HBH', 0x22f, 1, 537)
    assert decode(fed).items() >= {'kind': 'homunculus_fed', 'success': True, 'item_id': 537}.items()


def test_only_what_appears_next_to_me_right_after_my_summon_is_mine():
    own, now = OwnSummons(), 100.0
    own.cast(now)
    own.observe([{'kind': 'appearance', 'entity_id': SUMMON, 'species_id': 1001, 'position': [11, 10]},
                 {'kind': 'appearance', 'entity_id': MONSTER, 'species_id': 1002, 'position': [30, 30]},
                 {'kind': 'appearance', 'entity_id': 2000555, 'species_id': 1, 'position': [10, 11]}], OWN, [10, 10], now+1)
    assert own.allies() == {SUMMON}  # the far monster and the player next to me are not
    own.observe([{'kind': 'appearance', 'entity_id': 111700003, 'species_id': 1001, 'position': [10, 11]}], OWN, [10, 10], now+5)
    assert own.allies() == {SUMMON}  # too late after the summon
    own.observe([{'kind': 'remove', 'entity_id': SUMMON, 'reason': 1}], OWN, [10, 10], now+20)
    assert own.allies() == set()  # it died


def test_a_monster_my_summon_killed_counts_for_the_quest(tmp_path):
    r = relay(tmp_path)
    q = r.quests
    q.routes = [dict(id='R', name='R', target_map='field', species=[1002], kills=1, mission_ids=[], steps=[],
                     kill_targets=[dict(name='Gremlin', count=5, species=[1002])])]
    q.index, q.phase = 0, 'hunt'
    r.own_summons.cast(time.monotonic())
    appear = [{'kind': 'appearance', 'entity_id': SUMMON, 'species_id': 1001, 'position': [11, 10]},
              {'kind': 'appearance', 'entity_id': MONSTER, 'species_id': 1002, 'position': [14, 10]}]
    r.observe_own_summons(appear, time.monotonic())
    q.observe(appear, OWN, 'field', time.monotonic())
    hit = [{'kind': 'normal_attack', 'source_id': SUMMON, 'target_id': MONSTER, 'damage_raw': 900}]
    r.observe_own_summons(hit, time.monotonic())
    q.observe(hit+[{'kind': 'remove', 'entity_id': MONSTER, 'reason': 1}], OWN, 'field', time.monotonic())
    assert q.progress()[0]['done'] == 1
    assert r.inventory.entities.get(SUMMON, {}).get('summoned', True)  # never a hunt target


def test_a_kill_taken_over_by_another_player_does_not_count(tmp_path):
    r = relay(tmp_path)
    q = r.quests
    q.routes = [dict(id='R', name='R', target_map='field', species=[1002], kills=1, mission_ids=[], steps=[],
                     kill_targets=[dict(name='Gremlin', count=5, species=[1002])])]
    q.index, q.phase = 0, 'hunt'
    now = time.monotonic()
    q.observe([{'kind': 'appearance', 'entity_id': MONSTER, 'species_id': 1002, 'position': [14, 10]},
               {'kind': 'normal_attack', 'source_id': OWN, 'target_id': MONSTER, 'damage_raw': 10},
               {'kind': 'normal_attack', 'source_id': 2000777, 'target_id': MONSTER, 'damage_raw': 10},
               {'kind': 'remove', 'entity_id': MONSTER, 'reason': 1}], OWN, 'field', now)
    assert q.progress()[0]['done'] == 0


def test_homunculus_is_fed_at_the_chosen_hunger_with_the_menu_command(tmp_path):
    assert feed_packet() == bytes.fromhex('2d02000001')  # menu command 1 = feed (2 would delete it)
    r = relay(tmp_path, homun_feed=True, homun_hunger=20)
    r.tracker.observer.skills[243] = {'level': 1}

    class Pipe:
        def __init__(self): self.sent = []
        def write(self, data): self.sent.append(bytes(data))
        async def drain(self): pass

    r.upstream = Pipe()
    assert r.native_frames.ready  # nothing half-sent by the client
    r.tracker.observer.player_alive = True
    now = time.monotonic()
    r.observe_own_summons([{'kind': 'homunculus_state', 'state': 2, 'entity_id': 111700009, 'value': 30}], now)
    assert not asyncio.run(r.maintain_homunculus(now))  # 30 is above the chosen 20
    r.observe_own_summons([{'kind': 'homunculus_state', 'state': 2, 'entity_id': 111700009, 'value': 20}], now)
    assert asyncio.run(r.maintain_homunculus(now)) and r.upstream.sent == [bytes.fromhex('2d02000001')]
    assert not asyncio.run(r.maintain_homunculus(now+1))  # waits for the answer
    r.observe_own_summons([{'kind': 'homunculus_state', 'state': 2, 'entity_id': 111700009, 'value': 30},
                           {'kind': 'homunculus_fed', 'success': True, 'item_id': 537}], now+1)
    assert not asyncio.run(r.maintain_homunculus(now+3))
    r.observe_own_summons([{'kind': 'homunculus_state', 'state': 2, 'entity_id': 111700009, 'value': 15},
                           {'kind': 'homunculus_fed', 'success': False, 'item_id': 537}], now+4)
    assert not asyncio.run(r.maintain_homunculus(now+10))  # no food: waits two minutes
    assert asyncio.run(r.maintain_homunculus(now+4+OwnSummons.NO_FOOD_WAIT+1))


def test_feeding_is_off_by_default_and_the_hunger_is_checked():
    assert DEFAULTS['homun_feed'] is False
    assert validate({**DEFAULTS, 'species': [], 'homun_hunger': 40})['homun_hunger'] == 40
    for wrong in (0, 100, 'x'):
        try:
            validate({**DEFAULTS, 'species': [], 'homun_hunger': wrong})
        except ValueError:
            continue
        raise AssertionError(wrong)


def test_the_players_own_feed_is_learned():
    own = OwnSummons()
    assert own.learn_feed(bytes.fromhex('2d02000001')) and own.feed_type == 0
    assert not own.learn_feed(bytes.fromhex('2d02000002'))  # never anything but feeding


def test_saving_a_setting_keeps_the_hunt_running(tmp_path):
    r = relay(tmp_path)
    r.hunt.start()
    r.hunt.pending = {'kind': 'move', 'destination': [1, 1]}
    r.apply_settings({**DEFAULTS, 'species': [], 'pvp_enabled': True, 'pvp_targets': [2000777]})
    assert r.hunt.enabled and r.hunt.pending is None  # PvP checkboxes autosave: the bot goes on
    r.hunt.pause('pausada pelo usuário')
    r.apply_settings({**DEFAULTS, 'species': []})
    assert not r.hunt.enabled and r.hunt.reason == 'pausada pelo usuário'


def test_quest_progress_log_preserves_history_across_midnight_and_restart(tmp_path):
    log = QuestProgressLog(tmp_path/'progresso_quests.log')
    start = datetime(2026, 11, 5, 22, 0, 0)
    snapshot = dict(quest='Kami 2', phase='hunt', mission=None, mission_index=1, reason='',
                    kill_progress=[dict(name='Gremlin', count=50, done=12, complete=False)])
    assert describe(snapshot, 'anthell01.gat') == 'Kami 2 | caçando | Gremlin 12/50 | mapa anthell01'
    assert log.note(describe(snapshot), start)
    assert not log.note(describe(snapshot), start+timedelta(seconds=3))  # unchanged: not written again
    snapshot['kill_progress'][0]['done'] = 13
    log.note(describe(snapshot), start+timedelta(hours=1, minutes=59))  # 23:59, same day: kept
    assert len(log.read()) == 2
    snapshot['kill_progress'][0]['done'] = 14
    log.note(describe(snapshot), start+timedelta(hours=2, minutes=1))
    rows = log.read()
    assert len(rows) == 3 and '14/50' in rows[-1]
    log.prune(start+timedelta(days=1, hours=3))
    assert log.read() == rows
    restarted = QuestProgressLog(log.path)
    assert restarted.read() == rows
    assert restarted.note('Outra sessao', start+timedelta(days=2))
    assert restarted.read()[:-1] == rows


def test_a_summon_created_farther_away_is_mine_and_leaving_the_view_keeps_it():
    own, now = OwnSummons(), 100.0
    own.cast(now)
    own.observe([{'kind': 'appearance', 'entity_id': SUMMON, 'species_id': 1001, 'position': [16, 10], 'spawned': True},
                 {'kind': 'appearance', 'entity_id': MONSTER, 'species_id': 1002, 'position': [16, 12]}], OWN, [10, 10], now+1)
    assert own.allies() == {SUMMON}  # created 6 cells away: mine; one that only walked in that far: not
    own.observe([{'kind': 'move', 'entity_id': SUMMON, 'position': [16, 10], 'destination': [11, 10]}], OWN, [10, 10], now+2)
    assert own.confirmed == {SUMMON}  # it walks to me
    own.observe([{'kind': 'remove', 'entity_id': SUMMON, 'reason': 0}], OWN, [10, 10], now+30)
    own.observe([{'kind': 'appearance', 'entity_id': SUMMON, 'species_id': 1001, 'position': [20, 20]}], OWN, [10, 10], now+40)
    assert SUMMON in own.allies()  # out of view and back: still mine
    own.observe([{'kind': 'remove', 'entity_id': SUMMON, 'reason': 1}], OWN, [10, 10], now+50)
    assert own.allies() == set()


def test_a_creature_that_hits_me_is_not_my_summon():
    own, now = OwnSummons(), 100.0
    own.cast(now)
    own.observe([{'kind': 'appearance', 'entity_id': SUMMON, 'species_id': 1001, 'position': [11, 10], 'spawned': True}], OWN, [10, 10], now)
    own.observe([{'kind': 'normal_attack', 'source_id': SUMMON, 'target_id': OWN, 'damage_raw': 5}], OWN, [10, 10], now+1)
    assert own.allies() == set()


def test_each_counted_kill_says_who_made_it(tmp_path):
    r = relay(tmp_path)
    q = r.quests
    q.routes = [dict(id='R', name='R', target_map='field', species=[1002], kills=1, mission_ids=[], steps=[],
                     kill_targets=[dict(name='Gremlin', count=5, species=[1002])])]
    q.index, q.phase = 0, 'hunt'
    r.own_summons.homunculus = 111700009
    r.observe_own_summons([], time.monotonic())
    q.observe([{'kind': 'appearance', 'entity_id': MONSTER, 'species_id': 1002, 'position': [14, 10]},
               {'kind': 'normal_attack', 'source_id': 111700009, 'target_id': MONSTER, 'damage_raw': 9},
               {'kind': 'remove', 'entity_id': MONSTER, 'reason': 1}], OWN, 'field', time.monotonic())
    assert q.kill_log[0]['by'] == 111700009
    r.flush_quest_kills()
    assert q.kill_log == [] and q.progress()[0]['done'] == 1


def test_a_summon_counts_only_when_its_creature_is_born_and_is_sent_again_otherwise():
    from nrobot.summon_queue import SummonQueue
    q = SummonQueue()
    q.learned[q.key(744, 4)] = {'effect_id': 0, 'creature': True}
    q.reserve({'skill_id': 744, 'level': 4, 'summon_duration': 20}, 10.0)
    q.failed(744, 12.5, False)  # 2.5 s and no creature: it did not go out
    assert q.active is None and q.waiting is None and q.silent_misses == 1
    q.reserve({'skill_id': 744, 'level': 4, 'summon_duration': 20}, 13.0)
    q.creature_created(111700050, 13.8)
    assert q.active and q.active['evidence'] == 'creature_created' and q.silent_misses == 0
    q.creature_gone(111700050, 20.0)  # killed long before its 20 s
    assert q.active is None and q.last_completed == 744


def test_a_new_summon_learns_that_it_creates_a_creature():
    from nrobot.summon_queue import SummonQueue
    q = SummonQueue()
    q.reserve({'skill_id': 745, 'level': 4, 'summon_duration': 20}, 10.0)
    q.failed(745, 12.5, False)  # nothing known yet: assumed out, as before
    assert q.active is not None
    q.creature_created(111700051, 12.6)
    assert q.creates_creature(745, 4) and q.dirty


def test_rotation_waits_for_the_creature_and_retries_quickly(tmp_path):
    from nrobot.combat_rotation import CombatRotation
    r = CombatRotation([{'skill_id': 744, 'enabled': True, 'role': 'summon', 'level': 4, 'interval': 46, 'summon_duration': 20}],
                       response_timeout=.75)
    r.summons.learned[r.summons.key(744, 4)] = {'effect_id': 0, 'creature': True}
    action = {'skill_id': 744, 'level': 4, 'role': 'summon', 'interval': 46, 'target_id': OWN, 'sp_cost': 1, 'summon_duration': 20}
    r.sent(action, 100.0)
    assert r.pending[744]['deadline'] >= 102.5  # waits for the creature, not 0.75 s
    r._fail(744, 102.6, 'sem confirmação')
    assert r.ready[744] <= 103.2 and r.summons.active is None  # not charged the 46 s
    r.sent(action, 103.2)
    r.summon_created(111700052, 104.0)
    assert 744 not in r.pending and r.summons.active['evidence'] == 'creature_created'


def test_group_members_kills_count_too(tmp_path):
    r = relay(tmp_path, group_members=['Pipokinha'])
    r.player_names[2000777] = 'Pipokinha'
    r.player_names[2000888] = 'Estranho'
    q = r.quests
    q.routes = [dict(id='R', name='R', target_map='field', species=[1002], kills=1, mission_ids=[], steps=[],
                     kill_targets=[dict(name='Gremlin', count=5, species=[1002])])]
    q.index, q.phase = 0, 'hunt'
    r.observe_own_summons([], time.monotonic())
    assert q.allies == {2000777}
    q.observe([{'kind': 'appearance', 'entity_id': MONSTER, 'species_id': 1002, 'position': [14, 10]},
               {'kind': 'normal_attack', 'source_id': 2000777, 'target_id': MONSTER, 'damage_raw': 9},
               {'kind': 'remove', 'entity_id': MONSTER, 'reason': 1}], OWN, 'field', time.monotonic())
    r.flush_quest_kills()
    assert q.progress()[0]['done'] == 1


def test_users_copies_cannot_publish_and_get_the_visual_adjustments(tmp_path, monkeypatch):
    from nrobot import updater
    monkeypatch.setattr(updater, 'DEVELOPER', tmp_path/'nao_existe')
    assert not updater.can_publish()
    assert updater.distributed('nrobot/immediate_monster_removal.py')
    assert not updater.distributed('logs/relay/x/saida_relay.log')
    assert not updater.distributed('data/rede/personagens/Boa Hancock.json')
    assert not updater.distributed('perfis/desenvolvedor/x.json')
    import inspect
    from nrobot import session_relay
    assert "'sem_remocao_visual'" in inspect.getsource(session_relay)  # on unless turned off


def resumable(tmp_path):
    from nrobot.quest_routes import QuestRoutes
    route = dict(id='R', name='Kami 2', target_map='anthell01', species=[1002], kills=1, mission_ids=[],
                 steps=[dict(kind='portal', map='town', position=[1, 1]), dict(kind='wait_map', map='anthell01')],
                 kill_targets=[dict(name='Gremlin', count=50, species=[1002])])
    q = QuestRoutes()
    q.start([route], 0)
    q.phase, q.last_stage, q.kill_counts = 'hunt', ('hunt', 0), {1002: 12}
    q.extras = {'mount_enabled': True, 'mount': {'item_id': 1}, 'combat_items': [1]}
    return q, [route], q.progress_state()


def test_resuming_on_the_hunting_map_hunts_at_once_without_mount(tmp_path):
    q, routes, saved = resumable(tmp_path)
    assert saved['stage'] == 'hunt' and saved['target_map'] == 'anthell01'
    q.resume_from(routes, saved, 10.0, map_name='anthell01.gat')
    assert q.phase == 'hunt' and not q.errands and q.progress()[0]['done'] == 12


def test_resuming_elsewhere_travels_by_the_routes(tmp_path):
    q, routes, saved = resumable(tmp_path)
    q.resume_from(routes, saved, 10.0, map_name='town.gat')
    assert q.phase == 'travel' and 'de town' in q.reason


def test_finished_quest_monsters_are_not_brought_back_by_their_names(tmp_path, monkeypatch):
    import nrobot.monster_db as db
    monkeypatch.setattr(db, 'names_for_map', lambda m: {1002: {'Gremlin', 'Gorila'}})
    r = relay(tmp_path)
    q = r.quests
    q.routes = [dict(id='R', name='R', target_map='field', species=[1002], kills=1, mission_ids=[], steps=[], ignore_finished=True,
                     kill_targets=[dict(name='Gremlin', count=2, species=[1002]), dict(name='Gorila', count=2, species=[1002])])]
    q.index, q.phase = 0, 'hunt'
    q.name_counts = {'gremlin': 2}  # Gremlin done, Gorila not: same sprite
    choices = r.quest_name_choices(q)
    assert not any(enabled and 'Gremlin' in key for key, enabled in choices.items())
    assert any(enabled and 'Gorila' in key for key, enabled in choices.items())


def test_an_unreachable_monster_waits_even_with_deferral_off():
    from nrobot.packet_hunt import PacketHunt
    hunt = PacketHunt()
    hunt.TARGET_DEFER = 0
    hunt.target = MONSTER
    hunt.abandon(100.0, 'sem rota livre', defer=hunt.UNREACHABLE_DEFER)
    assert hunt.excluded_until[MONSTER] >= 108.0


def test_arriving_next_to_a_portal_steps_straight_away_first(tmp_path):
    from nrobot.map_navigation import CollisionMap
    r = relay(tmp_path)
    r.hunt.start()
    o = r.tracker.observer
    o.map_name, o.player = 'gl_sew02.gat', [31, 275]
    r.portals.known = {'gl_sew02': {'29,275': 1}}
    r.portals.widened = {'gl_sew02': {'29,275': 2}}
    collision = CollisionMap(300, 300, [1]*90000)
    r.collision_map = lambda: collision
    destination = r.leave_portal_area(0)
    assert destination and max(abs(destination[0]-29), abs(destination[1]-275)) >= 5
    assert destination[0] > 31  # straight away from it, not along its edge


def test_stepping_into_a_portal_by_accident_widens_it_and_is_no_recall(tmp_path):
    r = relay(tmp_path)
    r.hunt.start()
    r.portals.path = tmp_path/'portais.json'
    r.portals.known = {'gl_sew02': {'29,275': 2}}
    r.hunt.pending = {'kind': 'move', 'origin': [34, 275], 'destination': [30, 267]}
    info = dict(from_map='gl_sew02.gat', origin=[30, 267], to_map='prt_sewb4.gat', position=[101, 16])
    assert r.walked_into_portal(info)
    assert r.portals.known['gl_sew02']['29,275'] == 3


def test_visible_homunculus_is_not_vaporized_by_distance_or_destination(tmp_path):
    r = relay(tmp_path)
    r.hunt.start()
    o = r.tracker.observer
    o.player_alive = True
    o.skills = {243: {'level': 1}, 244: {'level': 1}, 247: {'level': 5}}

    class Pipe:
        def __init__(self): self.sent = []
        def write(self, data): self.sent.append(bytes(data))
        async def drain(self): pass

    r.upstream = Pipe()
    r.own_summons.homunculus = 111700009
    r.inventory.entities[111700009] = {'entity_id': 111700009, 'position': [25, 10], 'destination': None,
                                       'present_last_observation': True}
    assert not asyncio.run(r.keep_homunculus_alive(100.0))  # 15 cells away: a moment first
    assert r.hunt.enabled and r.hunt.pending is None  # never stands still waiting for it
    assert not asyncio.run(r.keep_homunculus_alive(104.0))  # still visible, even beyond eight cells
    r.inventory.entities[111700009]['destination'] = [200, 200]
    assert not asyncio.run(r.keep_homunculus_alive(105.0))
    r.observe_own_summons([{'kind': 'remove', 'entity_id': 111700009, 'reason': 0}], 106.0)
    assert not asyncio.run(r.keep_homunculus_alive(106.0))
    assert asyncio.run(r.keep_homunculus_alive(110.0))
    assert struct.pack('<H', 244) in r.upstream.sent[-1] and r.homun_rested_at == 110.0
    assert asyncio.run(r.keep_homunculus_alive(113.5))
    assert struct.pack('<H', 243) in r.upstream.sent[-1] and r.homun_rested_at == 110.0
    assert asyncio.run(r.keep_homunculus_alive(117.0))  # no appearance: retry, not falsely confirmed
    r.observe_own_summons([{'kind': 'appearance', 'entity_id': 111700009, 'position': [11, 10]}], 118.0)
    assert r.homun_rested_at is None and not asyncio.run(r.keep_homunculus_alive(121.0))


def test_homunculus_recovery_uses_removal_even_without_inventory_entry(tmp_path):
    r = relay(tmp_path)
    r.hunt.start()
    r.tracker.observer.skills = {243: {'level': 1}, 244: {'level': 1}}
    class Pipe:
        def __init__(self): self.sent = []
        def write(self, data): self.sent.append(bytes(data))
        async def drain(self): pass
    r.upstream = Pipe()
    r.observe_own_summons([{'kind': 'homunculus_state', 'state': 0, 'entity_id': 111700009},
                           {'kind': 'remove', 'entity_id': 111700009, 'reason': 0}], 10)
    assert not r.inventory.entities
    assert not asyncio.run(r.keep_homunculus_alive(10))
    assert asyncio.run(r.keep_homunculus_alive(14))
    assert asyncio.run(r.keep_homunculus_alive(18))
    assert asyncio.run(r.keep_homunculus_alive(22))
    assert asyncio.run(r.keep_homunculus_alive(26))
    assert not asyncio.run(r.keep_homunculus_alive(30))  # bounded retries; normal hunting remains enabled
    assert r.hunt.enabled and r.hunt.pending is None


def test_homunculus_rules_require_learned_skills_and_respect_server_cooldown(tmp_path):
    r = relay(tmp_path)
    r.hunt.start()
    r.own_summons.homunculus = 111700009
    r.own_summons.dead = True
    class Pipe:
        def __init__(self): self.sent = []
        def write(self, data): self.sent.append(bytes(data))
        async def drain(self): pass
    r.upstream = Pipe()
    assert not asyncio.run(r.keep_homunculus_alive(10))
    r.tracker.observer.skills = {247: {'level': 1}}
    r.tracker.observer.skill_cooldowns[247] = 30
    assert not asyncio.run(r.keep_homunculus_alive(20)) and not r.upstream.sent
    assert asyncio.run(r.keep_homunculus_alive(31))


def test_homunculus_attacking_nonquest_monster_does_not_change_character_target(tmp_path):
    r = relay(tmp_path)
    r.hunt.start()
    r.hunt.target = MONSTER
    r.own_summons.homunculus = SUMMON
    r.observe_own_summons([{'kind': 'normal_attack', 'source_id': SUMMON,
                           'target_id': 111700099, 'damage_raw': 100}], 10)
    assert r.hunt.target == MONSTER and r.hunt.enabled and r.hunt.pending is None


def test_showmobs_marks_lead_to_the_densest_group_from_time_to_time():
    from nrobot.mob_scan import MobScan
    mark = struct.pack('<HIIIIBI', 0x144, 111256000, 1, 40, 50, 1, 0xff0000)
    assert decode(mark)['kind'] == 'viewpoint' and decode(mark)['position'] == [40, 50]
    scan = MobScan()
    assert scan.start('field', [1002, 1003], 0.0, idle=True)
    assert scan.next_command(0.0) == 1002
    scan.sent(1002, 0.0)
    assert scan.next_command(1.0) is None  # 4 s between commands
    scan.observe([{'kind': 'viewpoint', 'mark_type': 1, 'position': p} for p in ([40, 50], [42, 51], [45, 48], [150, 10])], .5)
    scan.sent(scan.next_command(4.0), 4.0)
    scan.observe([{'kind': 'viewpoint', 'mark_type': 1, 'position': [41, 47]}], 4.5)
    assert scan.finish([100, 100], 5.0) is None  # still listening
    found = scan.finish([100, 100], 8.0)
    assert found['monsters'] == 4 and math.dist(found['position'], (42, 49)) <= 3
    assert not scan.start('field', [1002], 30.0, idle=True)  # once a minute
    assert scan.start('field', [1002], 70.0, idle=True)  # a minute later, fighting or not
    assert scan.current_goal([42, 50], 71.0) is None  # arrived


def test_showmobs_asks_only_for_the_monsters_still_missing(tmp_path):
    r = relay(tmp_path)
    q = r.quests
    q.routes = [dict(id='R', name='R', target_map='field', species=[1002, 1003], kills=1, mission_ids=[], steps=[],
                     kill_targets=[dict(name='Gremlin', count=2, species=[1002]), dict(name='Gorila', count=2, species=[1003])])]
    q.index, q.phase = 0, 'hunt'
    q.kill_counts = {1002: 2}
    assert r.quest_missing_species() == [1003]


def test_a_far_showmobs_spot_is_walked_to_and_then_the_patrol_goes_on():
    from nrobot.map_navigation import CollisionMap
    from nrobot.packet_patrol import PacketPatrol
    collision = CollisionMap(120, 120, [1]*14400)
    patrol = PacketPatrol(8)
    position, now = [5, 5], 0.0
    patrol.plan(position, now, 150, collision)
    patrol.focus = [110, 110]
    for _ in range(80):
        action = patrol.plan(position, now, 150, collision)
        now += 1
        if action is None:
            continue
        patrol.reached(action['destination'], position)
        position = action['destination']
        if patrol.focus_reached:
            break
    assert patrol.focus_reached and math.dist(position, (110, 110)) <= 12  # got there, never stood still
    assert patrol.focus is None and patrol.plan(position, now+1, 150, collision) is not None  # patrols on


def test_a_recorded_detour_out_of_the_map_and_back_is_skipped_when_walkable(tmp_path):
    from nrobot.map_navigation import CollisionMap
    from nrobot.portals import PortalGuard
    from nrobot.quest_routes import QuestRoutes
    q = QuestRoutes()
    q.routes, q.index, q.validation, q.phase = [{'target_map': 'alde_dun02.gat', 'name': 'x'}], 0, None, 'travel'
    q.steps = [dict(kind='portal', map='alde_dun02.gat', position=[50, 50]), dict(kind='wait_map', map='gl_prison.gat'),
               dict(kind='portal', map='gl_prison.gat', position=[10, 10]), dict(kind='wait_map', map='alde_dun02.gat'),
               dict(kind='walk', map='alde_dun02.gat', position=[53, 50])]
    q.step = 0
    q.skip_detour('alde_dun02.gat', (10, 10), CollisionMap(80, 80, [1]*6400), PortalGuard(tmp_path/'p.json'))
    assert q.step == 4  # straight to the walk after the return: no gl_prison
    walls = [1]*6400
    for y in range(80):
        walls[y*80+30] = 0  # this side cannot walk to the point: the detour is the way
    q.step, q.path_cache = 0, None
    q.skip_detour('alde_dun02.gat', (10, 10), CollisionMap(80, 80, walls), PortalGuard(tmp_path/'p.json'))
    assert q.step == 0


def test_the_walked_trail_and_coverage_start_over_on_leaving_and_every_30_minutes(tmp_path):
    from nrobot.map_navigation import CollisionMap
    from nrobot.packet_patrol import PacketPatrol
    r = relay(tmp_path)
    o = r.tracker.observer
    o.map_name, o.player = 'a.gat', [5, 5]
    r.record_trail(0); o.player = [9, 5]; r.record_trail(1)
    assert len(r.trails['a.gat']) == 2
    o.map_name = 'b.gat'; r.record_trail(2)
    assert 'a.gat' not in r.trails  # left: gone
    o.player = [20, 20]; r.record_trail(2+r.TRAIL_KEEP)
    assert r.trails['b.gat'] == [[20, 20]]  # 30 minutes: started over
    first, second = CollisionMap(40, 40, [1]*1600), CollisionMap(40, 40, [1]*1600)
    first.name, second.name = 'a.gat', 'b.gat'
    patrol = PacketPatrol(8)
    patrol.plan([5, 5], 0, 150, first)
    done = set(patrol.done)
    patrol.plan([5, 5], 1, 150, second)
    patrol.plan([5, 5], 2, 150, first)  # back on a: from scratch
    assert patrol.cycle_number == 1 and patrol.map_memory.get(id(first)) is None
    patrol.plan([5, 5], 3+patrol.CYCLE_KEEP, 150, first)
    assert patrol.cycle_number == 2  # 30 minutes on the same map: new cycle


def test_marionette_is_brought_back_when_dead_or_left_out_of_the_screen(tmp_path):
    r = relay(tmp_path)
    r.hunt.start()

    class Pipe:
        def __init__(self): self.sent = []
        def write(self, data): self.sent.append(bytes(data))
        async def drain(self): pass

    r.upstream = Pipe()
    o = r.tracker.observer
    o.player_alive = True
    o.skills = {243: {'level': 1}, 244: {'level': 1}, 247: {'level': 5}}
    r.own_summons.homunculus = 111700009
    r.observe_own_summons([{'kind': 'remove', 'entity_id': 111700009, 'reason': 1}], 0)
    assert r.own_summons.dead
    assert asyncio.run(r.keep_homunculus_alive(10.0))
    sent = r.upstream.sent[-1]  # Remontar Marionete (247, level 5) on the character
    assert struct.pack('<H', 247) in sent and struct.pack('<I', OWN) in sent
    r.observe_own_summons([{'kind': 'appearance', 'entity_id': 111700009, 'position': [11, 10]}], 11.0)
    assert not r.own_summons.dead
    r.inventory.entities[111700009] = {'entity_id': 111700009, 'position': [40, 40], 'present_last_observation': False}
    r.observe_own_summons([{'kind': 'remove', 'entity_id': 111700009, 'reason': 0}], 20.0)
    assert not asyncio.run(r.keep_homunculus_alive(20.0))  # just left the screen: a moment
    assert asyncio.run(r.keep_homunculus_alive(24.0)) and r.homun_rested_at == 24.0  # put away
    assert asyncio.run(r.keep_homunculus_alive(27.5)) and r.homun_rested_at == 24.0
    r.observe_own_summons([{'kind': 'appearance', 'entity_id': 111700009, 'position': [11, 10]}], 28.0)
    assert r.homun_rested_at is None


def test_strong_monsters_with_priority_are_finished_first(tmp_path):
    from nrobot.packet_hunt import PacketHunt
    from nrobot.quest_routes import validate_routes
    route = validate_routes([dict(id='R', name='R', target_map='field', species=[1002], kills=1, mission_ids=[], steps=[],
                                  always_attack=[1009, 1010], attack_priority={'1010': 1, '1009': 2, '7': 1})])[0]
    assert route['attack_priority'] == {'1010': 1, '1009': 2}  # only marked monsters keep a number
    try:
        validate_routes([dict(route, attack_priority={'1010': 0})])
        raise AssertionError('0 accepted')
    except ValueError:
        pass
    hunt = PacketHunt()
    hunt.auto_movement = False
    hunt.start()
    hunt.target_priority = {1010: 1, 1009: 2}
    state = {'state': 'tracking', 'player_position_recent': True, 'player_position': [10, 10], 'recent_entities': [
        {'entity_id': 1, 'species_id': 1002, 'kind': 'monster', 'position': [11, 10], 'position_age_seconds': .1},
        {'entity_id': 2, 'species_id': 1009, 'kind': 'monster', 'position': [15, 10], 'position_age_seconds': .1},
        {'entity_id': 3, 'species_id': 1010, 'kind': 'monster', 'position': [18, 10], 'position_age_seconds': .1}]}
    hunt.plan(state, 0)
    assert hunt.target == 3  # the strongest one first, though the farthest


def test_route_editor_saves_the_priority_column(tmp_path, monkeypatch):
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    app = QApplication.instance() or QApplication([])
    import nrobot.monster_db as db
    from nrobot.quest_monster_index import QuestMonsterIndex
    monkeypatch.setattr(QuestMonsterIndex, 'species', lambda self,name: {1009,1010})
    from nrobot.quest_panel import RouteEditor
    editor = RouteEditor(dict(name='Rota', mission_ids=[], steps=[], species=[], kills=1, always_attack=[1010],
                              attack_priority={'1010': 3}), {})
    rows = {editor.always.item(i, 0).data(Qt.UserRole): i for i in range(editor.always.rowCount())}
    assert editor.always.cellWidget(rows[1010], 1).value() == 3
    editor.always.item(rows[1009], 0).setCheckState(Qt.Checked)
    editor.always.cellWidget(rows[1009], 1).setValue(1)
    assert editor.always_attack() == [1009, 1010] and editor.attack_priority() == {1009: 1, 1010: 3}
    editor.close()


def test_showmobs_runs_early_without_a_target_but_not_near_the_scheduled_scan():
    from nrobot.mob_scan import MobScan
    scan = MobScan()
    assert scan.start('field', [1002], 0.0, idle=True)  # the on-arrival scan sets the 60 s clock
    scan.queue.clear(); scan.round_open = False
    assert not scan.start('field', [1002], 10.0, idle=True)  # 10 s later: the regular scan is not due
    assert not scan.start('field', [1002], 46.0, idle=True, early=True)  # 14 s before the 60 s scan: wait for it
    assert scan.start('field', [1002], 44.0, idle=True, early=True)  # 16 s before it: early scan runs now
