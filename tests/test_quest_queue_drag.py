from PySide6.QtWidgets import QApplication, QListWidget
from PySide6.QtCore import Qt


def test_multiple_routes_move_as_a_block_and_keep_selection_and_enabled(tmp_path, monkeypatch):
    from nrobot import quest_panel as module
    from nrobot.quest_routes import save, load
    app = QApplication.instance() or QApplication([])
    path = tmp_path/'quests.json'
    save([dict(id=n, name=n, enabled=n!='B') for n in 'ABCD'], path)
    monkeypatch.setattr(module, 'load', lambda: load(path))
    monkeypatch.setattr(module, 'save', lambda data: save(data, path))
    panel = module.QuestPanel()
    try:
        assert panel.list.dragDropMode() == QListWidget.InternalMove
        assert panel.list.selectionMode() == QListWidget.ExtendedSelection
        panel.list.setCurrentRow(1)
        panel.list.item(2).setSelected(True)
        panel.reorder(1)
        assert [r['id'] for r in load(path)] == list('ADBC')
        assert {item.data(Qt.UserRole) for item in panel.list.selectedItems()} == {'B', 'C'}
        assert not next(r for r in load(path) if r['id']=='B')['enabled']
        # Feed the completed internal drop order to the same persistence handler as dropEvent.
        panel.list.blockSignals(True)
        moved = [panel.list.takeItem(2), panel.list.takeItem(2)]
        for index, item in enumerate(moved):
            panel.list.insertItem(index, item)
            item.setSelected(True)
        panel.list.blockSignals(False)
        panel.list.order_changed.emit()
        assert [r['id'] for r in load(path)] == list('BCAD')
        assert not load(path)[0]['enabled']
        panel.reload()
        assert [panel.list.item(i).data(Qt.UserRole) for i in range(4)] == list('BCAD')
        panel.update_state({'quests': {'phase': 'travel'}})
        assert not panel.list.isEnabled()
    finally:
        panel.close()


def test_invalid_drop_cannot_duplicate_or_lose_a_quest(tmp_path, monkeypatch):
    from nrobot import quest_panel as module
    from nrobot.quest_routes import save, load
    app = QApplication.instance() or QApplication([])
    path = tmp_path/'quests.json'
    save([dict(id=n, name=n) for n in 'AB'], path)
    monkeypatch.setattr(module, 'load', lambda: load(path))
    monkeypatch.setattr(module, 'save', lambda data: save(data, path))
    panel = module.QuestPanel()
    try:
        panel.list.blockSignals(True)
        panel.list.takeItem(1)
        panel.list.blockSignals(False)
        panel.dropped()
        assert [r['id'] for r in load(path)] == list('AB')
        assert panel.list.count() == 2
    finally:
        panel.close()
