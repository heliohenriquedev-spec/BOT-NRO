"""Hunting map paths, smart walking, monsters learned at pickup, delivery proved by the slots."""
import copy
import os
import time
import pytest
from nrobot import quest_library as lib, map_routes, quest_daily
from nrobot.map_navigation import CollisionMap
from nrobot.portals import PortalGuard
from nrobot.quest_routes import QuestRoutes
from tests.test_quest_pickup_model import MODEL, BOARD, Board, slots

OPEN = CollisionMap(64, 64, [1]*4096)


def walk_route():
    return [dict(kind='walk', map='town', position=[5, 5]), dict(kind='walk', map='town', position=[10, 5]),
            dict(kind='walk', map='town', position=[20, 5]), dict(kind='walk', map='town', position=[30, 5]),
            dict(kind='portal', map='town', position=[40, 5]), dict(kind='wait_map', map='field'),
            dict(kind='walk', map='field', position=[9, 9])]


def travel(steps=None):
    q = QuestRoutes()
    q.start_validation(steps or walk_route(), 'field', 0, mode='travel', label='t')
    return q


def test_walks_straight_to_the_portal_instead_of_every_recorded_click(tmp_path):
    q = travel()
    action = q.plan('town', [5, 5], OPEN, PortalGuard(tmp_path/'p'), 1)
    assert q.step == 4 and q.steps[q.step]['kind'] == 'portal' and action['kind'] == 'move'


def test_after_a_teleport_resumes_from_the_closest_recorded_point(tmp_path):
    # The portal side is not reachable on the known map: follow the recording from the closest point.
    walls = [1]*4096
    for y in range(64):
        walls[y*64+35] = 0
    q = travel()
    q.plan('town', [29, 6], CollisionMap(64, 64, walls), PortalGuard(tmp_path/'p'), 1)  # landed near [30,5]
    assert q.step == 3


def test_arriving_on_the_hunting_map_ends_the_trip_without_walking_the_recorded_tail(tmp_path):
    q = travel()
    q.observe([dict(kind='map_change', map='field', position=[50, 50])], 1, 'town', 1)
    q.step = 5
    q.plan('field', [50, 50], OPEN, PortalGuard(tmp_path/'p'), 2)
    q.plan('field', [50, 50], OPEN, PortalGuard(tmp_path/'p'), 3)
    assert q.phase == 'done' and q.validation['completed']


def test_map_routes_are_saved_applied_to_routes_and_used_as_connections(tmp_path, monkeypatch):
    monkeypatch.setattr(map_routes, 'FILE', tmp_path/'maps.json')
    saved = map_routes.save([dict(name='', target_map='field', steps=walk_route()),
                             dict(name='Volta', target_map='town', steps=[dict(kind='portal', map='field', position=[1, 1]), dict(kind='wait_map', map='town')])])
    assert saved[0]['name'] == 'town → field' and saved[0]['start_map'] == 'town'
    route = dict(name='R', map_route_id=saved[0]['id'], steps=[], target_map='')
    map_routes.apply([route])
    assert route['steps'] == walk_route() and route['target_map'] == 'field'
    q = QuestRoutes(); q.map_routes = saved
    assert q.connection('field', 'town')[-1] == dict(kind='wait_map', map='town')


def test_relay_records_and_saves_a_hunting_map_path(tmp_path, monkeypatch):
    from nrobot.session_relay import SessionRelay
    monkeypatch.setattr(map_routes, 'FILE', tmp_path/'maps.json')
    r = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True); r.upstream = object()
    o = r.tracker.observer; o.player_id = 1; o.player = [5, 5]; o.player_at = time.monotonic(); o.map_name = 'town'
    r.quest_control('quest_map_record', {}, lambda: True)
    assert r.quests.recording['scope'] == 'map'
    with pytest.raises(ValueError, match='portal'):
        r.quest_control('quest_map_save', {}, lambda: True)
    r.quests.observe([dict(kind='map_change', map='field', position=[9, 9])], 1, 'town', time.monotonic())
    o.map_name = 'field'; o.player = [9, 9]
    r.quest_control('quest_map_save', dict(name='Campo'), lambda: True)
    entry = map_routes.load()[0]
    assert entry['name'] == 'Campo' and entry['target_map'] == 'field' and r.quests.recording is None


def library(*missions, delivery=True):
    model = copy.deepcopy(MODEL)
    templates = {'pickup': dict(steps=model, confirmation='')}
    if delivery:
        templates['delivery'] = dict(steps=[
            dict(kind='npc', map='ra_in01.gat', position=[219, 95], name='Quadro de missões#3'), dict(kind='next', map='ra_in01.gat'),
            dict(kind='select', map='ra_in01.gat', option='Completar missão'), dict(kind='select', map='ra_in01.gat', option='#1 ^0000FFRank A-1^000000'),
            dict(kind='next', map='ra_in01.gat'), dict(kind='select', map='ra_in01.gat', option='Sim'), dict(kind='close', map='ra_in01.gat')],
            confirmation='Você precisa matar todos os monstros da lista')  # recorded before killing: never trusted
    return lib.validate(dict(missions=[dict(id=i, name=n, menu_option=n, board_id='vip') for i, n in missions],
                             board_templates={'vip': templates}))


class DeliveryBoard(Board):
    """The same board, also answering "Completar missao"."""
    def __init__(self, q, taken, unfinished=()):
        super().__init__(q, 'ra_in01', [219, 96]); self.taken = dict(taken); self.unfinished = set(unfinished); self.mode = None

    def run(self, limit=300):
        menu = None
        for _ in range(limit):
            self.t += 1
            action = self.q.plan(self.map, self.position, None, self.p, self.t)
            if not self.q.active or self.q.phase in ('return', 'travel'): return
            if action is None: continue
            self.q.sent(action, self.t); self.sent.append(action); kind = action['kind']
            if kind == 'npc': self.say(dict(action='next')); menu = 'start'
            elif kind == 'next' and menu == 'start':
                self.say(dict(action='menu', options=['Completar missão', 'Desistir de uma missão', 'Aceitar uma missão', ''])); menu = 'main'
            elif kind == 'select' and menu == 'main': self.say(dict(action='menu', options=slots(*self.taken.items()))); menu = 'slots'
            elif kind == 'select' and menu == 'slots':
                self.slot = action['choice']; self.say(dict(action='next')); menu = 'confirm'
            elif kind == 'next' and menu == 'confirm': self.say(dict(action='menu', options=['Sim', 'Não'])); menu = 'yes'
            elif kind == 'select' and menu == 'yes':
                if self.taken.get(self.slot) in self.unfinished:
                    self.say(dict(action='text', text='Você precisa matar todos os monstros da lista'), dict(action='close'))
                else:
                    self.taken.pop(self.slot, None); self.say(dict(action='text', text='Missão completada!'), dict(action='close'))
                menu = None
            elif kind in ('close', 'cancel'): menu = None


def test_every_mission_is_delivered_with_the_one_recorded_delivery_and_proved_by_the_slot():
    d = library(('a', 'Rank A-1'), ('b', 'Rank A-2'))
    q = QuestRoutes(); q.start_validation([], 'ra_in01', 0, mode='delivery', label='t', library=d, mission_ids=['a', 'b'])
    q.actors[BOARD] = dict(position=[219, 95], name='Quadro de missões#3')
    board = DeliveryBoard(q, {1: 'Rank A-1', 2: 'Rank A-2'}); board.run()
    assert board.taken == {} and q.phase == 'return' and q.completed_missions['delivery'] == ['a', 'b']
    assert sorted(q.daily_marks) == [('vip', 'Rank A-1'), ('vip', 'Rank A-2')]
    assert sum(a['kind'] == 'npc' for a in board.sent) == 3  # A proved by B's slot menu


def test_unfinished_mission_is_not_delivered_and_says_monsters_are_missing():
    d = library(('a', 'Rank A-1'))
    q = QuestRoutes(); q.start_validation([], 'ra_in01', 0, mode='delivery', label='t', library=d, mission_id='a')
    q.actors[BOARD] = dict(position=[219, 95], name='Quadro de missões#3')
    board = DeliveryBoard(q, {1: 'Rank A-1'}, unfinished={'Rank A-1'}); board.run()
    assert q.phase == 'paused' and 'faltam monstros' in q.reason and board.taken == {1: 'Rank A-1'}


def test_monsters_are_learned_from_the_board_when_taking_and_only_picked_ones_are_hunted(monkeypatch):
    import nrobot.monster_db as db
    monkeypatch.setattr(db, 'all_monsters', lambda: [dict(species_id=10, name='Gorila'), dict(species_id=11, name='Gremlin')])
    d = library(('s', 'Rank S-11'), ('b', 'Rank B-1'))
    route = dict(id='R', name='R', target_map='field', mission_ids=['s', 'b'], steps=[dict(kind='portal', map='ra_in01', position=[1, 1]), dict(kind='wait_map', map='field')])
    q = QuestRoutes(); q.start([route], 0, library=d)  # nothing known yet: allowed, read from the board
    q.actors[BOARD] = dict(position=[219, 95], name='Quadro de missões#3')

    class Describing(Board):
        def say(self, *events):
            extra = []
            for e in events:
                if e.get('text') == 'Rank B-1': extra.append(dict(action='text', text='Monstros necessários : 40 Gremlin'))
            super().say(*(list(events[:-1])+extra+[events[-1]]))
    board = Describing(q, 'ra_in01', [219, 96], done={'Rank S-11'})
    for _ in range(3):
        if q.phase == 'travel': break
        board.run()
        if q.phase == 'return':
            q.observe([dict(kind='map_change', map='hospital', position=[1, 1])], 1, 'ra_in01', board.t)
            q.return_seen = dict(map='hospital', at=board.t); q.steps = []; q.step = 0
            q.plan('hospital', [1, 1], None, board.p, board.t+1)
    assert q.phase == 'travel'
    assert q.route['mission_ids'] == ['b'] and q.route['kill_targets'] == [dict(name='Gremlin', count=40, species=[11])]
    assert q.route['species'] == [11] and q.learned == ['b']


def test_editor_offers_every_board_option_and_flags_the_ones_done_today(tmp_path, monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from nrobot.quest_panel import RouteEditor
    monkeypatch.setattr(lib, 'FILE', tmp_path/'library.json'); monkeypatch.setattr(map_routes, 'FILE', tmp_path/'maps.json')
    monkeypatch.setattr(quest_daily, 'FILE', tmp_path/'daily.json')
    lib.save(dict(missions=[dict(id='a', name='Rank A-1', menu_option='Rank A-1', board_id='vip')],
                  menus={'vip': [['^0000FFRank D-1', 'Rank A-1', 'Rank S-11^000000'], ['Aceitar missão', 'Escolher outra']]}))
    quest_daily.mark('vip', 'Rank S-11')
    saved = map_routes.save([dict(name='Campo', target_map='field', steps=walk_route())])
    app = QApplication.instance() or QApplication([])
    editor = RouteEditor(dict(name='Rota', mission_ids=[], steps=[], species=[], kills=1), {})
    texts = [editor.mission_list.item(i).text() for i in range(editor.mission_list.count())]
    assert len(texts) == 3 and any('Rank D-1' in t for t in texts) and not any('Escolher' in t for t in texts)
    assert any('Rank S-11' in t and 'concluida hoje' in t for t in texts)
    for i in range(editor.mission_list.count()):
        if 'Rank D-1' in editor.mission_list.item(i).text(): editor.mission_list.item(i).setCheckState(Qt.Checked)
    editor.name.setText('Rota'); editor.map_route.setCurrentIndex(editor.map_route.findData(saved[0]['id'])); editor.accept()
    created = [m for m in lib.load()['missions'] if m['name'] == 'Rank D-1']
    assert len(created) == 1 and editor.route['mission_ids'] == [created[0]['id']] and editor.route['target_map'] == 'field'
    editor.close()


def test_relay_saves_learned_monsters_and_missions_done_today(tmp_path, monkeypatch):
    from nrobot.session_relay import SessionRelay
    monkeypatch.setattr(lib, 'FILE', tmp_path/'library.json'); monkeypatch.setattr(quest_daily, 'FILE', tmp_path/'daily.json')
    lib.save(dict(missions=[dict(id='b', name='Rank B-1', board_id='vip')]))
    r = SessionRelay('127.0.0.1', folder=tmp_path)
    r.quests.library = lib.load(); m = r.quests.library['missions'][0]
    m.update(monster_targets=[dict(name='Gremlin', count=40)], monster_names=['Gremlin'], monster_ids=[1632])
    r.quests.learned.append('b'); r.quests.daily_marks.append(('vip', 'Rank B-1'))
    r.flush_daily()
    assert lib.load()['missions'][0]['monster_targets'] == [dict(name='Gremlin', count=40)]
    assert quest_daily.done_today('vip', 'Rank B-1') and not r.quests.daily_marks


def test_same_rank_label_from_the_other_board_is_not_taken_as_already_active():
    # Kakashi Rank A-1 (Gremlin) is in slot 1; the Sala Vip Rank A-1 (Louva-a-Deus) is another mission.
    d = library(('vip-a1', 'Rank A-2'))
    q = QuestRoutes(); q.start_validation([], 'ra_in01', 0, mode='pickup', label='t', library=d, mission_id='vip-a1')
    q.slot_owner = {1: 'kakashi-a1'}
    q.actors[BOARD] = dict(position=[219, 95], name='Quadro de missões#3')
    board = Board(q, 'ra_in01', [219, 96]); board.taken = {1: 'Rank A-2'}; board.run()
    assert board.taken == {1: 'Rank A-2', 2: 'Rank A-2'} and q.completed_missions['pickup'] == ['vip-a1']
    assert q.slot_owner == {1: 'kakashi-a1', 2: 'vip-a1'} and q.slots_dirty


def test_delivery_picks_the_slot_of_this_board_mission():
    d = library(('vip-a1', 'Rank A-1'))
    q = QuestRoutes(); q.start_validation([], 'ra_in01', 0, mode='delivery', label='t', library=d, mission_id='vip-a1')
    q.slot_owner = {1: 'kakashi-a1', 2: 'vip-a1'}
    q.actors[BOARD] = dict(position=[219, 95], name='Quadro de missões#3')
    board = DeliveryBoard(q, {1: 'Rank A-1', 2: 'Rank A-1'}); board.run()
    assert board.taken == {1: 'Rank A-1'} and q.phase == 'return' and q.slot_owner == {1: 'kakashi-a1'}


def test_kakashi_missions_are_taken_first():
    d = library(('v', 'Rank A-1'), delivery=True)
    d['missions'].append(dict(d['missions'][0], id='k', board_id='kakashi')); d = lib.validate(d)
    route = dict(id='R', name='R', target_map='field', species=[1], mission_ids=['v', 'k'],
                 steps=[dict(kind='portal', map='ra_in01', position=[1, 1]), dict(kind='wait_map', map='field')])
    q = QuestRoutes(); q.start([route], 0, library=d)
    assert q.route['mission_ids'] == ['k', 'v'] and q.current_mission['id'] == 'k'


def test_path_is_searched_once_and_followed_while_on_it(monkeypatch):
    q = travel(); c = q.navigation('town', OPEN, PortalGuard(), dict(kind='walk', position=[60, 60]))
    calls = []
    original = CollisionMap.route
    monkeypatch.setattr(CollisionMap, 'route', lambda self, *a, **k: calls.append(1) or original(self, *a, **k))
    path = q.path_to(c, [5, 5], [60, 60], True)
    assert path and len(calls) == 1
    assert q.path_to(c, list(path[3]), [60, 60], True)[0] == path[3] and len(calls) == 1  # walking along it
    assert q.navigation('town', OPEN, PortalGuard(), dict(kind='walk', position=[1, 1])) is c  # map kept
    q.path_to(c, [5, 50], [60, 60], True); assert len(calls) == 2  # teleported off the path: one new search


def test_unreachable_goal_is_refused_without_searching(monkeypatch):
    walls = [1]*4096
    for y in range(64):
        walls[y*64+32] = 0
    c = CollisionMap(64, 64, walls); q = travel()
    monkeypatch.setattr(CollisionMap, 'route', lambda *a, **k: pytest.fail('searched an unreachable goal'))
    assert q.path_to(c, [5, 5], [50, 5], True) is None


def test_saved_route_keeps_npcs_choices_and_each_map_way_out_only():
    steps = [dict(kind='walk', map='town', position=[5, 5]), dict(kind='walk', map='town', position=[9, 5]),
             dict(kind='portal', map='town', position=[20, 5]), dict(kind='wait_map', map='field'),
             dict(kind='walk', map='field', position=[3, 3]), dict(kind='npc', map='field', position=[8, 8], name='Viajante'),
             dict(kind='next', map='field'), dict(kind='select', map='field', option='Mamutes'),
             dict(kind='wait_map', map='hunt'), dict(kind='walk', map='hunt', position=[40, 40]), dict(kind='walk', map='hunt', position=[50, 50])]
    assert [(s['kind'], s['map']) for s in map_routes.compact(steps)] == [
        ('portal', 'town'), ('wait_map', 'field'), ('npc', 'field'), ('next', 'field'), ('select', 'field'),
        ('wait_map', 'hunt'), ('walk', 'hunt')]
    assert map_routes.compact(steps)[-1]['position'] == [50, 50]  # the destination stays


def test_compact_route_is_walked_by_computed_paths(tmp_path):
    steps = map_routes.compact(walk_route())
    q = QuestRoutes(); q.start_validation(steps, 'field', 0, mode='travel', label='t')
    action = q.plan('town', [5, 5], OPEN, PortalGuard(tmp_path/'p'), 1)
    assert q.steps[q.step]['kind'] == 'portal' and action['kind'] == 'move'
