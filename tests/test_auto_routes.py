from nrobot.auto_routes import path, reachable
from nrobot.database_hunt import database_hunt_route
from nrobot.portals import PortalGuard

DEST = {'hospital2': {'103,3': {'map': 'areia', 'arrival': [150, 20], 'confirmed': True}},
        'areia': {'150,18': {'map': 'hospital2', 'arrival': [103, 5], 'confirmed': False},
                  '10,100': {'map': 'deserto', 'arrival': [290, 100], 'confirmed': True}},
        'deserto': {'5,5': {'map': 'caverna', 'arrival': [20, 20], 'confirmed': True}}}


def test_the_way_is_built_from_the_portals_crossed():
    steps = path('hospital2.gat', 'caverna', DEST)
    assert steps == [dict(kind='portal', map='hospital2.gat', position=[103, 3]), dict(kind='wait_map', map='areia.gat'),
                     dict(kind='portal', map='areia.gat', position=[10, 100]), dict(kind='wait_map', map='deserto.gat'),
                     dict(kind='portal', map='deserto.gat', position=[5, 5]), dict(kind='wait_map', map='caverna.gat'),
                     dict(kind='walk', map='caverna.gat', position=[20, 20])]
    assert path('areia', 'hospital2', DEST)[0] == dict(kind='portal', map='areia.gat', position=[150, 18])  # inferred way back
    assert path('caverna', 'hospital2', DEST) is None  # never walked out of the cave
    assert reachable('hospital2', DEST) == {'hospital2', 'areia', 'deserto', 'caverna'}


def test_recorded_paths_with_npc_transports_join_the_learned_portals():
    entries = [dict(id='r', name='Vip', target_map='ra_in01.gat',
                    steps=[dict(kind='npc', map='areia.gat', position=[144, 195], name='Sala Vip'),
                           dict(kind='select', map='areia.gat', option='Sim'), dict(kind='wait_map', map='ra_in01.gat'),
                           dict(kind='walk', map='ra_in01.gat', position=[217, 90])])]
    steps = path('hospital2', 'ra_in01', DEST, entries)
    assert [s['kind'] for s in steps] == ['portal', 'wait_map', 'npc', 'select', 'wait_map', 'walk']


def test_crossing_portals_while_playing_feeds_the_routes(tmp_path):
    guard = PortalGuard(tmp_path/'portais.json')
    warp = lambda i, cell: dict(kind='appearance', entity_id=i, species_id=45, position=list(cell))
    guard.observe([warp(1, (103, 3))], 'hospital2', (103, 6))
    guard.observe([dict(kind='map_change', map='areia.gat', position=[150, 20])], 'hospital2', (150, 20))
    assert path('hospital2', 'areia', guard.destinations)[0]['position'] == [103, 3]


def test_database_hunt_uses_the_learned_way_without_a_recording():
    route = database_hunt_route(dict(target_map='caverna', species=[1031]), [], 'hospital2.gat', DEST)
    assert route['map_route_id'] == '' and route['steps'][-1] == dict(kind='walk', map='caverna.gat', position=[20, 20])
    here = database_hunt_route(dict(target_map='caverna', species=[1031]), [], 'caverna.gat', DEST, [30, 40])
    assert here['steps'] == [dict(kind='walk', map='caverna.gat', position=[30, 40])]
    from nrobot import quest_routes
    assert quest_routes.validate_routes([route])[0]['steps'] == route['steps']
    import pytest
    with pytest.raises(ValueError, match='portais'):
        database_hunt_route(dict(target_map='hospital2', species=[1031]), [], 'caverna', DEST)


def test_hunt_window_offers_maps_reached_by_learned_portals():
    from PySide6.QtWidgets import QApplication, QWidget
    from nrobot.hunt_dialog import HuntDialog
    app = QApplication.instance() or QApplication([])
    rows = [dict(species_id=1031, name='Deca', maps=['caverna', 'longe'], seen_maps=[])]
    owner = QWidget()
    dialog = HuntDialog(owner, [1031], monsters=rows, entries=[], drops=lambda s: [],
                        current_map='hospital2.gat', destinations=DEST)
    assert [dialog.map_box.itemData(i) for i in range(dialog.map_box.count())] == ['caverna', 'longe']
    assert 'aprendido' in dialog.map_box.itemText(0) and dialog.go.isEnabled()
    dialog.map_box.setCurrentIndex(1)
    assert not dialog.go.isEnabled() and 'sem caminho' in dialog.map_box.itemText(1)
    owner.close()
