import math
import random

from nrobot.map_navigation import CollisionMap
from nrobot.packet_patrol import PacketPatrol
from nrobot.patrol_tour import PatrolTour


def fork_map():
    width, height = 120, 100
    def floor(x, y):
        return (8 <= x <= 110 and 38 <= y <= 42 or
                28 <= x <= 32 and 10 <= y <= 42 or
                68 <= x <= 72 and 38 <= y <= 88 or
                98 <= x <= 102 and 10 <= y <= 42)
    return CollisionMap(width, height, [int(floor(x, y)) for y in range(height) for x in range(width)])


def test_corridor_order_finishes_one_branch_before_another():
    tour = PatrolTour(fork_map(), [10, 40], spacing=8)
    assert tour.corridor_mode and len(tour.endpoints) >= 3
    order = tour.sweep_order([10, 40])
    assert set(order) == set(tour.points)
    for x in (30, 100):
        indices = [i for i, node in enumerate(order)
                   if abs(tour.points[node][0]-x) <= 3 and tour.points[node][1] < 32]
        assert len(indices) >= 2
        assert indices == list(range(min(indices), max(indices)+1))


def test_corridor_tip_must_actually_be_reached_before_being_marked():
    collision = fork_map()
    tour = PatrolTour(collision, [10, 40], spacing=8)
    for node in tour.endpoints:
        tip = tour.points[node]
        path = collision.route([10, 40], tip, exact=True)
        if len(path) > 7:
            before_tip = path[-7]
            assert node not in set(tour.seen_from(before_tip))
        assert node in set(tour.seen_from(tip))


def test_cycle_reaches_safe_tips_and_respects_walls():
    collision = fork_map()
    patrol = PacketPatrol(rng=random.Random(7), spacing=8)
    position = [10, 40]
    trail = [position]
    for tick in range(1000):
        action = patrol.plan(position, tick, 100, collision)
        if patrol.cycle_number == 2:
            break
        if action:
            destination = action['destination']
            assert collision.segment(position, destination, max_steps=8)
            patrol.reached(destination, position)
            length = max(abs(destination[i]-position[i]) for i in (0, 1))
            trail.extend([[round(position[i]+(destination[i]-position[i])*step/length) for i in (0, 1)]
                          for step in range(1, length+1)])
            position = destination
    else:
        raise AssertionError('corridor cycle did not complete')
    assert all(min(math.dist(patrol.tour.points[node], p) for p in trail) <= 2 for node in patrol.tour.endpoints)


def test_nearby_parallel_corridor_is_not_marked_through_a_wall():
    width, height = 100, 50
    cells = [int(10 <= x <= 90 and (20 <= y <= 22 or 26 <= y <= 28) or
                 10 <= x <= 12 and 20 <= y <= 28) for y in range(height) for x in range(width)]
    collision = CollisionMap(width, height, cells)
    tour = PatrolTour(collision, [11, 21], spacing=8, wall_margin=1)
    assert tour.corridor_mode
    candidates = [(a, b) for a, p in tour.points.items() for b, q in tour.points.items()
                  if a not in tour.endpoints and b not in tour.endpoints and a != b
                  and math.dist(p, q) <= tour.seen_radius and not collision.line_clear(p, q)]
    assert candidates
    a, b = candidates[0]
    assert b not in set(tour.seen_from(tour.points[a]))
