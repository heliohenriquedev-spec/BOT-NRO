import json
from pathlib import Path

from nrobot.packet_hunt import PacketHunt
from nrobot.map_navigation import CollisionMap
from test_packet_hunt import state, walled_map
from test_map_combat_focus import relay_for, add_monster


def config():
    return json.loads(Path('exemplos/comportamentos/ra_fild03.json').read_text(encoding='utf-8'))['combat']


def test_wall_exclusion_ends_as_soon_as_monster_is_on_our_side():
    hunt = PacketHunt(); hunt.start()
    collision = walled_map()
    hunt.plan(state([15, 5], [(101, [25, 5])]), 0, collision=collision)
    hunt.excluded_until[101] = 8
    # Same ID comes around to this side before the wall cache/deferral expires.
    action = hunt.plan(state([15, 5], [(101, [16, 5])]), .1, collision=collision)
    assert action and action['kind'] == 'attack' and action['target_id'] == 101
    assert 101 not in hunt.excluded_until and not hunt.walled(101, .1)


def test_wall_budget_does_not_hide_later_clear_line_monster():
    hunt = PacketHunt(); hunt.start()
    rows = state([15, 5], [(i, [25, 5]) for i in range(10, 17)]+[(30, [16, 5])])['recent_entities']
    assert [e['entity_id'] for e in hunt.reachable_targets(rows, walled_map(), [15, 5], 0)] == [30]


def test_walled_control_target_does_not_block_nearby_ninkame(tmp_path):
    relay, now = relay_for(tmp_path, config())
    collision = CollisionMap(60, 60, [int(x != 22) for y in range(60) for x in range(60)])
    relay.collision_map = lambda: collision
    add_monster(relay, 110000001, 1634, [24, 20], now)
    add_monster(relay, 110000002, 1315, [21, 20], now)
    intent = relay.map_combat_intent(relay.map_combat, relay.status(), now)
    assert intent['mode'] == 'kill' and intent['target_id'] == 110000002


def test_old_damage_and_pending_attack_do_not_override_map_pick(tmp_path):
    relay, now = relay_for(tmp_path, config())
    add_monster(relay, 110000001, 1315, [21, 20], now)
    add_monster(relay, 110000002, 1177, [24, 20], now)
    relay.hunt.target = 110000001
    relay.hunt.engaged = 110000002
    relay.hunt.engaged_until = now+15
    relay.hunt.pending = dict(kind='attack', target_id=110000002, deadline=now+1)
    action = relay.plan_group_or_hunt(relay.status(), now, 150, relay.collision_map())
    assert action and action['kind'] == 'attack' and action['target_id'] == 110000001
    assert relay.hunt.engaged == 110000001


def test_wall_cache_is_discarded_after_portal():
    hunt = PacketHunt(); hunt.start()
    hunt.wall_checks[101] = (100, (20, 20), (25, 20), True)
    hunt.map_transition()
    assert not hunt.wall_checks
