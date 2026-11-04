"""Routes saved for every map passed."""
import time
from nrobot import map_routes


def test_recording_through_several_maps_saves_a_route_to_each_one(tmp_path):
    from nrobot.session_relay import SessionRelay
    r = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True); r.upstream = object()
    monkey = map_routes.FILE
    map_routes.FILE = tmp_path/'maps.json'
    try:
        o = r.tracker.observer; o.player_id = 1; o.player = [5, 5]; o.player_at = time.monotonic(); o.map_name = 'town'
        r.quest_control('quest_map_record', {}, lambda: True)
        q = r.quests
        for source, target, cell in (('town', 'field1', [3, 3]), ('field1', 'field2', [4, 4]), ('field2', 'dungeon', [9, 9])):
            q.append(dict(kind='portal', map=source, position=[1, 1]))
            q.observe([dict(kind='map_change', map=target, position=cell)], 1, source, time.monotonic())
        o.map_name = 'dungeon'; o.player = [9, 9]
        r.quest_control('quest_map_save', dict(name=''), lambda: True)
        targets = sorted(e['target_map'] for e in map_routes.load())
        assert targets == ['dungeon', 'field1', 'field2']
        o.map_name = 'town'; o.player = [5, 5]
        r.quest_control('quest_map_record', {}, lambda: True)  # recorded again: updated, not duplicated
        q.append(dict(kind='portal', map='town', position=[1, 1]))
        q.observe([dict(kind='map_change', map='field1', position=[3, 3])], 1, 'town', time.monotonic())
        o.map_name = 'field1'; o.player = [3, 3]
        r.quest_control('quest_map_save', dict(name=''), lambda: True)
        assert sorted(e['target_map'] for e in map_routes.load()) == ['dungeon', 'field1', 'field2']  # updated, no copy
    finally:
        map_routes.FILE = monkey


def test_each_map_passed_is_saved_with_the_name_typed_for_it(tmp_path):
    from nrobot.session_relay import SessionRelay
    r = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True); r.upstream = object()
    monkey = map_routes.FILE
    map_routes.FILE = tmp_path/'maps.json'
    try:
        o = r.tracker.observer; o.player_id = 1; o.player = [5, 5]; o.player_at = time.monotonic(); o.map_name = 'town'
        r.quest_control('quest_map_record', {}, lambda: True)
        q = r.quests
        for source, target in (('town', 'field1'), ('field1', 'dungeon')):
            q.append(dict(kind='portal', map=source, position=[1, 1]))
            q.observe([dict(kind='map_change', map=target, position=[3, 3])], 1, source, time.monotonic())
        assert q.snapshot()['recorded_maps'] == ['town', 'field1', 'dungeon']
        o.map_name = 'dungeon'; o.player = [9, 9]
        r.quest_control('quest_map_save', dict(name='Caverna', names={'field1': 'Campo', 'dungeon': 'Caverna'}), lambda: True)
        assert {e['target_map']: e['name'] for e in map_routes.load()} == {'field1': 'Campo', 'dungeon': 'Caverna'}
    finally:
        map_routes.FILE = monkey


def test_save_window_lists_each_map_with_its_monsters(monkeypatch):
    from PySide6.QtWidgets import QApplication, QDialog, QTableWidget
    from nrobot import quest_panel
    app = QApplication.instance() or QApplication([])
    panel = quest_panel.MapRoutesPanel()
    panel.recorded_maps = ['town', 'field1', 'dungeon']
    monkeypatch.setattr(quest_panel.MapRoutesPanel, 'monsters_on', staticmethod(lambda m: 'Morcego' if m == 'dungeon' else ''))
    sent, seen = [], {}
    panel.request = lambda command, **values: sent.append((command, values))

    def answer(dialog):
        table = dialog.findChild(QTableWidget)
        seen['rows'] = [(table.item(i, 0).text(), table.item(i, 2).text()) for i in range(table.rowCount())]
        table.cellWidget(1, 1).setText('Caverna')
        return QDialog.Accepted
    monkeypatch.setattr(QDialog, 'exec', answer)
    panel.finish()
    assert seen['rows'] == [('field1', 'nenhum monstro visto ainda neste mapa'), ('dungeon (destino)', 'Morcego')]
    assert sent == [('quest_map_save', dict(name='Caverna', names={'field1': '', 'dungeon': 'Caverna'}))]
