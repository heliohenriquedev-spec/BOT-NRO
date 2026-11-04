"""Walled-off maps (sewers): routes reach the way out through inner portals, saved with the route."""
from nrobot import map_routes
from nrobot.map_navigation import CollisionMap
from nrobot.portals import PortalGuard
from nrobot.quest_routes import QuestRoutes


def corridors():
    """Three vertical corridors (x=2, 6, 10), y 1..18, separated by walls."""
    width, height = 14, 21
    cells = [0]*(width*height)
    for x in (2, 6, 10):
        for y in range(1, 19):
            cells[y*width+x] = 1
    return CollisionMap(width, height, cells)


def routes():
    q = QuestRoutes.__new__(QuestRoutes)
    q.path_cache = None
    return q


def test_goal_past_inner_portals_walks_onto_the_first_one_of_the_chain():
    c = corridors()
    links = [((2, 18), (6, 1)), ((6, 18), (10, 1))]
    q = routes()
    path = q.path_to(c, (2, 1), (10, 17), True, links)
    assert path[-1] == (2, 18)
    q.path_cache = None
    path = q.path_to(c, (6, 1), (10, 17), True, links)  # after the first warp: the next portal
    assert path[-1] == (6, 18)
    q.path_cache = None
    assert q.path_to(c, (10, 1), (10, 17), True, links)[-1] == (10, 17)


def test_without_a_learned_link_the_goal_stays_unreachable():
    assert routes().path_to(corridors(), (2, 1), (10, 17), True, [((2, 18), (6, 1))]) is None


def test_saved_map_routes_carry_their_inner_portals_to_another_pc(tmp_path):
    here = PortalGuard(tmp_path/'a'/'portais.json')
    here.internal = {'prt_sewb2': {'20,175': [60, 28]}, 'outro': {'1,1': [9, 9]}}
    steps = [dict(kind='portal', map='areia.gat', position=[1, 1]), dict(kind='wait_map', map='prt_sewb2.gat'),
             dict(kind='portal', map='prt_sewb2.gat', position=[180, 24]), dict(kind='wait_map', map='prt_sewb4.gat')]
    entry = dict(name='Esgoto', target_map='prt_sewb4.gat', steps=steps, inner_portals=map_routes.inner_portals(steps, here))
    map_routes.save([entry], tmp_path/'rotas.json')
    saved = map_routes.load(tmp_path/'rotas.json')
    assert saved[0]['inner_portals'] == {'prt_sewb2': {'20,175': [60, 28]}}
    elsewhere = PortalGuard(tmp_path/'b'/'portais.json')
    map_routes.adopt_inner_portals(saved, elsewhere)
    assert elsewhere.links('prt_sewb2.gat') == [((20, 175), (60, 28))] and elsewhere.dirty
