"""REDE-34: coverage, target priority and common send/stop guards."""
import asyncio
import time
import random
import pytest

from nrobot.packet_patrol import PacketPatrol
from nrobot.packet_hunt import PacketHunt
from nrobot.map_navigation import CollisionMap
from nrobot.session_relay import SessionRelay, HuntTargetChanged
from nrobot.network_targets import Entity


def state(position, entities=None):
    return {'state': 'tracking', 'player_position_recent': True,
            'player_position': position, 'recent_entities': entities or []}


def test_seeded_patrol_is_reproducible_and_prefers_unvisited_sector_over_heading():
    one, two = PacketPatrol(rng=random.Random(42)), PacketPatrol(rng=random.Random(42))
    first = one.plan([20, 20], 0, 100)
    assert first == two.plan([20, 20], 0, 100)
    for x in range(5, 9):
        for y in range(5, 9):
            one.visits[(x, y)] = 10 if x > 5 else 0
    action = one.plan([20, 20], 1, 100)
    assert action['destination'][0] == 20 and action['destination'][1] > 20


def test_long_diagonal_accounts_for_walk_time_and_full_segment_collision():
    actions = [PacketPatrol(rng=random.Random(seed)).plan([20, 20], 0, 100) for seed in range(20)]
    action = next(action for action in actions if action['destination'][0] == action['destination'][1])
    length = abs(action['destination'][0]-20)
    assert action['wait_seconds'] == pytest.approx(length*.1*1.4)
    collision = CollisionMap(40, 40, [1]*1600)
    assert collision.segment([20, 20], [28, 28], max_steps=8)
    cells = bytearray(collision.cells)
    cells[25*40+24] = 0  # diagonal corner, beyond the old four-cell limit
    collision = CollisionMap(40, 40, cells)
    assert not collision.segment([20, 20], [28, 28], max_steps=8)
    assert not collision.segment([20, 20], [28, 28])  # combat keeps its four-cell limit


def test_patrol_avoids_failed_ray_and_waits_if_all_exits_failed():
    patrol = PacketPatrol(rng=random.Random(42))
    patrol.failed([20, 20], [28, 28], 0)
    destination = patrol.plan([20, 20], .1, 100)['destination']
    assert destination[0] != destination[1]
    for direction in patrol.DIRECTIONS:
        destination = [20+8*direction[i] for i in (0, 1)]
        patrol.failed([20, 20], destination, 0)
    assert patrol.plan([20, 20], 1, 100) is None
    assert patrol.plan([20, 20], 2, 100) is None
    assert patrol.plan([20, 20], 61, 100) is not None


def test_collision_and_boundaries_limit_patrol_segments():
    cells = bytearray([1]*100)
    for y in range(10): cells[y*10+5] = 0
    collision = CollisionMap(10, 10, cells)
    action = PacketPatrol().plan([3, 3], 0, 100, collision)
    assert collision.segment([3, 3], action['destination'], max_steps=8)
    assert action['destination'] != [7, 3]
    action = PacketPatrol().plan([1022, 1022], 0, 100)
    assert all(1 <= n <= 1022 for n in action['destination'])


def test_target_appearing_during_patrol_takes_priority_after_current_step():
    hunt = PacketHunt(patrol=True, patrol_step=4)
    hunt.patrol.heading = (1, 0)
    hunt.start()
    action = hunt.plan(state([20, 20]), 0, 100)
    hunt.sent(action, 0)
    destination = action['destination']
    target = [{'entity_id': 9, 'position': [destination[0], destination[1]+1]}]
    assert hunt.plan(state([20, 20], target), .1, 100) is None
    hunt.observe([{'kind': 'player_move', 'position': [20, 20], 'destination': destination}], 1, .1)
    assert hunt.plan(state(destination, target), .15, 100) is None
    assert hunt.plan(state(destination, target), 2, 100) == {'kind': 'attack', 'target_id': 9}
    hunt.pause('Home')
    assert hunt.plan(state([24, 20]), 1, 100) is None


def test_patrol_failure_changes_direction_instead_of_repeating():
    hunt = PacketHunt(patrol=True, patrol_step=4)
    hunt.patrol.heading = (1, 0)
    hunt.start()
    action = hunt.plan(state([20, 20]), 0, 100)
    hunt.sent(action, 0)
    hunt.observe([{'kind': 'position', 'entity_id': 1, 'position': [20, 20]}], 1, .1)
    next_action = hunt.plan(state([20, 20]), .3, 100)
    a, b = action['destination'], next_action['destination']
    assert ((a[0]-20)*(b[1]-20) != (a[1]-20)*(b[0]-20)
            or sum((a[i]-20)*(b[i]-20) for i in (0, 1)) <= 0)


def test_relay_patrol_shares_pending_panic_and_target_priority_guards(tmp_path):
    async def scenario():
        relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
        relay.hunt = PacketHunt(patrol=True)
        relay.hunt.start()
        class Writer:
            def __init__(self): self.packets = []
            def write(self, data): self.packets.append(data)
            async def drain(self): pass
        relay.upstream = Writer()
        observer = relay.tracker.observer
        observer.player_id, observer.player, observer.player_at = 1, [20, 20], time.monotonic()
        action = relay.hunt.plan(relay.status(), time.monotonic(), 100)
        await relay.send_hunt_action(action, game_gate=lambda: True)
        assert len(relay.upstream.packets) == 1
        with pytest.raises(ValueError, match='pendente'):
            await relay.send_hunt_action(action, game_gate=lambda: True)
        relay.hunt.pending = None
        observer.registry.update(Entity(2, 1051, 21, 20, time.monotonic(), 'monster'))
        with pytest.raises(HuntTargetChanged, match='apareceu'):
            await relay.send_hunt_action(action, game_gate=lambda: True)
        relay.commands_blocked = True
        with pytest.raises(ValueError, match='bloqueada'):
            await relay.send_hunt_action(action, game_gate=lambda: True)
        assert len(relay.upstream.packets) == 1
    asyncio.run(scenario())
