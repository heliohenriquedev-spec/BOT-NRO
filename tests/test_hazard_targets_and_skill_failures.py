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


def test_monster_cut_off_by_poison_gives_way_to_another_close_by_for_one_second():
    ring = {(x, y) for x in range(16, 25) for y in range(16, 25)} - {(20, 20)}
    collision = poisoned(ring)
    hunt = PacketHunt()
    hunt.start()
    hunt.TARGET_DEFER = 2
    seen = state([10, 10], [(1, [20, 20]), (2, [6, 10])])
    hunt.target = 1
    hunt.plan(seen, 100, collision=collision)
    assert hunt.target != 1
    assert hunt.excluded_until[1] == 101  # back to it a second later


def test_alone_in_poison_the_character_gets_as_close_as_the_area_allows():
    ring = {(x, y) for x in range(16, 25) for y in range(16, 25)} - {(20, 20)}
    collision = poisoned(ring)
    hunt = PacketHunt()
    hunt.start()
    action = hunt.plan(state([10, 10], [(1, [20, 20])]), 100, collision=collision)
    assert action is not None and action['kind'] == 'move' and action['target_id'] == 1
    assert tuple(action['destination']) not in ring


def relay_with_target(target, others):
    relay = SimpleNamespace(hunt=PacketHunt(), skill_fail_track=None, events=[])
    relay.hunt.target = target
    relay.record_hunt = lambda event: relay.events.append(event)
    relay.SKILL_FAIL_WINDOW, relay.SKILL_FAIL_SENDS, relay.SKILL_FAIL_RETURN = 1.5, 3, 1.0
    entities = [(target, [11, 10])]+[(i, [12+i, 10]) for i in others]
    return relay, state([10, 10], entities)


def test_many_offensive_skills_without_a_hit_switch_target_and_come_back_in_one_second():
    relay, seen = relay_with_target(7, [8])
    for _ in range(4):
        SessionRelay.note_skill_result(relay, {'kind': 'rotation_skill_sent', 'role': 'offensive', 'target_id': 7})
    relay.skill_fail_track[1] -= 2  # two seconds of skills without any confirmation
    now = time.monotonic()
    assert SessionRelay.skill_failure_switch(relay, seen, now)
    assert relay.hunt.target is None and abs(relay.hunt.excluded_until[7]-(now+1)) < 1e-6
    assert relay.events[-1]['kind'] == 'target_switched_skill_failures'


def test_a_confirmed_hit_or_no_other_monster_keeps_the_target():
    relay, seen = relay_with_target(7, [8])
    for _ in range(4):
        SessionRelay.note_skill_result(relay, {'kind': 'rotation_skill_sent', 'role': 'offensive', 'target_id': 7})
    SessionRelay.note_skill_result(relay, {'kind': 'attack_confirmed', 'target_id': 7})
    assert not SessionRelay.skill_failure_switch(relay, seen, time.monotonic()+2)
    alone, seen = relay_with_target(7, [])
    for _ in range(4):
        SessionRelay.note_skill_result(alone, {'kind': 'rotation_skill_sent', 'role': 'offensive', 'target_id': 7})
    alone.skill_fail_track[1] -= 2
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
