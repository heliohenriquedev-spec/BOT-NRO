from nrobot.npc_map import NpcMap, is_npc
from nrobot.portals import PortalGuard


def warp(identity, cell):
    return dict(kind='appearance', entity_id=identity, species_id=45, position=list(cell))


def test_crossing_a_portal_records_where_it_leads_and_the_way_back(tmp_path):
    guard = PortalGuard(tmp_path/'portais.json')
    guard.observe([warp(1, (50, 50))], 'hospital_areia', (47, 50))
    guard.observe([], 'hospital_areia', (49, 50))
    guard.observe([dict(kind='map_change', map='areia.gat', position=[120, 80])], 'hospital_areia', (120, 80))
    assert guard.destination('hospital_areia', (50, 50)) == {'map': 'areia', 'arrival': [120, 80], 'confirmed': True}
    # The portal next to the arrival spot appears after the map loads: it is the way back.
    guard.observe([warp(2, (122, 81))], 'areia.gat', (120, 80))
    back = guard.destination('areia', (122, 81))
    assert back['map'] == 'hospital_areia' and back['arrival'] == [50, 50] and not back['confirmed']
    guard.save()
    again = PortalGuard(tmp_path/'portais.json')
    assert again.destination('areia', (122, 81))['map'] == 'hospital_areia'


def test_teleport_far_from_portals_records_nothing(tmp_path):
    guard = PortalGuard(tmp_path/'portais.json')
    guard.observe([warp(1, (50, 50))], 'mapa_a', (10, 10))
    guard.observe([], 'mapa_a', (10, 12))
    guard.observe([dict(kind='map_change', map='mapa_b', position=[5, 5])], 'mapa_a', (5, 5))
    guard.observe([warp(2, (6, 6))], 'mapa_b', (5, 5))
    assert guard.destinations == {}


def test_inferred_way_back_never_overwrites_a_seen_crossing(tmp_path):
    guard = PortalGuard(tmp_path/'portais.json')
    guard.set_destination('b', (6, 6), 'c', (1, 1), True)
    guard.observe([warp(1, (50, 50))], 'a', (49, 50))
    guard.observe([dict(kind='map_change', map='b', position=[5, 5])], 'a', (5, 5))
    guard.observe([warp(2, (6, 6))], 'b', (5, 5))
    assert guard.destination('b', (6, 6))['map'] == 'c'


def test_npcs_are_recorded_with_names_and_warps_or_monsters_are_not(tmp_path):
    npcs = NpcMap(tmp_path/'npcs.json')
    entities = [dict(entity_id=111000001, species_id=739, position=[10, 20], name='Médica#h1-2'),
                dict(entity_id=111000002, species_id=45, position=[30, 30]),
                dict(entity_id=111000003, species_id=1031, position=[40, 40]),
                dict(entity_id=2000556, species_id=9, position=[50, 50])]
    assert [is_npc(e) for e in entities] == [True, False, False, False]
    npcs.observe(entities, 'hospital2.gat')
    npcs.observe([dict(entity_id=111000009, species_id=843, position=[1, 2])], 'hospital2.gat')
    npcs.observe([dict(entity_id=111000009, species_id=843, position=[1, 2], name='Campo de Treinamento#c')], 'hospital2.gat')
    npcs.learn_steps([dict(kind='npc', map='hospital2.gat', position=[3, 4], name='Ichiraku')])
    assert sorted(npcs.for_map('hospital2'), key=lambda n: n['position']) == [
        {'position': [1, 2], 'name': 'Campo de Treinamento'}, {'position': [3, 4], 'name': 'Ichiraku'},
        {'position': [10, 20], 'name': 'Médica'}]
    npcs.save()
    assert NpcMap(tmp_path/'npcs.json').for_map('hospital2.gat')


def test_a_long_walk_into_the_portal_is_learned_from_the_walk_destination(tmp_path):
    guard = PortalGuard(tmp_path/'portais.json')
    guard.observe([warp(1, (103, 3))], 'hospital2', (103, 30))
    guard.observe([], 'hospital2', (103, 30), (103, 4))  # last position known: 27 cells away, walking to the portal
    guard.observe([dict(kind='map_change', map='areia.gat', position=[150, 20])], 'hospital2', (150, 20), None)
    assert guard.destination('hospital2', (103, 3))['map'] == 'areia'


def test_relay_order_new_map_already_current_when_the_change_arrives(tmp_path):
    """The relay updates its current map before the guard sees the change (kakashi -> areia bug)."""
    guard = PortalGuard(tmp_path/'portais.json')
    guard.observe([warp(1, (52, 2))], 'kakashi.gat', (52, 20))
    guard.observe([], 'kakashi.gat', (52, 20), (52, 3))
    guard.observe([dict(kind='map_change', map='areia.gat', position=[100, 240])], 'areia.gat', (100, 240), None)
    assert guard.destination('kakashi', (52, 2)) == {'map': 'areia', 'arrival': [100, 240], 'confirmed': True}
    assert 'areia' not in guard.internal  # not mistaken for an inner portal of the new map
    guard.observe([warp(2, (101, 242))], 'areia.gat', (100, 240))
    assert guard.destination('areia', (101, 242))['map'] == 'kakashi'


def test_a_confirmed_crossing_removes_a_false_inner_portal(tmp_path):
    (tmp_path/'portais_internos.json').write_text('{"kakashi": {"52,2": [112, 62]}}', encoding='utf-8')  # old bug
    guard = PortalGuard(tmp_path/'portais.json')
    assert guard.internal == {'kakashi': {'52,2': [112, 62]}}
    guard.observe([warp(1, (52, 2))], 'kakashi.gat', (52, 4))
    guard.observe([dict(kind='map_change', map='areia.gat', position=[100, 240])], 'areia.gat', (100, 240))
    assert 'kakashi' not in guard.internal and (52, 2) not in {c for c, _ in guard.links('kakashi')}
    guard.save()
    import json
    assert json.loads((tmp_path/'portais_internos.json').read_text(encoding='utf-8')) == {}
