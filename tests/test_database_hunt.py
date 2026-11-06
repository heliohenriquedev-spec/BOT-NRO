import pytest

from nrobot.database_hunt import DATABASE_HUNT, ENDLESS, database_hunt_route, monsters_by_map, routes_by_map

ROWS = [dict(species_id=1031, name='Deca', maps=['0045@tower.gat'], seen_maps=[]),
        dict(species_id=1447, name='Boa Hancock', maps=[], seen_maps=['0045@tower']),
        dict(species_id=1002, name='Poring', maps=['prt_fild08'], seen_maps=[])]
ENTRIES = [dict(id='r1', name='Torre', target_map='0045@tower.gat', steps=[dict(kind='walk', map='kakashi', position=[1, 1])])]


def test_monsters_and_recorded_paths_are_indexed_by_map():
    by_map = monsters_by_map(ROWS)
    assert [r['species_id'] for r in by_map['0045@tower']] == [1447, 1031]
    assert set(routes_by_map(ENTRIES)) == {'0045@tower'}


def test_hunt_route_uses_the_recorded_path_priorities_and_endless_kills():
    route = database_hunt_route(dict(target_map='0045@tower', species=[1031, 1447],
                                     priority={'1031': 2, '1447': 1, '9999': 3}, kills=0), ENTRIES)
    assert route['id'] == DATABASE_HUNT and route['map_route_id'] == 'r1' and route['kills'] == ENDLESS
    assert route['species'] == route['always_attack'] == [1031, 1447]
    assert route['attack_priority'] == {'1031': 2, '1447': 1}
    from nrobot import map_routes, quest_routes
    applied = map_routes.apply([route], ENTRIES)
    assert quest_routes.validate_routes(applied)[0]['steps'] == ENTRIES[0]['steps']


def test_hunt_route_explains_what_is_missing():
    with pytest.raises(ValueError, match='caminho conhecido'):
        database_hunt_route(dict(target_map='prt_fild08', species=[1002]), ENTRIES)
    with pytest.raises(ValueError, match='Marque'):
        database_hunt_route(dict(target_map='0045@tower', species=[]), ENTRIES)


def test_hunt_dialog_lists_the_map_monsters_and_sends_the_choice():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
    from nrobot.hunt_dialog import HuntDialog, LootDialog
    app = QApplication.instance() or QApplication([])
    sent = []

    class Owner(QWidget):
        def command(self, command, **values):
            sent.append((command, values))
    owner = Owner()
    drops = lambda species: [dict(item_id=7070, item_name='Casca Quebrada', rate=14.0)] if 1031 in species else []
    dialog = HuntDialog(owner, [1031], monsters=ROWS, entries=ENTRIES, drops=drops)
    assert dialog.map_box.currentData() == '0045@tower' and dialog.table.rowCount() == 2
    assert dialog.go.isEnabled() and dialog.item.count() == 2
    dialog.table.item(0, 1).setCheckState(Qt.Checked)  # Boa Hancock too
    dialog.table.cellWidget(0, 3).setValue(3)
    dialog.minutes.setValue(30)
    dialog.item.setCurrentIndex(1); dialog.amount.setValue(50)
    dialog.start()
    assert sent == [('quest_hunt_database', dict(target_map='0045@tower', map_route_id='r1', species=[1447, 1031],
                                                 priority={'1447': 3, '1031': 1}, kills=0, goal_minutes=30,
                                                 goal_item_id=7070, goal_item_amount=50, goal_item_name='Casca Quebrada'))]
    loot = LootDialog(dialog, ROWS[0], drops([1031]))
    loot.send_all(); loot.send('@autoloot 100')
    assert sent[1:] == [('loot_command', {'text': '@alootid +7070'}), ('loot_command', {'text': '@autoloot 100'})]
    owner.close()


def test_goals_end_the_hunt_by_time_or_items_gained_after_arriving():
    from nrobot.database_hunt import goal_reached
    route = database_hunt_route(dict(target_map='0045@tower', species=[1031], goal_minutes=10,
                                     goal_item_id=7070, goal_item_amount=5, goal_item_name='Casca'), ENTRIES)
    items = [dict(item_id=7070, amount=2)]
    assert goal_reached(route, items, 1000.0) is None  # clock and count start on the map
    assert goal_reached(route, [dict(item_id=7070, amount=6)], 1100.0) is None
    assert goal_reached(route, [dict(item_id=7070, amount=7)], 1200.0) == '5x Casca'
    assert goal_reached(dict(route, goal_item_id=0, goal_item_amount=0), items, 1600.0) == '10 min de caca'
    with pytest.raises(ValueError, match='quantidade'):
        database_hunt_route(dict(target_map='0045@tower', species=[1031], goal_item_id=7070), ENTRIES)


def test_only_loot_commands_reach_the_chat():
    from nrobot.database_hunt import loot_command
    assert loot_command(' @alootid  +501 ') == '@alootid +501'
    for text in ('@autoloot', '@autoloot 100', '@autoloot 0', '@alootid -501', '@alootid reset'):
        assert loot_command(text) == text
    for text in ('@warp prontera', '@alootid +501; @go 0', '@autoloot 1000', 'oi'):
        with pytest.raises(ValueError):
            loot_command(text)


def test_relay_starts_the_database_hunt_without_touching_the_queue_resume_point(tmp_path, monkeypatch):
    import time
    from nrobot import map_routes, quest_progress
    from nrobot.packet_hunt import PacketHunt
    from nrobot.session_relay import SessionRelay
    entry = dict(id='r1', name='Torre', target_map='ra_in01', steps=[dict(kind='walk', map='ra_in01', position=[219, 95])])
    map_routes.save([entry])
    quest_progress.save({'route_id': 'fila', 'route_name': 'Fila do usuario'})
    r = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True); r.hunt = PacketHunt(); r.apply_settings({})
    o = r.tracker.observer; o.player_id = 1; o.player = [219, 95]; o.player_at = time.monotonic(); o.map_name = 'ra_in01'
    r.upstream = object()
    r.quest_control('quest_hunt_database', dict(target_map='ra_in01', species=[1031], priority={'1031': 1}, kills=0), lambda: True)
    assert r.quests.active and r.quests.route['id'] == 'database_hunt' and r.quests.route['steps'] == entry['steps']
    r.save_progress(time.monotonic(), force=True)
    assert quest_progress.load()['route_id'] == 'fila'
    r.quest_control('quest_stop', {}, lambda: True)
    assert not r.quests.active


def test_loot_commands_are_queued_by_the_relay_and_bad_ones_refused(tmp_path):
    import json
    from nrobot.session_relay import SessionRelay
    r = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    for identity, text in ((1, '@alootid +7070'), (2, '@warp prontera')):
        (tmp_path/'comando.json').write_text(json.dumps(dict(id=identity, command='loot_command', text=text)), encoding='utf-8')
        r.process_control(lambda: True)
    assert r.loot_commands == ['@alootid +7070']
    assert not r.control_result['ok'] and 'loot' in r.control_result['message']
