import struct

from nrobot.npc_transports import NpcTransports, as_entries, purge, DISCARDED
from nrobot import shared_data

HEALER = {111757356: {'position': [25, 70], 'name': 'Medica#h1-2'}}


def click(t, opcode, identity=111757356, now=0.0):
    t.client(opcode, struct.pack('<HI', opcode, identity)+b'\0', 'hospital2', HEALER, now)


def test_walking_after_the_talk_is_a_portal_not_a_transport(tmp_path):
    t = NpcTransports(tmp_path/'t.json')
    click(t, 0x90)
    t.client(0xa7, b'\xa7\x00'+b'\0'*6, 'hospital2', HEALER, 1.0)  # walked to the portal
    t.observe([dict(kind='map_change', map='areia.gat', position=[179, 162])], 'hospital2', 3.0)
    assert not t.known.get('hospital2')
    click(t, 0x90, now=10.0)  # an NPC that really warps: no walk in between
    t.observe([dict(kind='map_change', map='areia.gat', position=[179, 162])], 'hospital2', 11.0)
    assert '25,70>areia>' in t.known['hospital2']


def test_forgotten_transport_is_listed_and_purged_everywhere(tmp_path):
    t = NpcTransports(tmp_path/'t.json')
    t.known = {'hospital2': {'25,70>areia>': dict(steps=[dict(kind='npc', map='hospital2.gat', position=[25, 70], name='Medica'),
                                                         dict(kind='wait_map', map='areia.gat')], to='areia', name='Medica')}}
    assert t.forget('hospital2.gat', [25, 70], 'areia.gat') == ['Medica'] and t.dirty
    assert not t.known['hospital2'] and '25,70>areia>' in t.known[DISCARDED]['hospital2']
    assert as_entries(t.known) == []
    # Another PC still has it: the shared discard list removes it there on merge.
    other = {'hospital2': {'25,70>areia>': {'steps': [{}], 'to': 'areia'}, '16,74>kakashi>Sim': {'steps': [{}], 'to': 'kakashi'}}}
    merged = shared_data.merge_portals(other, t.known)
    assert purge(merged) and list(merged['hospital2']) == ['16,74>kakashi>Sim']


def test_queue_drops_a_transport_that_did_not_change_the_map(tmp_path):
    from nrobot.quest_routes import QuestRoutes
    q = QuestRoutes.__new__(QuestRoutes)
    q.steps = [dict(kind='npc', map='hospital2.gat', position=[25, 70], name='Medica'), dict(kind='wait_map', map='areia.gat')]
    q.step = 1
    forgotten = []
    q.forget_transport = lambda m, p, to: forgotten.append((m, p, to)) or ['Medica']
    stops = []
    q.stop = stops.append
    assert q.false_transport(q.steps[1], 'hospital2.gat')
    assert forgotten == [('hospital2.gat', [25, 70], 'areia.gat')] and 'descartado' in stops[0]


def test_discards_survive_an_old_connection_rewriting_the_file(tmp_path, monkeypatch):
    import json
    from nrobot import npc_transports
    own, shared = tmp_path/'mapas.json', tmp_path/'shared.json'
    bad = {'steps': [{'kind': 'npc', 'map': 'hospital2.gat', 'position': [35, 76]}], 'to': 'areia'}
    own.write_text(json.dumps({'hospital2': {'35,76>areia>': bad}}), encoding='utf-8')  # rewritten, no list
    shared.write_text(json.dumps({DISCARDED: {'hospital2': {'35,76>areia>': 'curandeira'}}}), encoding='utf-8')
    monkeypatch.setattr(npc_transports, 'FILE', own)
    monkeypatch.setattr(npc_transports, 'SHARED_FILE', shared)
    t = NpcTransports(own)
    assert not t.known['hospital2'] and t.dirty
    t.save()
    saved = json.loads(own.read_text(encoding='utf-8'))
    assert not saved['hospital2'] and '35,76>areia>' in saved[DISCARDED]['hospital2']
    # An old process with the healer still in memory saves: the list on disk wins.
    old = NpcTransports(tmp_path/'other.json'); old.path = own
    old.known = {'hospital2': {'35,76>areia>': bad}}; old.dirty = True
    old.save()
    assert not json.loads(own.read_text(encoding='utf-8'))['hospital2']
