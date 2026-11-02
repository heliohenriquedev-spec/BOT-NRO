import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication
from nrobot.skill_panel import SkillPanel


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def catalog():
    return [{'skill_id': 524, 'level': 10, 'sp_cost': 1, 'range': 6, 'target_flags': 1, 'name': 'NJ_KUNAI'},
            {'skill_id': 1, 'level': 9, 'sp_cost': 0, 'range': 0, 'target_flags': 0, 'name': 'NV_BASIC'},
            {'skill_id': 29, 'level': 0, 'sp_cost': 30, 'range': 9, 'target_flags': 16, 'name': 'AL_INCAGI'}]


def test_only_learned_skills_are_shown_and_passives_do_not_create_editors(app):
    panel = SkillPanel()
    panel.update_catalog(catalog(), {})
    assert panel.table.rowCount() == 2
    assert set(panel.rows) == {524}
    assert [panel.table.item(row, 1).text() for row in range(2)] == ['1', '524']
    assert panel.table.cellWidget(0, 0) is None
    assert [p['skill_id'] for p in panel.profiles()] == [524]
    panel.close()


def test_repeated_refresh_reuses_editors_status_items_and_unsaved_values(app):
    panel = SkillPanel()
    panel.update_catalog(catalog(), {})
    level = panel.rows[524]['level']
    level.setValue(5)
    index = panel.rows[524]['index']
    item = panel.table.item(index, 10)
    for _ in range(25):
        panel.update_catalog(catalog(), {})
    assert panel.rows[524]['level'] is level and level.value() == 5
    assert panel.table.item(index, 10) is item
    panel.close()


def test_skill_becoming_unavailable_removes_controls_but_keeps_its_setup(app):
    from nrobot.combat_rotation import CombatRotation
    panel = SkillPanel()
    skills = catalog()
    panel.update_catalog(skills, {})
    skills[0]['level'] = 0
    panel.update_catalog(skills, {})
    assert panel.table.rowCount() == 1 and not panel.rows
    assert panel.table.cellWidget(0, 0) is None
    kept = panel.profiles()  # REDE-78: another character's setup is not erased on save
    assert [p['skill_id'] for p in kept] == [524]
    rotation = CombatRotation(kept)
    state = {'state': 'tracking', 'player_position_recent': True, 'player_position': [10, 10], 'player_id': 1,
             'player_sp': 500, 'learned_skills': [], 'recent_entities': [{'entity_id': 20, 'position': [11, 10]}]}
    assert rotation.plan(state, 0, 20) is None  # never used by a character that lacks it
    panel.close()


def test_panel_global_delay_preserves_decimal_and_validates():
    from PySide6.QtWidgets import QApplication, QDoubleSpinBox
    from nrobot.packet_panel import PacketPanel
    from nrobot.packet_settings import validate
    app = QApplication.instance() or QApplication([])
    panel = PacketPanel()
    field = panel.combat_fields['skill_global_delay']
    assert isinstance(field, QDoubleSpinBox)
    field.setValue(.12)
    assert validate(panel.settings())['skill_global_delay'] == .12
    panel.close()


def test_learned_buff_is_enabled_once_and_user_uncheck_survives_refresh(app):
    panel = SkillPanel()
    skills = [{'skill_id':29, 'name':'AL_INCAGI', 'level':5, 'target_flags':16, 'sp_cost':30, 'range':9}]
    panel.update_catalog(skills, {})
    result = {'id':'learning-1', 'profile':{'skill_id':29, 'enabled':True, 'role':'buff', 'level':5, 'interval':.5, 'effect_id':12}}
    panel.receive_buff_learning(result)
    assert panel.rows[29]['enabled'].isChecked()
    panel.rows[29]['enabled'].setChecked(False)
    for _ in range(25):
        panel.update_catalog(skills, {12:True})
        panel.receive_buff_learning(result)
    assert not panel.rows[29]['enabled'].isChecked()
    assert not panel.profiles()[0]['enabled']
    panel.receive_buff_learning({**result, 'id':'learning-2'})
    assert panel.rows[29]['enabled'].isChecked()
    panel.close()


def test_panel_saves_edits_by_itself_and_restores_them(app, tmp_path, monkeypatch):
    import nrobot.packet_panel as panel_module
    import nrobot.packet_settings as settings_module
    config = tmp_path/'painel_config.json'
    monkeypatch.setattr(settings_module, 'CONFIG', config)
    monkeypatch.setattr(panel_module, 'save', lambda data, path=config: settings_module.save(data, path))
    monkeypatch.setattr(panel_module, 'read', lambda path=config: settings_module.read(path))
    monkeypatch.setattr(panel_module.PacketPanel, 'UI_FILE', tmp_path/'painel_ui.json')
    panel = panel_module.PacketPanel()
    panel.radius.setValue(33)
    panel.pause_players.setChecked(not panel.pause_players.isChecked())
    paused = panel.pause_players.isChecked()
    panel.priority_panel.minimap.setChecked(False)
    assert panel.save_timer.isActive()
    panel.close()  # pending save is written on close
    reopened = panel_module.PacketPanel()
    assert reopened.radius.value() == 33 and reopened.pause_players.isChecked() == paused
    assert not reopened.priority_panel.minimap.isChecked()
    reopened.close()
