"""Monsters in enemy skill areas on the floor, and many failed skills on one target."""
import time
from types import SimpleNamespace

from nrobot.map_navigation import CollisionMap
from nrobot.packet_hunt import PacketHunt
from nrobot.session_relay import SessionRelay


def state(player, entities):
    return {'state': 'tracking', 'player_position_recent': True, 'player_position': player,
            'recent_entities': [{'entity_id': i, 'position': pos} for i, pos in entities]}


def poisoned(cells):
    collision = CollisionMap(40, 40, [1]*1600)
    collision.hazard_cells = frozenset(cells)
    collision.set_forbidden(cells)
    return collision


def cross(x, y):
    return {(x, y), (x-1, y), (x+1, y), (x, y-1), (x, y+1)}


def test_monster_standing_in_poison_is_fought_from_the_cell_next_to_it():
    collision = poisoned(cross(20, 20))
    path = collision.route((10, 20), (20, 20), max_nodes=8000)
    assert path and path[-1] not in collision.hazard_cells
    assert max(abs(path[-1][i]-(20, 20)[i]) for i in (0, 1)) == 1
    assert collision.route((10, 20), (20, 20), exact=True) is None  # never steps into it


def test_final_skill_send_allows_ground_hazards_but_keeps_real_walls(tmp_path):
    import asyncio
    from nrobot.packet_settings import DEFAULTS
    from nrobot.network_targets import Entity
    async def scenario(wall):
        relay=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
        relay.hunt=PacketHunt()
        profile=dict(skill_id=525,role='offensive',enabled=True,level=10,interval=.5,effect_id=0)
        relay.apply_settings(dict(DEFAULTS,species=[1037],auto_map_targets=False,skill_profiles=[profile]))
        relay.hunt.start();relay.hunt.target=20
        now=time.monotonic();o=relay.tracker.observer
        o.player_id=1;o.player=[10,20];o.player_at=now;o.sp=100
        o.skills[525]=dict(skill_id=525,level=10,sp_cost=1,range=6,target_flags=1)
        o.registry.update(Entity(20,1037,14,20,now,'monster'))
        cells=[1]*1600
        if wall:cells[20*40+12]=0
        collision=CollisionMap(40,40,cells)
        collision.hazard_cells=frozenset({(14,20)})
        collision.set_forbidden(collision.hazard_cells)
        relay.collision_map=lambda:collision
        class Writer:
            def __init__(self):self.packets=[]
            def write(self,data):self.packets.append(data)
            async def drain(self):pass
        relay.upstream=Writer()
        action=relay.rotation.plan(relay.status(),now,20)
        assert action is not None
        sent=await relay.send_rotation_action(action,game_gate=lambda:True)
        assert sent is (not wall) and bool(relay.upstream.packets) is (not wall)
        assert not collision.walkable((14,20))  # walking still avoids the hazard
    asyncio.run(scenario(False))
    asyncio.run(scenario(True))


def test_monster_cut_off_by_poison_is_reached_across_the_area():
    # Searching other monsters and partial paths every tick left the character standing still,
    # hit, for seconds (yuno_fild07 2026-11-09): with no way around, it walks across.
    ring = {(x, y) for x in range(16, 25) for y in range(16, 25)} - {(20, 20)}
    collision = poisoned(ring)
    hunt = PacketHunt()
    hunt.start()
    seen = state([14, 14], [(1, [20, 20]), (2, [6, 10])])
    hunt.target = 1
    action = hunt.plan(seen, 100, collision=collision)
    assert hunt.target == 1 and action['kind'] == 'move' and action.get('cross_hazards')
    assert tuple(action['destination']) in ring  # into the area, toward the monster
    assert hunt.hazard_crossing_until > 100


def test_alone_in_poison_the_character_gets_as_close_as_the_area_allows():
    ring = {(x, y) for x in range(16, 25) for y in range(16, 25)} - {(20, 20)}
    collision = poisoned(ring)
    hunt = PacketHunt()
    hunt.start()
    action = hunt.plan(state([10, 10], [(1, [20, 20])]), 100, collision=collision)
    assert action is not None and action['kind'] == 'move' and action['target_id'] == 1
    assert tuple(action['destination']) not in ring


def relay_with_target(target, others):
    relay = SimpleNamespace(hunt=PacketHunt(), skill_fail_track=None, events=[], manual_active=False, manual_until=0,
                            active_map_combat=lambda: None)
    relay.hunt.target = target
    relay.record_hunt = lambda event: relay.events.append(event)
    for name in ('SKILL_FAIL_WINDOW', 'SKILL_FAIL_SENDS', 'SKILL_FAIL_GAP', 'SKILL_FAIL_RETURN'):
        setattr(relay, name, getattr(SessionRelay, name))
    entities = [(target, [11, 10])]+[(i, [12+i, 10]) for i in others]
    return relay, state([10, 10], entities)


def test_many_offensive_skills_without_a_hit_switch_target_and_come_back_in_one_second():
    relay, seen = relay_with_target(7, [8])
    for _ in range(8):
        SessionRelay.note_skill_result(relay, {'kind': 'rotation_skill_sent', 'role': 'offensive', 'target_id': 7})
    relay.skill_fail_track[1] -= 2.5  # 2.5 s of skills in a row without any confirmation
    now = time.monotonic()
    assert SessionRelay.skill_failure_switch(relay, seen, now)
    assert relay.hunt.target is None and abs(relay.hunt.excluded_until[7]-(now+1)) < 1e-6
    assert relay.events[-1]['kind'] == 'target_switched_skill_failures'


def test_a_confirmed_hit_or_no_other_monster_keeps_the_target():
    relay, seen = relay_with_target(7, [8])
    for _ in range(8):
        SessionRelay.note_skill_result(relay, {'kind': 'rotation_skill_sent', 'role': 'offensive', 'target_id': 7})
    SessionRelay.note_skill_result(relay, {'kind': 'attack_confirmed', 'target_id': 7})
    assert not SessionRelay.skill_failure_switch(relay, seen, time.monotonic()+2)
    alone, seen = relay_with_target(7, [])
    for _ in range(8):
        SessionRelay.note_skill_result(alone, {'kind': 'rotation_skill_sent', 'role': 'offensive', 'target_id': 7})
    alone.skill_fail_track[1] -= 2.5
    assert not SessionRelay.skill_failure_switch(alone, seen, time.monotonic())
    assert alone.hunt.target == 7


def test_double_attack_is_drawn_as_one_hit_with_the_same_damage():
    import struct
    from nrobot.immediate_monster_removal import ImmediateMonsterRemoval
    removal = ImmediateMonsterRemoval(None, lambda identity: False)
    removal.started = True
    double = struct.pack('<HIIIiiHhBH', 0x8a, 2003137, 111935700, 0, 300, 500, 65535, 2, 8, 0)
    single = struct.pack('<HIIIiiHhBH', 0x8a, 2003137, 111935700, 0, 300, 500, 65535, 1, 0, 0)
    out = removal.feed(double+single)
    assert len(out) == 58
    first = struct.unpack('<HIIIiiHhBH', out[:29])
    assert first[6] == 65535 and first[7] == 1 and first[8] == 0 and first[5] == 60
    assert out[29:] == single  # a normal hit is left alone


def test_slow_cast_skill_waits_while_basic_attacks_can_land():
    relay = SimpleNamespace(settings={'auto_attacks': True}, SLOW_CAST=.3,
                            tracker=SimpleNamespace(observer=SimpleNamespace(cast_times={62: 1.2, 523: 0})),
                            active_map_combat=lambda: object(), map_damage_allowed=lambda *a, **k: True)
    attack = {'kind': 'attack', 'target_id': 5}
    kick = {'role': 'offensive', 'skill_id': 62, 'target_id': 5}
    throw = {'role': 'offensive', 'skill_id': 523, 'target_id': 5}
    assert SessionRelay.prefer_basic_attack(relay, kick, attack, {}, 0) is None
    assert SessionRelay.prefer_basic_attack(relay, throw, attack, {}, 0) is throw  # instant: still in the burst
    assert SessionRelay.prefer_basic_attack(relay, kick, None, {}, 0) is kick  # cannot hit: the skill goes
    relay.active_map_combat = lambda: None
    assert SessionRelay.prefer_basic_attack(relay, kick, attack, {}, 0) is kick  # only in the map behavior


def test_monsters_all_beyond_the_poison_do_not_make_it_hop_between_them():
    wall = {(15, y) for y in range(40)}  # a strip of poison across the whole map
    collision = poisoned(wall)
    hunt = PacketHunt()
    hunt.start()
    seen = state([10, 10], [(1, [20, 10]), (2, [20, 14])])
    hunt.target = 1
    action = hunt.plan(seen, 100, collision=collision)
    assert hunt.target == 1 and 1 not in hunt.excluded_until  # nobody else reachable: no switch
    assert action is not None and action['kind'] == 'move' and action['destination'][0] < 15


def test_manual_pause_or_control_skills_never_trigger_the_switch():
    relay, seen = relay_with_target(7, [8])
    relay.active_map_combat = lambda: SimpleNamespace(control_skill_ids={76, 179, 182})
    for _ in range(8):
        SessionRelay.note_skill_result(relay, {'kind': 'rotation_skill_sent', 'role': 'offensive', 'target_id': 7, 'skill_id': 76})
    assert relay.skill_fail_track is None  # silence retries are control, not damage
    for _ in range(8):
        SessionRelay.note_skill_result(relay, {'kind': 'rotation_skill_sent', 'role': 'offensive', 'target_id': 7, 'skill_id': 524})
    relay.skill_fail_track[1] -= 2.5
    relay.skill_fail_track[3] -= 3  # the last send was 3 s ago (player moving by hand): starts over
    assert not SessionRelay.skill_failure_switch(relay, seen, time.monotonic())


def test_cornered_inside_clouds_walks_over_them_instead_of_standing_still():
    from nrobot.toxic_ground import ToxicGround
    collision = CollisionMap(40, 40, [1]*1600)
    # clouds side by side: every way out crosses another one after a free cell
    clouds = {(x, y) for x in range(10, 31) for y in range(10, 31)} - {(19, 20), (21, 20)}
    ground = ToxicGround()
    ground.cells = lambda now, **k: frozenset(clouds)
    destination = ground.escape(collision, (20, 20), set(), 0)
    assert destination is not None and destination != (20, 20)


def test_boxed_in_by_skill_areas_lets_routes_cross_them():
    collision = CollisionMap(40, 40, [1]*1600)
    ring = {(x, y) for x in range(14, 27) for y in range(14, 27)} - {(x, y) for x in range(18, 23) for y in range(18, 23)}
    relay = SimpleNamespace(cornered_cache=None, CORNERED_CELLS=40,
                            portals=SimpleNamespace(cells=lambda name: []),
                            tracker=SimpleNamespace(observer=SimpleNamespace(map_name='m')))
    assert SessionRelay.cornered(relay, collision, (20, 20), frozenset(ring))  # 25 free cells, closed in
    open_field = {(x, 20) for x in range(14, 27)}
    relay.cornered_cache = None
    assert not SessionRelay.cornered(relay, collision, (20, 25), frozenset(open_field))


def test_monster_on_a_skill_area_not_reached_in_one_second_gives_way_and_comes_back_soon():
    ring = {(x, y) for x in range(16, 25) for y in range(16, 25)} - {(20, 20)}
    collision = poisoned(ring)
    hunt = PacketHunt()
    hunt.start()
    seen = state([14, 14], [(1, [20, 20]), (2, [6, 10])])
    hunt.target = 1
    assert hunt.plan(seen, 100, collision=collision)['kind'] == 'move'  # first second: goes for it
    hunt.pending = None; hunt.ready_at = 0
    assert hunt.plan(seen, 100.5, collision=collision)['kind'] == 'move'
    hunt.pending = None; hunt.ready_at = 0
    hunt.plan(seen, 101.2, collision=collision)  # not there after 1 s: another one meanwhile
    assert hunt.target != 1 and hunt.excluded_until[1] == 104.2  # back to it 3 s later


def test_alone_on_a_skill_area_the_monster_is_not_given_up():
    ring = {(x, y) for x in range(16, 25) for y in range(16, 25)} - {(20, 20)}
    collision = poisoned(ring)
    hunt = PacketHunt()
    hunt.start()
    seen = state([14, 14], [(1, [20, 20])])
    hunt.target = 1
    hunt.plan(seen, 100, collision=collision)
    hunt.pending = None; hunt.ready_at = 0
    assert hunt.plan(seen, 102, collision=collision)['kind'] == 'move' and hunt.target == 1


def test_basic_attacks_go_on_during_the_coelho_seals():
    from nrobot.map_navigation import CollisionMap as Map
    stub = SimpleNamespace(hunt=PacketHunt())
    stub.hunt.start()
    seen = dict(state([10, 10], [(1, [11, 10]), (2, [15, 10])]), player_sp=100,
                learned_skills=[dict(skill_id=524, level=20, range=6, sp_cost=1)])
    seen['recent_entities'] = [dict(e, position_age_seconds=.1) for e in seen['recent_entities']]
    collision = Map(30, 30, bytes([1])*900)
    act = SessionRelay.area_sleep_basic_attack(stub, dict(mode='area_sleep', target_id=1), seen, 100, 150, collision)
    assert act == dict(kind='attack', target_id=1)
    far = SessionRelay.area_sleep_basic_attack(stub, dict(mode='area_sleep', target_id=2), seen, 101, 150, collision)
    assert far is None  # not next to it: no walking during the seals
