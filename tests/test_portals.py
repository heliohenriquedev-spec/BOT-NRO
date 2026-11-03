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


def test_arrival_and_own_cell_keep_the_way_out_open(tmp_path):
    guard = PortalGuard(tmp_path/'portais.json')
    guard.observe([warp(15, 15, species=139)], 'map', own_position=[17, 15])
    assert (17, 15) not in guard.cells('map') and (15, 15) in guard.cells('map')
    guard.observe([warp(5, 5)], 'map', own_position=[25, 25])
    guard.observe([{'kind': 'map_change', 'map': 'map', 'position': [7, 5]}], 'map')
    assert (7, 5) not in guard.cells('map') and (6, 5) in guard.cells('map')


def test_warp_portal_skill_is_avoided_until_it_closes(tmp_path):
    guard = PortalGuard(tmp_path/'portais.json')
    guard.observe([{'kind': 'ground_effect', 'effect_id': 9, 'source_id': 2000002, 'position': [8, 8],
                    'effect_type': 0x80, 'visible': True}], 'map')
    assert (8, 8) in guard.cells('map')
    assert guard.observe([{'kind': 'ground_effect_removed', 'effect_id': 9}], 'map')
    assert not guard.cells('map') and not guard.known
