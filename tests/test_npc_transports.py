import struct

from nrobot.npc_transports import NpcTransports, as_entries
from nrobot.quest_routes import QuestRoutes

ACTORS = {111000050: dict(position=[144, 195], name='Sala Vip#2')}


def click(identity):
    return 0x90, struct.pack('<HIB', 0x90, identity, 1)


def menu(identity, choice):
    return 0xb8, struct.pack('<HIB', 0xb8, identity, choice)


def nxt(identity):
    return 0xb9, struct.pack('<HI', 0xb9, identity)


def learner(tmp_path):
    n = NpcTransports(tmp_path/'npc.json')
    n.client(*click(111000050), 'areia.gat', ACTORS, now=10)
    n.client(*nxt(111000050), 'areia.gat', ACTORS, now=11)
    n.observe([dict(kind='npc_dialog', entity_id=111000050, action='menu', options=['Sim', 'Nao'])], 'areia.gat', now=11.5)
    n.client(*menu(111000050, 1), 'areia.gat', ACTORS, now=12)
    n.observe([dict(kind='map_change', map='ra_in01.gat', position=[217, 90])], 'areia.gat', now=13)
    return n


def test_npc_conversation_followed_by_a_map_change_is_learned(tmp_path):
    n = learner(tmp_path)
    link = next(iter(n.known['areia'].values()))
    assert link['to'] == 'ra_in01' and link['arrival'] == [217, 90] and link['name'] == 'Sala Vip#2'
    assert [s['kind'] for s in link['steps']] == ['npc', 'next', 'select', 'wait_map']
    assert link['steps'][2]['option'] == 'Sim'
    n.save()
    assert NpcTransports(tmp_path/'npc.json').known == n.known


def test_cancel_or_slow_map_change_teaches_nothing(tmp_path):
    n = NpcTransports(tmp_path/'npc.json')
    n.client(*click(111000050), 'areia.gat', ACTORS, now=10)
    n.observe([dict(kind='npc_dialog', entity_id=111000050, action='menu', options=['Sim'])], 'areia.gat', now=10.5)
    n.client(*menu(111000050, 255), 'areia.gat', ACTORS, now=11)
    n.observe([dict(kind='map_change', map='ra_in01.gat', position=[1, 1])], 'areia.gat', now=12)
    n.client(*click(111000050), 'areia.gat', ACTORS, now=20)
    n.observe([dict(kind='map_change', map='ra_in01.gat', position=[1, 1])], 'areia.gat', now=60)  # walked to a portal later
    assert n.known == {}


def test_quests_and_bg_travel_through_learned_portals_and_npcs(tmp_path):
    n = learner(tmp_path)
    q = QuestRoutes()
    q.learned_transports = n.known
    q.learned_portals = {'hospital2': {'103,3': {'map': 'areia', 'arrival': [150, 20], 'confirmed': True}}}
    q.known_routes, q.map_routes, q.library = [], [], None
    steps = q.connection('hospital2', 'ra_in01')
    assert [s['kind'] for s in steps] == ['portal', 'wait_map', 'npc', 'next', 'select', 'wait_map']
    # BG entry recorded on ra_in01: from hospital2 the trip reaches the NPC and runs the conversation.
    bg = [dict(kind='walk', map='ra_in01.gat', position=[210, 90]),
          dict(kind='npc', map='ra_in01.gat', position=[215, 92], name='Batalha'), dict(kind='select', map='ra_in01.gat', option='4x4')]
    q.start_validation(bg, 'ra_in01.gat', 0, mode='travel', label='BG 4x4', connect_from='hospital2.gat')
    q.learned_transports = n.known
    q.learned_portals = {'hospital2': {'103,3': {'map': 'areia', 'arrival': [150, 20], 'confirmed': True}}}
    assert [s['kind'] for s in q.itinerary('hospital2.gat')][-3:] == ['walk', 'npc', 'select']


def test_learned_npcs_feed_the_automatic_routes():
    from nrobot.auto_routes import path
    known = {'areia': {'k': dict(steps=[dict(kind='npc', map='areia.gat', position=[1, 1], name='Vip'),
                                        dict(kind='wait_map', map='ra_in01.gat')], to='ra_in01', arrival=[5, 5], name='Vip')}}
    steps = path('areia', 'ra_in01', {}, as_entries(known))
    assert [s['kind'] for s in steps] == ['npc', 'wait_map', 'walk']
