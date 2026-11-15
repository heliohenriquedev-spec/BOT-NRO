import pytest

from nrobot import showmobs_cycle as sc
from nrobot.database_hunt import is_database_hunt
from nrobot.mob_scan import MobScan
from nrobot.quest_routes import QuestRoutes

DEST = {'hospital2': {'103,3': {'map': 'areia', 'arrival': [179, 162], 'confirmed': True}},
        'areia': {'153,21': {'map': 'moc_fild01', 'arrival': [235, 379], 'confirmed': True, 'varies': True},
                  '10,10': {'map': 'gef_fild04', 'arrival': [5, 5], 'confirmed': True}}}
CONFIG = {'save_map': 'hospital2', 'stages': [
    {'name': 'A', 'map': 'gef_fild04', 'species': 1083},
    {'name': 'B', 'map': 'moc_fild01', 'species': 1078, 'portal': {'map': 'areia', 'position': [153, 21]}}]}


def test_validate_rejects_bad_stage():
    with pytest.raises(ValueError):
        sc.validate({'save_map': 'hospital2', 'stages': [{'map': 'x', 'species': 'abc'}]})


def test_portal_override_uses_varying_exit():
    routes = sc.build_routes(sc.validate(CONFIG), DEST, [])
    assert [r['id'] for r in routes] == ['database_hunt#1', 'database_hunt#2']
    assert all(is_database_hunt(r) and r['cycle'] and r['kills'] == 1 for r in routes)
    assert routes[1]['steps'][-2:] == [dict(kind='portal', map='areia.gat', position=[153, 21]),
                                       dict(kind='wait_map', map='moc_fild01.gat')]


def test_unknown_map_is_an_error():
    with pytest.raises(ValueError):
        sc.build_routes(sc.validate({'save_map': 'hospital2', 'stages': [{'map': 'nowhere', 'species': 1}]}), DEST, [])


def test_queue_loops_and_uses_voltar_after_each_stage():
    q = QuestRoutes()
    q.extras = {'voltar_frame': 'f300'}  # @voltar learned, option off: the cycle still uses it
    q.start(sc.build_routes(sc.validate(CONFIG), DEST, []), 0.0)
    q.cycle = True
    seen = []
    for i in range(3):
        q.phase = 'hunt'
        q.finish_hunt(1.0+i)
        seen.append((q.route['name'], [e.kind for e in q.errands]))
        q.errands = []
    assert [s[0] for s in seen] == ['Ciclo 2/2: B', 'Ciclo 1/2: A', 'Ciclo 2/2: B']
    assert all(kinds == ['voltar'] for _, kinds in seen)


def test_cycle_scan_retries_fast_and_walks_to_a_lone_far_monster():
    scan = MobScan()
    scan.cycle = True
    assert scan.start('gef_fild04', [1083], 0.0, idle=True)
    scan.sent(1083, 0.0)
    scan.round_open = False  # answered: nothing marked yet
    assert not scan.start('gef_fild04', [1083], 20.0, idle=True, early=True)  # no early rounds in the cycle
    assert not scan.start('gef_fild04', [1083], MobScan.CYCLE_INTERVAL-1, idle=True)
    assert scan.start('gef_fild04', [1083], MobScan.CYCLE_INTERVAL+0.1, idle=True)
    scan.queue = []
    scan.mark_records = {('mark', 1, 1): ((300, 300), 1083)}
    scan.sent_at = -10
    found = scan.finish([10, 10], 100.0)
    assert found and found['position'] == [300, 300]


def test_cycle_hunts_mounted_and_dismounts_before_voltar():
    q = QuestRoutes()
    q.extras = {'voltar_frame': 'f300', 'mount_enabled': True, 'mount': {'item_id': 2643}, 'combat_items': [11484]}
    q.start(sc.build_routes(sc.validate(CONFIG), DEST, []), 0.0)
    q.cycle = True
    q.errands = []
    q.queue('gear', 1.0)  # arriving on the hunting map: no gear, stays mounted
    assert q.errands == []
    q.phase = 'hunt'
    q.finish_hunt(2.0)
    assert [e.kind for e in q.errands] == ['gear', 'voltar', 'mount']  # dismount, @voltar, mount for the trip


def wall_map():
    from nrobot.map_navigation import CollisionMap
    w, h = 60, 40
    cells = [1]*(w*h)
    for y in range(0, 35):
        cells[y*w+30] = 0  # a wall with a gap only at the bottom (y 35..39)
    for x in range(w):
        cells[(h-1)*w+x] = cells[x] = 0
    return CollisionMap(w, h, cells)


def test_high_jump_crosses_a_wall_when_it_saves_the_walk():
    from nrobot import high_jump
    c = wall_map()
    p = high_jump.plan(c, (25, 5), (35, 5), reach=10, jump_cost=10, min_saving=20)
    assert p is not None and p['landing'][0] > 30 > p['takeoff'][0]
    dx, dy = p['direction']
    assert [p['takeoff'][0]-dx, p['takeoff'][1]-dy] == p['prep']  # the last step turns the character
    assert [p['takeoff'][0]+10*dx, p['takeoff'][1]+10*dy] == p['landing']
    assert high_jump.plan(c, (25, 36), (35, 36), reach=10, min_saving=20) is None  # walking is short


def test_exact_jump_points_are_not_skipped_by_shortcut():
    q = QuestRoutes()
    q.steps = [dict(kind='walk', map='m.gat', position=[1, 1], exact=True),
               dict(kind='walk', map='m.gat', position=[2, 2], exact=True),
               dict(kind='jump', map='m.gat', position=[2, 2], landing=[12, 12], direction=[1, 1])]
    q.step = 0
    assert q.shortcut('m', (0, 0), None, None) is None


def test_after_a_hunt_map_jump_the_queue_hunts_again_keeping_kills():
    q = QuestRoutes()
    q.extras = {'voltar_frame': 'f300'}
    q.start(sc.build_routes(sc.validate(CONFIG), DEST, []), 0.0)
    q.cycle = True
    q.phase = 'hunt'
    q.kills = 0
    q.enter_stage('travel', 1.0)
    q.steps = []  # the jump steps already done
    q.errands = []
    q.plan('gef_fild04.gat', (40, 40), None, None, 2.0)
    assert q.phase == 'hunt' and q.errands == [] and q.route['name'] == 'Ciclo 1/2: A'


def test_start_away_from_save_point_dismounts_before_voltar_and_mounts_after():
    q = QuestRoutes()
    q.extras = {'voltar_frame': 'f300', 'mount_enabled': True, 'mount': {'item_id': 2643}, 'combat_items': [11484]}
    q.start(sc.build_routes(sc.validate(CONFIG), DEST, []), 0.0)  # travel: mount queued first
    q.cycle = True
    q.errands = [e for e in q.errands if e.kind != 'mount']
    q.queue('gear', 0.0, before_voltar=True)
    q.queue('voltar', 0.0, force=True)
    q.queue('mount', 0.0)
    assert [e.kind for e in q.errands] == ['gear', 'voltar', 'mount']


def test_start_keeps_the_chosen_stage_after_saving(monkeypatch, tmp_path):
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(sc, 'FILE', tmp_path/'ciclo.json')
    from nrobot import showmobs_cycle_panel
    import nrobot.hunt_dialog as hd
    sent = {}
    monkeypatch.setattr(hd, 'send_command', lambda w, c, **v: sent.update(command=c, **v) or True)
    panel = showmobs_cycle_panel.ShowmobsCyclePanel()
    panel.start_stage.setCurrentIndex(2)  # "2. Mamute Konoha"
    panel.start()
    assert sent == {'command': 'quest_showmobs_cycle', 'start_stage': 1}
    assert panel.start_stage.currentIndex() == 2


def test_jump_planning_waits_for_the_trip_steps():
    import asyncio
    from types import SimpleNamespace
    from nrobot.quest_relay import QuestRelay
    relay = object.__new__(QuestRelay)
    q = QuestRoutes()
    q.steps = None  # the itinerary is built on the stage's first plan
    relay.quests = q
    observer = SimpleNamespace(map_name='hospital2.gat', player=(10, 10), skills={})
    assert asyncio.run(relay.cycle_high_jump(0.0, observer, lambda: True)) is False


def test_stage_found_from_a_map_in_the_middle_of_its_way():
    routes = sc.build_routes(sc.validate(CONFIG), DEST, [])
    assert sc.stage_on_the_way(routes, 'areia') == 0  # the first stage's way passes through areia
    steps = sc.steps_from_here(sc.validate(CONFIG)['stages'][0], 'areia', DEST, [])
    assert steps and steps[0]['map'] == 'areia.gat'  # continues from here, no @voltar
    assert sc.steps_from_here(sc.validate(CONFIG)['stages'][0], 'nowhere', DEST, []) is None


def test_cycle_walks_to_a_mark_already_on_the_minimap():
    from types import SimpleNamespace
    from nrobot.session_relay import SessionRelay
    relay = object.__new__(SessionRelay)
    relay.mob_scan = MobScan()
    relay.viewpoint_marks = {(1, 1): {'position': [114, 203], 'species': None, 'at': 10.0}}
    relay.quest_missing_species = lambda: [1081]
    relay.record_hunt = lambda event: None
    observer = SimpleNamespace(player=(366, 197), map_name='yuno_fild08.gat')
    relay.cycle_mark_goal(20.0, observer)
    assert relay.mob_scan.goal == [114, 203]
    relay.mob_scan.goal = None
    relay.cycle_mark_goal(25.0, observer)  # the same mark is not taken again after arriving there
    assert relay.mob_scan.goal is None


def test_cycle_failed_round_keeps_minimap_goal():
    from nrobot.mob_scan import MobScan
    scan = MobScan()
    scan.cycle = True
    scan.map = 'prt_fild02.gat'
    scan.goal, scan.goal_until = [357, 246], 1e9
    scan.fail()
    assert scan.goal == [357, 246]
    assert not scan.map_failed('prt_fild02.gat')
    scan.cycle = False
    scan.fail()
    assert scan.goal is None
