import asyncio
import struct
import time

import pytest

from nrobot.packet_hunt import PacketHunt
from nrobot.network_targets import Entity
from nrobot.session_relay import SessionRelay


def state(player, entities):
    return {'state': 'tracking', 'player_position_recent': True, 'player_position': player,
            'recent_entities': [{'entity_id': i, 'position': pos} for i, pos in entities]}


def test_hunt_keeps_moving_target_and_waits_for_each_confirmation():
    hunt = PacketHunt()
    initial = state([0, 0], [(20, [8, 0]), (21, [12, 0])])
    assert hunt.plan(initial, 0) is None
    hunt.start()
    action = hunt.plan(initial, 0)
    assert action['kind'] == 'move' and action['target_id'] == 20
    assert action['destination'] == [4, 0]
    hunt.sent(action, 0)
    assert hunt.plan(initial, .1) is None
    hunt.observe([{'kind': 'player_move', 'destination': action['destination']}], 1, .2)
    moved = state([4, 0], [(20, [9, 1]), (21, [14, 1])])
    action = hunt.plan(moved, 4)
    assert action['target_id'] == 20  # entity 20 remains nearest
    hunt.sent(action, 4)
    hunt.observe([{'kind': 'position', 'entity_id': 1, 'position': action['destination']}], 1, 4.1)
    close = state([8, 1], [(20, [9, 1]), (21, [4, 1])])
    action = hunt.plan(close, 8)
    assert action == {'kind': 'attack', 'target_id': 20}
    hunt.sent(action, 8)
    assert hunt.plan(close, 8.5) is None
    hunt.observe([{'kind': 'normal_attack', 'source_id': 99, 'target_id': 20}], 1, 8.6)
    assert hunt.pending
    hunt.observe([{'kind': 'normal_attack', 'source_id': 1, 'target_id': 20}], 1, 8.7)
    assert hunt.confirmed_attacks == 1 and hunt.pending is None
    next_target = state([8, 1], [(21, [8, 2])])
    assert hunt.plan(next_target, 9.6) == {'kind': 'attack', 'target_id': 21}


def test_missing_response_retries_same_target_without_stopping_hunt():
    hunt = PacketHunt()
    hunt.start()
    initial = state([0, 0], [(20, [8, 0])])
    action = hunt.plan(initial, 0)
    hunt.sent(action, 0)
    assert hunt.plan(initial, 10) is None
    assert hunt.enabled and 'movimento' in hunt.reason
    assert hunt.plan(initial, 10.1) is None
    hunt.start()
    close = state([0, 0], [(20, [1, 0])])
    hunt.sent(hunt.plan(close, 0), 0)
    assert hunt.plan(close, 5) is None
    assert hunt.enabled and 'resposta' in hunt.reason
    assert hunt.plan(close, 5.1) is None


def test_walk_duration_uses_server_speed_and_position_correction_can_finish_early():
    hunt = PacketHunt()
    hunt.start()
    initial = state([0, 0], [(20, [5, 0])])
    action = hunt.plan(initial, 0, walk_speed_ms=100)
    assert action['wait_seconds'] == pytest.approx(.3)
    hunt.sent(action, 0)
    hunt.observe([{'kind': 'player_move', 'destination': action['destination']}], 1, .01)
    assert hunt.plan(state([3, 0], [(20, [5, 0])]), .02) is None
    hunt.observe([{'kind': 'position', 'entity_id': 1, 'position': [3, 0]}], 1, .03)
    assert hunt.plan(state([3, 0], [(20, [5, 0])]), .04)['kind'] == 'attack'


def test_target_removal_releases_pending_immediately_without_counting_kill():
    hunt = PacketHunt()
    hunt.start()
    hunt.sent(hunt.plan(state([0, 0], [(20, [1, 0])]), 0), 0)
    hunt.observe([{'kind': 'remove', 'entity_id': 20}], 1, .01)
    assert hunt.confirmed_attacks == 0
    assert hunt.plan(state([0, 0], [(21, [1, 1])]), .02)['target_id'] == 21


def test_no_monsters_waits_and_invalid_player_state_stops():
    hunt = PacketHunt()
    hunt.start()
    assert hunt.plan(state([0, 0], []), 0) is None
    assert hunt.enabled
    invalid = state([0, 0], [(20, [1, 0])])
    invalid['player_position_recent'] = False
    assert hunt.plan(invalid, 1) is None
    assert not hunt.enabled


def test_other_movement_response_does_not_acknowledge_planned_step():
    hunt = PacketHunt()
    hunt.start()
    initial = state([0, 0], [(20, [8, 0])])
    hunt.sent(hunt.plan(initial, 0), 0)
    hunt.observe([{'kind': 'player_move', 'destination': [0, 8]},
                  {'kind': 'position', 'entity_id': 20, 'position': [4, 0]}], 1, 1)
    assert hunt.pending['movement_acknowledged'] is False


def test_distant_monster_is_selected_but_outside_radius_is_ignored():
    hunt = PacketHunt()
    hunt.start()
    action = hunt.plan(state([0, 0], [(20, [25, 0]), (21, [29, 0])]), 0)
    assert action['target_id'] == 20
    hunt.start()
    assert hunt.plan(state([0, 0], [(21, [29, 0])]), 0) is None


def test_long_approach_allows_more_than_three_steps():
    hunt = PacketHunt()
    hunt.start()
    for step in range(6):
        now = step*2
        action = hunt.plan(state([step*4, 0], [(20, [25, 0])]), now, 100)
        assert action['kind'] == 'move'
        hunt.sent(action, now)
        hunt.observe([{'kind': 'player_move', 'destination': action['destination']}], 1, now+.01)
    assert hunt.plan(state([24, 0], [(20, [25, 0])]), 12)['kind'] == 'attack'


def test_removing_moving_target_does_not_cancel_wait_for_own_movement():
    hunt = PacketHunt()
    hunt.start()
    action = hunt.plan(state([0, 0], [(20, [8, 0])]), 0)
    hunt.sent(action, 0)
    hunt.observe([{'kind': 'remove', 'entity_id': 20}], 1, .01)
    assert hunt.pending['kind'] == 'move'
    assert hunt.plan(state([4, 0], [(21, [5, 0])]), .02) is None


class Writer:
    def __init__(self):
        self.packets = []
    def write(self, payload):
        self.packets.append(payload)
    async def drain(self):
        pass


def test_relay_hunt_never_sends_without_focus_and_does_not_duplicate_pending(tmp_path):
    async def scenario():
        relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
        relay.hunt = PacketHunt()
        relay.hunt.start()
        relay.upstream = Writer()
        now = time.monotonic()
        observer = relay.tracker.observer
        observer.player_id, observer.player, observer.player_at = 1, [10, 10], now
        observer.registry.update(Entity(20, 1051, 11, 10, now, 'monster'))
        action = {'kind': 'attack', 'target_id': 20}
        with pytest.raises(ValueError, match='Foco'):
            await relay.send_hunt_action(action, game_gate=lambda: False)
        assert not relay.upstream.packets
        await relay.send_hunt_action(action, game_gate=lambda: True)
        assert len(relay.upstream.packets[0]) == 19
        assert struct.unpack_from('<I', relay.upstream.packets[0], 5)[0] == 20
        with pytest.raises(ValueError, match='pendente'):
            await relay.send_hunt_action(action, game_gate=lambda: True)
        assert len(relay.upstream.packets) == 1
        relay.hunt.pause('F12')
        with pytest.raises(ValueError, match='inativa'):
            await relay.send_hunt_action(action, game_gate=lambda: True)
    asyncio.run(scenario())


def test_patrol_hunt_prefers_monsters_ahead_over_slightly_closer_ones_behind():
    from nrobot.packet_patrol import PacketPatrol
    hunt = PacketHunt(); hunt.start()
    hunt.patrol = PacketPatrol(); hunt.patrol.heading = (8, 0)  # sweeping to the east
    ahead_and_behind = state([50, 50], [(30, [41, 50]), (31, [60, 50])])
    assert hunt.plan(ahead_and_behind, 0)['target_id'] == 31  # 10 ahead beats 9 behind
    hunt = PacketHunt(); hunt.start()
    hunt.patrol = PacketPatrol(); hunt.patrol.heading = (8, 0)
    far_behind = state([50, 50], [(32, [30, 50])])
    action = hunt.plan(far_behind, 0)
    assert action is None or action.get('target_id') != 32  # far behind: left for the sweep
    hunt = PacketHunt(); hunt.start()
    no_patrol = state([50, 50], [(30, [41, 50]), (31, [60, 50])])
    assert hunt.plan(no_patrol, 0)['target_id'] == 30  # without patrol: simply the closest


def walled_map():
    """60x40 open ground with a wall at x=20 from the top down to y=34 (way around at the bottom)."""
    from nrobot.map_navigation import CollisionMap
    width, height = 60, 40
    return CollisionMap(width, height, [int(not (x == 20 and y <= 34)) for y in range(height) for x in range(width)])


def test_monster_across_a_wall_is_not_chosen_over_a_reachable_one():
    collision = walled_map()
    hunt = PacketHunt(); hunt.start()
    # 101 is 10 cells away in a straight line but ~70 steps around the wall; 102 is 15 cells away on this side.
    seen = state([15, 5], [(101, [25, 5]), (102, [5, 20])])
    action = hunt.plan(seen, 0, collision=collision)
    assert action['kind'] == 'move' and action['target_id'] == 102
    assert hunt.wall_checks[101][3]


def test_only_monsters_across_the_wall_leave_the_character_where_it_is():
    collision = walled_map()
    hunt = PacketHunt(); hunt.start()
    assert hunt.plan(state([15, 5], [(101, [25, 5])]), 0, collision=collision) is None
    assert hunt.target is None


def test_current_target_found_across_a_wall_is_dropped_unless_it_attacks():
    collision = walled_map()
    hunt = PacketHunt(); hunt.start()
    hunt.target, hunt.target_since = 101, 0
    assert hunt.plan(state([15, 5], [(101, [25, 5])]), 0, collision=collision) is None
    assert hunt.target is None and 101 in hunt.excluded_until
    fighting = PacketHunt(); fighting.start()
    fighting.target, fighting.target_since, fighting.aggressors = 101, 0, {101: 0}
    action = fighting.plan(state([15, 5], [(101, [25, 5])]), 0, collision=collision)
    assert action['kind'] == 'move' and action['target_id'] == 101  # it is hitting us: go get it


def test_a_short_way_around_is_still_hunted():
    from nrobot.map_navigation import CollisionMap
    collision = CollisionMap(40, 40, [int(not (x == 20 and 3 <= y <= 7)) for y in range(40) for x in range(40)])
    hunt = PacketHunt(); hunt.start()
    action = hunt.plan(state([15, 5], [(101, [25, 5])]), 0, collision=collision)
    assert action['kind'] == 'move' and action['target_id'] == 101


def test_walled_monster_is_not_dropped_and_repicked_every_tick_with_deferral_off():
    """Log of 2026-11-04: target deferral 0 s; the rotation picked the walled monster again every
    tick and the hunt dropped it again (1958 times in 51 s, standing still)."""
    collision = walled_map()
    hunt = PacketHunt(); hunt.TARGET_DEFER = 0; hunt.start()
    seen = state([15, 5], [(101, [25, 5])])
    for tick in range(20):
        hunt.target = 101  # what the skill rotation did each tick
        hunt.plan(seen, tick*.02, collision=collision)
    ignored = [d for d in hunt.diagnostics if d['kind'] == 'target_ignored']
    assert len(ignored) <= 1 and hunt.walled(101, .3)


def test_unreachable_attacker_releases_engagement_instead_of_locking_combat():
    collision = walled_map()
    collision.route = lambda *args, **kwargs: None  # no valid approach even with partial search
    hunt = PacketHunt(); hunt.TARGET_DEFER = 0; hunt.start()
    hunt.observe([{'kind': 'normal_attack', 'source_id': 101, 'target_id': 1}], 1, 0)
    hunt.target = hunt.engaged = 101
    hunt.engaged_until = 100
    seen = state([15, 5], [(101, [25, 5])])
    assert hunt.plan(seen, .1, collision=collision) is None
    assert hunt.engaged is None and hunt.target is None and hunt.excluded_until[101] > .1
    # More incoming hits during the short deferral do not reacquire the same impossible path.
    hunt.observe([{'kind': 'normal_attack', 'source_id': 101, 'target_id': 1}], 1, .2)
    assert hunt.engaged is None


def test_detour_around_blocked_cells_is_not_a_wall():
    from nrobot.map_navigation import CollisionMap
    collision = CollisionMap(40, 40, [1]*1600)
    hunt = PacketHunt(); hunt.start()
    hunt.blocked_until = {(17, y): 99 for y in range(0, 12)}  # failed steps, not walls
    action = hunt.plan(state([15, 5], [(101, [22, 5])]), 0, collision=collision)
    assert action['kind'] == 'move' and action['target_id'] == 101
