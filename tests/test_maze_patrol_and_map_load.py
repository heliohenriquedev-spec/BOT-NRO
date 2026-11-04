import random
import time

from nrobot.map_navigation import CollisionMap
from nrobot.packet_patrol import PacketPatrol


def comb():
    """One-cell corridors (a maze): a spine at y=5 with teeth going down every 6 cells."""
    width, height = 61, 40
    cells = [int(y == 5 and 1 <= x <= 59 or x % 6 == 1 and 5 <= y <= 35) for y in range(height) for x in range(width)]
    return CollisionMap(width, height, cells)


def test_maze_patrol_goes_to_the_nearest_pending_waypoint():
    collision = comb()
    patrol = PacketPatrol(8, random.Random(1), spacing=8)
    patrol.plan((1, 5), 0, 150, collision)
    assert patrol.tour.corridor_mode
    distances = patrol.tour.distances((1, 5))
    candidates = patrol.remaining-set(patrol.deferred)
    chosen = patrol.next_block((1, 5))
    assert distances[chosen] == min(distances[b] for b in candidates if b in distances)


def test_keeping_off_walls_never_costs_a_long_detour():
    # A one-cell corridor straight ahead and a wide road far around: the corridor is taken.
    width, height = 60, 40
    cells = [int(y == 5 and 1 <= x <= 50 or 30 <= y <= 38 and 1 <= x <= 50 or (x <= 4 or x >= 47) and 5 <= y <= 38)
             for y in range(height) for x in range(width)]
    collision = CollisionMap(width, height, cells)
    patrol = PacketPatrol(8, random.Random(1), spacing=8, avoid_walls=True)
    route = patrol.route(collision, (2, 5), (49, 5), exact=True, max_nodes=50000, wall_cost=patrol.wall_cost())
    assert len(route)-1 <= 50
    open_ground = patrol.route(collision, (2, 32), (49, 32), exact=True, max_nodes=50000, wall_cost=patrol.wall_cost())
    assert len(open_ground)-1 <= 50  # nearly straight: kept as found


def test_nothing_is_sent_until_the_game_finished_loading_the_map(tmp_path):
    from nrobot.session_relay import SessionRelay
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    now = time.monotonic()
    assert not relay.map_loading(now)
    relay.map_changed_at = now
    assert relay.map_loading(now+1)  # waiting for the client's 007D
    relay.native_frames._fallback = {}
    relay.inspect_native_frames(b'\x7d\x00')
    assert not relay.map_loading(time.monotonic())
    relay.map_changed_at, relay.map_loaded_at = now, None
    assert not relay.map_loading(now+relay.MAP_LOAD_LIMIT)  # never stuck if the 007D is missed


def test_native_frames_are_read_only_after_the_server_accepts_the_map_connection(tmp_path):
    """A new map connection left the guard reading the map login or half a frame: 1A00 (2026-11-04)."""
    import struct
    from nrobot.session_relay import SessionRelay
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    relay.native_feed = False  # set when a map connection opens
    accepted = struct.pack('<HI', 0x73, 0)+bytes([10, 10 << 2 & 0xff, 0])+bytes([5, 5])
    relay.mirror_map(accepted)
    assert relay.native_feed
    relay.native_frames._fallback = {}
    assert relay.inspect_native_frames(b'\x7d\x00') == [0x7d] and relay.native_frames.error is None
