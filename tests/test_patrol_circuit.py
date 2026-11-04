import random

from nrobot.map_navigation import CollisionMap
from nrobot.packet_patrol import PacketPatrol


def test_circuit_order_does_not_rechoose_goals_after_each_change_of_heading():
    collision = CollisionMap(90, 90, [1]*8100)
    patrol = PacketPatrol(rng=random.Random(7))
    patrol.switch_map(collision, [10, 10])
    assert len(patrol.sweep_order) == len(set(patrol.sweep_order)) == len(patrol.tour.points)
    first = patrol.next_block([10, 10])
    patrol.heading = (-1, -1)
    assert patrol.next_block([12, 12]) == first
    patrol.remaining.remove(first)
    assert patrol.next_block([12, 12]) != first
    assert set(patrol.sweep_order) == set(patrol.tour.points)


def test_connections_between_fresh_goals_do_not_detour_to_avoid_old_cells():
    class RecordingMap(CollisionMap):
        def route(self, *args, **kwargs):
            assert not kwargs.get('visited_sectors'), 'coverage belongs to goal selection, not path detours'
            return super().route(*args, **kwargs)
    collision = RecordingMap(60, 60, [1]*3600)
    patrol = PacketPatrol(rng=random.Random(7))
    position = [10, 10]
    explored = set()
    for tick in range(50):
        action = patrol.plan(position, tick, 100, collision)
        if action:
            destination = action['destination']
            assert collision.segment(position, destination, max_steps=8)
            patrol.reached(destination, position)
            position = destination
        explored.update(patrol.done)
    assert len(explored) > 5
