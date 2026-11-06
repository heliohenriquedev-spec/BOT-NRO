"""REDE-69: server walk path replica, step timing and server clock."""
from nrobot.map_navigation import CollisionMap
from nrobot.network_observer import Observer
from nrobot.network_targets import Entity
from nrobot.server_clock import ServerClock
from nrobot.server_path import server_path, step_durations, cells_at


def open_map(size=40, walls=()):
    cells = bytearray([1]*(size*size))
    for x, y in walls:
        cells[y*size+x] = 0
    return CollisionMap(size, size, cells)


def test_open_ground_path_is_diagonal_first_then_straight_with_server_costs():
    path = server_path(open_map(), (5, 5), (10, 7))
    assert path[0] == (5, 5) and path[-1] == (10, 7) and len(path) == 6
    steps = list(zip(path, path[1:]))
    assert sum(a[0] != b[0] and a[1] != b[1] for a, b in steps) == 2  # min(dx, dy) diagonals
    assert step_durations(path, 150) == [.21 if a[0] != b[0] and a[1] != b[1] else .15 for a, b in steps]


def test_path_walks_around_wall_corners_instead_of_cutting_them():
    wall = [(8, y) for y in range(3, 9)]
    path = server_path(open_map(walls=wall), (6, 6), (10, 6))
    assert path[-1] == (10, 6) and all(cell not in wall for cell in path)
    for a, b in zip(path, path[1:]):
        if a[0] != b[0] and a[1] != b[1]:  # a diagonal never squeezes past a wall corner
            assert (b[0], a[1]) not in wall and (a[0], b[1]) not in wall


def test_server_limits_are_reproduced():
    assert server_path(open_map(80), (2, 2), (40, 2)) is None  # more than 32 steps
    assert server_path(open_map(walls=[(9, 9)]), (5, 5), (9, 9)) is None  # blocked destination
    assert server_path(open_map(), (5, 5), (5, 5)) == [(5, 5)]


def test_candidate_cells_cover_half_step_and_end_of_step_conventions():
    path = [(0, 0), (1, 0), (2, 0)]
    durations = step_durations(path, 200)
    assert cells_at(path, durations, 0) == [(0, 0)]
    assert cells_at(path, durations, .15) == [(1, 0), (0, 0)]  # past half, before the end
    assert cells_at(path, durations, .25) == [(1, 0)]
    assert cells_at(path, durations, 1) == [(2, 0)]


def test_entity_follows_server_path_around_obstacle_not_straight_line():
    wall = [(8, y) for y in range(3, 9)]
    path = tuple(server_path(open_map(walls=wall), (6, 6), (10, 6)))
    entity = Entity(1, 1002, 6, 6, 0, 'monster', destination=(10, 6), walk_speed_ms=200, path=path, walk_started=0)
    middle = entity.position_bounds(.35)[0]
    assert all(tuple(cell) in path for cell in middle)
    assert all(tuple(cell) not in wall for cell in middle)
    assert entity.position_bounds(5) == ([[10, 6]], True)


def test_server_clock_uses_round_trip_of_time_requests():
    clock = ServerClock()
    clock.observe(10_000, 100.5)  # move packet before any time request: latency-biased fallback
    assert abs(clock.to_local(10_000, 100.5)-100.5) < 1e-9
    clock.request_sent(200.0)
    clock.time_reply(109_000, 200.008)
    assert abs(clock.to_local(109_500, 201) - 200.504) < 1e-6
    assert clock.to_local(200_000, 201) == 201  # never in the future of arrival


def test_observer_builds_paths_from_move_packets_with_server_tick():
    observer = Observer({1002})
    collision = open_map()
    observer.collision_provider = lambda: collision
    observer.apply({'kind': 'appearance', 'entity_id': 7, 'species_id': 1002, 'position': [5, 5], 'walk_speed_ms': 200}, 0)
    observer.apply({'kind': 'move', 'entity_id': 7, 'position': [5, 5], 'destination': [9, 5], 'server_tick': 4_000}, 1)
    entity = observer.registry.entities[7]
    assert entity.path[0] == (5, 5) and entity.path[-1] == (9, 5) and entity.walk_started == 1
    observer.apply({'kind': 'player_move', 'position': [3, 3], 'destination': [6, 3], 'server_tick': 4_100}, 1.1)
    assert observer.player_motion['path'][-1] == (6, 3)
    assert observer.combat_positions(10) == [[6, 3]]


def test_maps_without_collision_use_the_free_ground_server_path():
    observer = Observer({1002})
    observer.apply({'kind': 'appearance', 'entity_id': 7, 'species_id': 1002, 'position': [5, 5], 'walk_speed_ms': 200}, 0)
    observer.apply({'kind': 'move', 'entity_id': 7, 'position': [5, 5], 'destination': [9, 7], 'server_tick': 4_000}, 1)
    path = observer.registry.entities[7].path
    assert path[:3] == ((5, 5), (6, 6), (7, 7)) and path[-1] == (9, 7)  # diagonal first, then straight
    observer.apply({'kind': 'player_move', 'position': [3, 3], 'destination': [6, 3], 'server_tick': 4_100}, 1.1)
    assert observer.player_motion['path'] == ((3, 3), (4, 3), (5, 3), (6, 3))
