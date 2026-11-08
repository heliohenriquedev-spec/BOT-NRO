"""Save point moved from hospital2 to hospital4 (nuvem): routes still found, Retorno still ends."""
from nrobot.auto_routes import edges
from nrobot.npc_transports import as_entries
from nrobot.portals import PortalGuard
from nrobot.quest_routes import QuestRoutes
from nrobot.shared_data import merge_destinations


def retorno(to):
    return dict(steps=[dict(kind='npc', map='kakashi.gat', position=[83, 150], name='Retorno#f'),
                       dict(kind='select', map='kakashi.gat', option='Sim'), dict(kind='wait_map', map=to+'.gat')],
                to=to, name='Retorno#f', arrival=[25, 92])


def test_npc_leading_to_different_maps_is_not_a_way():
    known = {'kakashi': {'83,150>hospital2>Sim': retorno('hospital2'), '83,150>hospital4>Sim': retorno('hospital4'),
                         '78,121>new_4-2>Sim': dict(retorno('new_4-2'), steps=[
                             dict(kind='npc', map='kakashi.gat', position=[78, 121]),
                             dict(kind='select', map='kakashi.gat', option='Sim'),
                             dict(kind='wait_map', map='new_4-2.gat')])}}
    assert [e['target_map'] for e in as_entries(known)] == ['new_4-2.gat']


def test_portal_seen_leading_to_two_maps_varies_and_is_skipped(tmp_path):
    guard = PortalGuard(tmp_path/'portais.json')
    guard.set_destination('payon_in03', [20, 60], 'nuvem', [74, 211], True)
    guard.set_destination('payon_in03', [20, 60], 'areia', [219, 241], True)
    assert guard.destination('payon_in03', [20, 60])['varies']
    guard.set_destination('payon_in03', [20, 60], 'areia', [219, 241], True)
    assert guard.destination('payon_in03', [20, 60])['varies']  # stays marked
    assert 'payon_in03' not in edges(guard.destinations)


def test_shared_merge_marks_a_portal_that_varies():
    mine = {'payon_in03': {'20,60': {'map': 'areia', 'arrival': [219, 241], 'confirmed': True}}}
    theirs = {'payon_in03': {'20,60': {'map': 'nuvem', 'arrival': [74, 211], 'confirmed': True}}}
    assert merge_destinations(mine, theirs)['payon_in03']['20,60']['varies']


def test_return_ends_on_any_save_point():
    q = QuestRoutes()
    q.phase = 'return';q.return_board = 'kakashi'
    q.library = dict(return_paths={'kakashi': dict(steps=[
        dict(kind='npc', map='kakashi.gat', position=[83, 150], name='Retorno#f'), dict(kind='next', map='kakashi.gat'),
        dict(kind='select', map='kakashi.gat', option='Sim'), dict(kind='wait_map', map='hospital2.gat'),
        dict(kind='walk', map='hospital2.gat', position=[25, 92])])})
    steps = q.itinerary('kakashi')
    assert [s['kind'] for s in steps] == ['npc', 'next', 'select', 'wait_transfer']


def test_quest_from_hospital4_goes_through_nuvem_sala_vip():
    q = QuestRoutes()
    route = dict(id='m', name='Mamute', target_map='ve_fild04.gat', needs_recording=False, steps=[
        dict(kind='portal', map='hospital2.gat', position=[103, 3]), dict(kind='wait_map', map='areia.gat'),
        dict(kind='npc', map='areia.gat', position=[144, 195], name='Sala Vip#2'),
        dict(kind='select', map='areia.gat', option='Sim'), dict(kind='wait_map', map='ra_in01.gat'),
        dict(kind='npc', map='ra_in01.gat', position=[217, 86], name='Viajante'),
        dict(kind='select', map='ra_in01.gat', option='Mamutes da Suna'), dict(kind='wait_map', map='ve_fild04.gat')])
    q.routes = [route];q.known_routes = [route];q.phase = 'travel'
    q.learned_portals = {'hospital4': {'103,3': {'map': 'nuvem', 'arrival': [54, 239], 'confirmed': True}},
                         'nuvem': {'74,208': {'map': 'payon_in03', 'arrival': [20, 63], 'confirmed': True}},
                         'payon_in03': {'20,60': {'map': 'areia', 'arrival': [219, 241], 'confirmed': True, 'varies': True}}}
    q.learned_transports = {'nuvem': {'238,105>ra_in01>Sim': dict(steps=[
        dict(kind='npc', map='nuvem.gat', position=[238, 105], name='Sala Vip#5'),
        dict(kind='select', map='nuvem.gat', option='Sim'), dict(kind='wait_map', map='ra_in01.gat')],
        to='ra_in01', arrival=[209, 90])}}
    maps = [s['map'] for s in q.itinerary('hospital4') if s['kind'] == 'wait_map']
    assert maps == ['nuvem.gat', 'ra_in01.gat', 've_fild04.gat']
