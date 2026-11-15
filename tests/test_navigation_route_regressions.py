"""Route reuse and server movement must respect physical map geometry."""
from nrobot.map_navigation import CollisionMap, MapRepository
from nrobot.network_observer import Observer
from nrobot.portals import PortalGuard
from nrobot.quest_routes import QuestRoutes
from nrobot.session_relay import SessionRelay
from types import SimpleNamespace
import pytest


def test_cached_route_rejoins_around_a_corner_instead_of_cutting_it():
    cells = bytearray([1]*64)
    cells[2*8+3] = 0
    c = CollisionMap(8, 8, cells)
    q = QuestRoutes()
    assert q.path_to(c, (3, 3), (6, 3), True)
    path = q.path_to(c, (2, 2), (6, 3), True)
    assert path[0] == (2, 2) and path[-1] == (6, 3)
    assert all(c.edge(a, b) for a, b in zip(path, path[1:]))


def test_learning_an_inner_portal_invalidates_an_unreachable_cached_path():
    cells = bytearray([1]*100)
    for y in range(10):
        cells[y*10+5] = 0
    c = CollisionMap(10, 10, cells)
    q = QuestRoutes()
    assert q.path_to(c, (2, 2), (7, 2), True) is None
    path = q.path_to(c, (2, 2), (7, 2), True, [((4, 2), (6, 2))])
    assert path[-1] == (4, 2)


def test_changed_collision_does_not_reuse_a_cached_walk():
    c = CollisionMap(10, 10, [1]*100)
    q = QuestRoutes()
    path = q.path_to(c, (2, 2), (7, 2), True)
    c.set_forbidden({(4, 2)})
    path = q.path_to(c, (2, 2), (7, 2), True)
    assert (4, 2) not in path
    assert all(c.edge(a, b) for a, b in zip(path, path[1:]))


def test_confirmed_walk_uses_ground_even_inside_a_guarded_portal():
    cells = bytearray([1]*144)
    cells[4*12+5] = 0
    c = CollisionMap(12, 12, cells)
    c.set_forbidden({(7, 5), (6, 5)})
    o = Observer(set())
    o.collision_provider = lambda: c
    o.apply(dict(kind='player_move', position=[3, 3], destination=[7, 5]), 0)
    path = o.player_motion['path']
    assert path and path[-1] == (7, 5)
    assert c.forbidden == frozenset({(7, 5), (6, 5)})
    for tick in range(200):
        assert all(c.ground(p) for p in o.combat_positions(tick/100))


def test_sewer_entrance_predicts_the_confirmed_walk_through_the_portal(tmp_path):
    c = MapRepository(tmp_path, independent=True).get('areia.gat')
    assert c is not None
    guard = PortalGuard(tmp_path/'portais.json')
    guard.known = {'areia': {'108,250': 3}}
    c.set_forbidden(guard.cells('areia', edge=1))
    o = Observer(set())
    o.collision_provider = lambda: c
    o.apply(dict(kind='player_move', position=[112, 252], destination=[108, 250]), 0)
    assert o.player_motion['path'][-1] == (108, 250)
    assert all(c.ground(p) for p in o.player_motion['path'])


def test_travel_leaves_the_arrival_portal_before_crossing_the_sewer(tmp_path):
    c = MapRepository(tmp_path, independent=True).get('alde_dun02.gat')
    guard = PortalGuard(tmp_path/'portais.json')
    guard.known = {'alde_dun02': {'43,23': 3, '123,170': 3}}
    guard.widened = {'alde_dun02': {'43,23': 3}}
    relay = SessionRelay.__new__(SessionRelay)
    relay.portals = guard
    relay.tracker = SimpleNamespace(observer=SimpleNamespace(map_name='alde_dun02.gat', player=[41, 23]))
    relay.collision_map = lambda: c
    relay.hunt = SimpleNamespace(enabled=False)
    q = QuestRoutes()
    q.start_validation([dict(kind='portal',map='alde_dun02.gat',position=[123,170]),
                        dict(kind='wait_map',map='gl_prison.gat')], 'gl_prison.gat', 0, mode='travel', label='t')
    def escape(point, step):
        return relay.leave_portal_area(0, travelling=True, position=point, allowed_portal=step['position'])
    position = [41, 23]
    for tick in range(150):
        action = q.plan('alde_dun02.gat',position,c,guard,tick/10,portal_escape=escape)
        assert q.phase != 'paused', q.reason
        if action is None:
            assert position == [123, 170]
            break
        assert action['kind'] == 'move'
        # Escape and planned legs must be walkable by the server without cutting walls.
        assert c.plain().segment(position,action['position'],max_steps=16)
        position = action['position']
    else:
        raise AssertionError('sewer travel did not reach its exit')
    # A portal intentionally selected by the route must remain enterable.
    assert relay.leave_portal_area(0,travelling=True,position=[122,170],allowed_portal=[123,170]) is None


@pytest.mark.parametrize('async_paths', [False, True])
def test_sewer_trip_waits_for_each_inner_warp_and_continues_without_clearing_cache(tmp_path, async_paths):
    """Reproduce the stop at 101,176 before the warp packet to 141,31 arrives."""
    c = MapRepository(tmp_path, independent=True).get('prt_sewb2.gat')
    guard = PortalGuard(tmp_path/'portais.json')
    guard.known = {'prt_sewb2': {'20,175': 3, '101,176': 3, '180,24': 3}}
    guard.internal = {'prt_sewb2': {'20,175': [60,28], '101,176': [141,31]}}
    q = QuestRoutes()
    q.start_validation([dict(kind='portal',map='prt_sewb2.gat',position=[180,24]),
                        dict(kind='wait_map',map='prt_sewb4.gat')], 'prt_sewb4.gat', 0, mode='travel', label='t')
    q.async_paths = async_paths
    # This test exercises the worker path too, while keeping simulated times deterministic.
    q.ASYNC_WAIT = 5
    position = [20, 17]
    crossed = []
    now = 0
    links = dict(guard.links('prt_sewb2'))
    for _ in range(200):
        now += .2
        action = q.plan('prt_sewb2.gat',position,c,guard,now)
        assert q.phase != 'paused', q.reason
        if position == [180, 24]:
            assert action is None
            break
        assert action and action['kind'] == 'move'
        q.sent(action,now)
        position = action['position']
        if tuple(position) in links:
            source = tuple(position)
            crossed.append(source)
            # Estimated arrival is seen before the same-map teleport confirmation.
            # More than one relay tick may occur in this interval.
            for _ in range(3):
                now += .2
                assert q.plan('prt_sewb2.gat',position,c,guard,now) is None
                assert q.phase == 'travel', q.reason
            position = list(links[source])
            q.observe([dict(kind='map_change',map='prt_sewb2.gat',position=position)],1,'prt_sewb2.gat',now)
    else:
        pytest.fail('sewer trip did not finish')
    assert crossed == [(20,175), (101,176)]


def test_inner_portal_that_never_warps_times_out_instead_of_waiting_forever(tmp_path):
    from tests.test_inner_portal_routes import corridors
    c = corridors()
    guard = PortalGuard(tmp_path/'portais.json')
    guard.internal = {'sewer': {'2,18': [6,1], '6,18': [10,1]}}
    q = QuestRoutes()
    q.start_validation([dict(kind='portal',map='sewer',position=[10,17]),
                        dict(kind='wait_map',map='field')], 'field', 0, mode='travel', label='t')
    # Seed the path, then reach its first portal without receiving the warp packet.
    assert q.plan('sewer',[2,17],c,guard,1)['kind'] == 'move'
    assert q.plan('sewer',[2,18],c,guard,2) is None
    assert q.phase == 'travel'
    assert q.plan('sewer',[2,18],c,guard,18) is None
    assert q.phase == 'paused' and 'Portal interno' in q.reason
