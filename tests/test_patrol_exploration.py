"""REDE-40: coverage properties rather than one fixed random route."""
import math
import random

from nrobot.packet_patrol import PacketPatrol
from nrobot.map_navigation import CollisionMap


def test_open_exploration_varies_steps_and_directions_while_progressing_same_heading():
    patrol = PacketPatrol(rng=random.Random(7))
    initial_heading = patrol.heading
    position = [200, 200]
    directions, lengths = set(), set()
    endpoints = []
    for index in range(40):
        action = patrol.plan(position, index*3, 100)
        destination = action['destination']
        dx, dy = destination[0]-position[0], destination[1]-position[1]
        assert max(abs(dx), abs(dy)) <= 8
        directions.add(((dx > 0)-(dx < 0), (dy > 0)-(dy < 0)))
        lengths.add(max(abs(dx), abs(dy)))
        patrol.reached(destination, position)
        position = destination
        endpoints.append(tuple(position))
    assert len(directions) >= 3 and len(lengths) >= 3
    assert len(set(endpoints)) == 40
    assert len(patrol.visits) > 40


def test_intermediate_sectors_are_marked_and_chase_does_not_reorient_general_patrol():
    patrol = PacketPatrol(rng=random.Random(7))
    initial_heading = patrol.heading
    patrol.reached([0, 0])
    patrol.reached([8, 8], [0, 0])
    assert set(patrol.visits) == {(0, 0), (1, 1), (2, 2)}
    patrol.reached([4, 8], [8, 8])
    assert patrol.heading == initial_heading


def test_bounded_map_exploration_avoids_collisions_and_reaches_many_sectors():
    collision = CollisionMap(60, 60, [1]*3600)
    for seed in (1, 7, 42):
        patrol = PacketPatrol(rng=random.Random(seed))
        position = [20, 20]
        for index in range(100):
            action = patrol.plan(position, index*3, 100, collision)
            assert action is not None
            destination = action['destination']
            assert collision.segment(position, destination, max_steps=8)
            patrol.reached(destination, position)
            position = destination
        assert len(patrol.visits) >= 40


def test_small_repeated_loop_requests_an_escape():
    patrol = PacketPatrol(rng=random.Random(7))
    position = [20, 20]
    for index in range(10):
        destination = [24, 20] if index % 2 == 0 else [20, 20]
        patrol.reached(destination, position)
        position = destination
    assert patrol.escape_next and patrol.loop_escapes == 1
    assert patrol.plan(position, 30, 100) is not None
    assert not patrol.escape_next


def test_initial_heading_is_not_always_same_corner_and_boundary_is_left():
    assert len({PacketPatrol(rng=random.Random(seed)).heading for seed in range(20)}) >= 6
    collision = CollisionMap(60, 60, [1]*3600)
    for seed in (1, 7, 42):
        patrol = PacketPatrol(rng=random.Random(seed))
        position = [1, 1]
        corners = 0
        for index in range(150):
            action = patrol.plan(position, index*2, 100, collision)
            assert action is not None
            patrol.reached(action['destination'], position)
            position = action['destination']
            if min(position) < 6 and max(position) < 6: corners += 1
        assert corners < 10
        assert len(patrol.visits) > 50




def walk_cycle(patrol, collision, position, limit=3000):
    """Follow the patrol until it starts a second cycle; returns walked cells and the trail."""
    walked, trail = 0, [tuple(position)]
    for index in range(limit):
        action = patrol.plan(position, index, 100, collision)
        if patrol.cycle_number == 2:
            return walked, trail
        if action is None:
            continue
        destination = action['destination']
        assert collision.segment(position, destination, max_steps=8)
        walked += max(abs(destination[i]-position[i]) for i in (0, 1))
        patrol.reached(destination, position)
        position = destination
        trail.append(tuple(position))
    raise AssertionError('cycle did not finish')


def test_global_route_progress_does_not_reverse_on_free_ground():
    collision = CollisionMap(100, 100, [1]*10000)
    patrol = PacketPatrol(rng=random.Random(7))
    patrol.switch_map(collision, [10, 10])
    block = max(patrol.remaining, key=lambda b: math.dist([10, 10], patrol.tour.points[b]))
    patrol.goal_block, patrol.goal = block, patrol.tour.points[block]
    patrol.goal_distance = math.dist([10, 10], patrol.goal)
    goal = patrol.goal
    position = [10, 10]
    for index in range(8):
        before = math.dist(position, goal)
        action = patrol.plan(position, index*5, 100, collision)
        assert patrol.goal == goal  # progress extends timeout beyond 25 seconds
        destination = action['destination']
        assert math.dist(destination, goal) < before
        assert max(abs(destination[i]-position[i]) for i in (0, 1)) >= 4
        patrol.reached(destination, position)
        position = destination


def test_cycle_visits_every_waypoint_and_heartbeats_keep_progress():
    collision = CollisionMap(60, 50, [1]*3000)
    patrol = PacketPatrol(rng=random.Random(7))
    position = [2, 2]
    patrol.plan(position, 0, 100, collision)
    total = set(patrol.tour.points)
    seen = set(patrol.done)
    for index in range(1, 400):
        action = patrol.plan(position, index, 100, collision)
        if patrol.cycle_number == 2:
            break
        seen |= patrol.done
        if action is None:
            continue
        patrol.reached(action['destination'], position)
        before = set(patrol.done)
        patrol.reached(action['destination'])  # pause/heartbeat must not reset coverage
        assert patrol.done == before
        seen |= patrol.done
        position = action['destination']
    else:
        raise AssertionError('cycle did not finish')
    assert seen == total


def test_waypoints_stay_on_open_ground_away_from_walls_and_corners():
    # A room with pillars and a thin dead-end corridor: no waypoint may sit next to a wall.
    width = height = 80
    cells = bytearray([1]*(width*height))
    for x in range(20, 24):
        for y in range(20, 60):
            cells[y*width+x] = 0
    for y in range(0, 70):
        for x in (60, 63):
            cells[y*width+x] = 0  # 2-cell wide dead end between x=61..62
    collision = CollisionMap(width, height, cells)
    patrol = PacketPatrol(rng=random.Random(1))
    patrol.switch_map(collision, [5, 5])
    assert patrol.tour.points
    assert all(patrol.tour.wall[point] >= 2 for point in patrol.tour.points.values())
    assert not any(61 <= point[0] <= 62 for point in patrol.tour.points.values())


def test_cycle_excludes_disconnected_ground():
    collision = CollisionMap(40, 40, [int(x != 20) for y in range(40) for x in range(40)])
    patrol = PacketPatrol()
    patrol.plan([1, 1], 0, 100, collision)
    assert all(point[0] < 20 for point in patrol.tour.points.values())


def test_old_sightings_cannot_redirect_cycle_and_goal_is_a_close_waypoint():
    from nrobot.packet_hunt import PacketHunt
    collision = CollisionMap(80, 80, [1]*6400)
    hunt = PacketHunt(patrol=True)
    hunt.start()
    state = {'state': 'tracking', 'player_position_recent': True, 'player_position': [40, 40],
             'recent_entities': [], 'search_goal': {'entity_id': 20, 'position': [2, 2]}}
    action = hunt.plan(state, 0, 100, collision)
    patrol = hunt.patrol
    assert patrol.search_destination is None and action is not None
    closest = min(math.dist([40, 40], patrol.tour.points[b]) for b in patrol.remaining)
    assert math.dist([40, 40], patrol.goal) <= closest+12


def test_walls_split_distance_so_goal_is_not_behind_a_long_detour():
    # Vertical wall at x=30 with a gap only at the bottom: ground just across the wall is
    # far by walking, so the closer side must be finished first.
    cells = bytearray([1]*(80*80))
    for y in range(0, 74):
        cells[y*80+30] = 0
    collision = CollisionMap(80, 80, cells)
    patrol = PacketPatrol(rng=random.Random(1))
    position = [10, 5]
    for index in range(40):
        action = patrol.plan(position, index, 100, collision)
        assert patrol.goal[0] < 30
        patrol.reached(action['destination'], position)
        position = action['destination']
        if not any(p[0] < 30 for b, p in patrol.tour.points.items() if b in patrol.remaining):
            break


def test_coverage_is_remembered_per_map_when_returning():
    first, second = CollisionMap(60, 60, [1]*3600), CollisionMap(40, 40, [1]*1600)
    patrol = PacketPatrol(rng=random.Random(2))
    patrol.plan([30, 30], 0, 100, first)
    done = set(patrol.done)
    assert done
    patrol.plan([5, 5], 1, 100, second)
    assert patrol.tour.collision is second
    patrol.plan([30, 30], 2, 100, first)
    assert done <= patrol.done and patrol.tour.collision is first


def test_large_open_map_is_covered_without_retracing():
    collision = CollisionMap(120, 120, [1]*14400)
    patrol = PacketPatrol(rng=random.Random(3))
    walked, trail = walk_cycle(patrol, collision, [5, 5])
    # Lanes ~SPACING apart: a sweep over 120x120 needs ~120*120/12 = 1200 cells.
    assert walked < 1700
    view = {(x, y) for x in range(120) for y in range(119)
            if any(math.dist((x, y), p) <= 12 for p in trail[::1] if abs(p[0]-x) <= 12 and abs(p[1]-y) <= 12)}
    assert len(view)/(120*119) > .97


def test_coverage_goal_remains_reachable_when_revisit_penalties_exhaust_search_budget():
    class BudgetMap(CollisionMap):
        def route(self, *args, **kwargs):
            if kwargs.get('visited_sectors'):
                return None
            return super().route(*args, **kwargs)
    collision = BudgetMap(60, 60, [1]*3600)
    patrol = PacketPatrol()
    position = [2, 2]
    for index in range(6):
        action = patrol.plan(position, index, 100, collision)
        if action is not None:
            assert collision.segment(position, action['destination'], max_steps=8)
            patrol.reached(action['destination'], position)
            position = action['destination']
    assert patrol.walked and action is not None


def test_spacing_coverage_and_wall_margin_are_configurable():
    from nrobot.map_navigation import CollisionMap
    from nrobot.patrol_tour import PatrolTour
    from nrobot.packet_patrol import PacketPatrol
    open_map = CollisionMap(80, 80, [1]*6400)
    dense, sparse = PatrolTour(open_map, (40, 40), spacing=8), PatrolTour(open_map, (40, 40), spacing=20)
    assert len(dense.points) > 2*len(sparse.points) and sparse.seen_radius == 15
    near_walls = PatrolTour(open_map, (40, 40), spacing=10, wall_margin=1)
    away = PatrolTour(open_map, (40, 40), spacing=10, wall_margin=6, avoid_walls=True)
    assert min(away.wall[p] for p in away.points.values()) >= 6  # no point next to a wall
    assert min(near_walls.wall[p] for p in near_walls.points.values()) < 6
    patrol = PacketPatrol(8, spacing=10, coverage=.5)
    patrol.switch_map(open_map, [40, 40])
    for block in list(patrol.remaining)[:len(patrol.tour.points)//2+1]:
        patrol.remaining.discard(block); patrol.done.add(block)
    cycle = patrol.cycle_number
    patrol.plan([40, 40], 100, 150, open_map)
    assert patrol.cycle_number == cycle+1  # half the map done: a new cycle, as configured
    patrol.configure(spacing=20, coverage=1.0, wall_margin=2, avoid_walls=False)
    assert patrol.tour is None and patrol.coverage_target == 1.0  # waypoints redone with the new spacing


def test_ring_shaped_map_is_swept_without_jumping_away_from_waypoints_right_beside():
    # A cave ring like ve_fild04: the sweep goes on along it instead of leaving points behind.
    from nrobot.map_navigation import CollisionMap
    from nrobot.packet_patrol import PacketPatrol
    import math as m
    size = 120
    cells = bytearray(size*size)
    for y in range(size):
        for x in range(size):
            if 25 <= m.dist((x, y), (60, 60)) <= 50:
                cells[y*size+x] = 1
    collision = CollisionMap(size, size, cells)
    patrol = PacketPatrol(rng=random.Random(4), spacing=12)
    position, jumps, goals = [60, 15], 0, 0
    for tick in range(600):
        before = patrol.goal_block
        action = patrol.plan(position, tick, 100, collision)
        if patrol.goal_block is not None and patrol.goal_block != before:
            goals += 1
            distances = patrol.tour.distances(position)
            near = [b for b in patrol.remaining if b != patrol.goal_block and distances.get(b, 1e9) <= 12]
            if distances[patrol.goal_block] > 36 and near:
                jumps += 1  # went far while a waypoint was right beside
        if action is None or patrol.cycle_number > 1:
            break
        patrol.reached(action['destination'], position)
        position = action['destination']
    assert goals > 10 and jumps == 0


def test_waypoints_behind_refused_steps_are_given_up_until_the_next_cycle():
    from nrobot.map_navigation import CollisionMap
    from nrobot.packet_patrol import PacketPatrol
    patrol = PacketPatrol(rng=random.Random(5), spacing=10)
    open_map = CollisionMap(60, 60, [1]*3600)
    patrol.switch_map(open_map, [30, 30])
    patrol.plan([30, 30], 0, 100, open_map)
    goal = patrol.goal_block
    for t in range(3):  # the server refuses the way three times from the same cell
        patrol.failed([30, 30], [36, 30], t)
    assert goal in patrol.unreachable and goal not in patrol.remaining and patrol.goal is None
    patrol.new_cycle([30, 30])
    assert not patrol.unreachable  # tried again on the next round
