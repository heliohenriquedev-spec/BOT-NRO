from nrobot.map_navigation import CollisionMap
from nrobot.portals import MARGIN, PortalGuard


def open_field(size=30):
    return CollisionMap(size, size, [1]*size*size)


def warp(x, y, species=45):
    return {'kind': 'appearance', 'entity_id': 110000500, 'species_id': species, 'position': [x, y], 'object_type': 6}


def test_routes_never_cross_a_portal_area(tmp_path):
    guard = PortalGuard(tmp_path/'portais.json')
    assert guard.observe([warp(15, 15)], 'prt_fild01', own_position=[2, 15])
    collision = open_field()
    collision.set_forbidden(guard.cells('prt_fild01'))
    route = collision.route((2, 15), (27, 15))
    assert route and all(max(abs(x-15), abs(y-15)) > MARGIN for x, y in route)
    assert not collision.segment((11, 15), (12, 15))  # a single step into the area is refused too
    guard.save()
    # Remembered per map: avoided as soon as the map loads again.
    assert PortalGuard(tmp_path/'portais.json').cells('prt_fild01.gat') == guard.cells('prt_fild01')
    assert not PortalGuard(tmp_path/'portais.json').cells('other_map')


def test_arrival_keeps_corridors_open_but_never_shrinks_an_area_proved_by_a_warp(tmp_path):
    from nrobot.map_navigation import CollisionMap
    guard = PortalGuard(tmp_path/'portais.json')
    # prt_sewb4: landing 2 cells from its portal in a narrow corridor; the way out must stay open.
    guard.observe([warp(99, 94, species=45)], 'prt_sewb4', own_position=[101, 94])
    guard.observe([{'kind': 'map_change', 'map': 'prt_sewb4', 'position': [101, 94]}], 'prt_sewb4')
    assert (101, 93) not in guard.cells('prt_sewb4')
    # gl_sew02: an accidental warp 2 cells away proved its area; arriving there never shrinks it again.
    guard.observe([warp(29, 275, species=45)], 'gl_sew02', own_position=[31, 275])
    guard.widen('gl_sew02', [[31, 275], [31, 274]])
    guard.observe([{'kind': 'map_change', 'map': 'gl_sew02', 'position': [31, 275]}], 'gl_sew02')
    cells = guard.cells('gl_sew02')
    assert (31, 274) in cells and (31, 275) in cells
    guard.save()
    assert PortalGuard(tmp_path/'portais.json').cells('gl_sew02') == cells  # remembered
    collision = CollisionMap(300, 300, [1]*90000)
    collision.set_forbidden(cells)
    route = collision.route((31, 275), (31, 262))
    assert route and all(point not in cells for point in route[1:])  # starts inside, never steps in again


def test_warp_portal_skill_is_avoided_until_it_closes(tmp_path):
    guard = PortalGuard(tmp_path/'portais.json')
    guard.observe([{'kind': 'ground_effect', 'effect_id': 9, 'source_id': 2000002, 'position': [8, 8],
                    'effect_type': 0x80, 'visible': True}], 'map')
    assert (8, 8) in guard.cells('map')
    assert guard.observe([{'kind': 'ground_effect_removed', 'effect_id': 9}], 'map')
    assert not guard.cells('map') and not guard.known


def test_inner_portal_is_learned_freed_and_used_by_the_patrol(tmp_path):
    import random
    from nrobot.map_navigation import CollisionMap
    from nrobot.packet_patrol import PacketPatrol
    from nrobot.portals import PortalGuard
    guard = PortalGuard(tmp_path/'portais.json')
    guard.observe([{'kind': 'appearance', 'entity_id': 1, 'species_id': 45, 'position': [20, 10]}], 'ygg', own_position=[10, 10])
    assert (20, 10) in guard.cells('ygg')
    guard.observe([], 'ygg', own_position=[20, 11])  # standing on the portal
    guard.observe([{'kind': 'map_change', 'map': 'ygg.gat', 'position': [50, 50]}], 'ygg', own_position=[50, 50])
    assert guard.links('ygg') == [((20, 10), (50, 50))] and (20, 10) not in guard.cells('ygg')
    guard.observe([{'kind': 'map_change', 'map': 'ygg.gat', 'position': [5, 5]}], 'ygg', own_position=[5, 5])
    assert len(guard.links('ygg')) == 1  # a random teleport far from portals is not a link
    guard.save(); assert PortalGuard(tmp_path/'portais.json').links('ygg') == [((20, 10), (50, 50))]
    # Two halves of a map split by a wall; the inner portal leads to the other half.
    cells = bytearray([1]*(70*70))
    for y in range(70):
        cells[y*70+35] = 0
    collision = CollisionMap(70, 70, cells); collision.links = ((20, 10), (50, 50)),
    patrol = PacketPatrol(rng=random.Random(2), spacing=10)
    patrol.switch_map(collision, [10, 10])
    assert any(p[0] > 35 for p in patrol.tour.points.values())  # the other side is part of the patrol
    beyond = next(b for b, p in patrol.tour.points.items() if p[0] > 40)
    patrol.remaining = {beyond}; patrol.done = set(patrol.tour.points)-{beyond}
    action = patrol.plan([18, 10], 0, 100, collision)
    assert patrol.tour.portal_on_way([18, 10], beyond) == (20, 10)
    assert action['destination'] == [20, 10]  # walks onto the portal to get there
