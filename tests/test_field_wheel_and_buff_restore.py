import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QScrollArea, QSpinBox, QComboBox
from nrobot.responsive_ui import install_field_wheel_guard


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('focused', [True, False])
def test_wheel_preserves_values_and_scrolls_page(app, focused):
    install_field_wheel_guard()
    page = QWidget();layout = QVBoxLayout(page)
    spin = QSpinBox();spin.setValue(42)
    combo = QComboBox();combo.addItems(['A','B','C']);combo.setCurrentIndex(1)
    layout.addWidget(spin);layout.addWidget(combo);page.setMinimumHeight(1600)
    scroll = QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page)
    scroll.resize(500,400);scroll.show();app.processEvents()
    for field in (spin,combo):
        if focused: field.setFocus()
        else: field.clearFocus()
        before = scroll.verticalScrollBar().value()
        wheel = QWheelEvent(QPointF(10,10),QPointF(20,20),QPoint(),QPoint(0,-120),
                            Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
        QApplication.sendEvent(field,wheel)
        assert spin.value() == 42 and combo.currentIndex() == 1
        assert scroll.verticalScrollBar().value() > before
    scroll.close()


def test_buff_link_survives_empty_profiles_and_rebuilt_catalog(app, tmp_path, monkeypatch):
    import nrobot.packet_settings as settings
    from nrobot.skill_panel import SkillPanel
    path = tmp_path/'config.json'
    monkeypatch.setattr(settings,'CONFIG',path)
    profile = dict(skill_id=29,role='buff',enabled=True,level=5,interval=.5,effect_id=12)
    settings.save({'skill_profiles':[profile]},path)
    settings.save({'skill_profiles':[]},path)
    skills = [dict(skill_id=29,level=5,sp_cost=30,range=9,target_flags=16,name='Chakra')]
    panel = SkillPanel();panel.update_catalog(skills,{})
    assert panel.profiles()[0]['effect_id'] == 12
    panel.rows[29]['enabled'].setChecked(False)
    panel.update_catalog([], {})
    panel.update_catalog(skills,{})
    assert panel.profiles()[0]['effect_id'] == 12
    assert not panel.profiles()[0]['enabled']
    panel.close()


def test_custom_install_path_restores_link_without_enabling_disabled_buff(tmp_path):
    from nrobot.packet_settings import read, save
    path = tmp_path/'painel_config.json'
    (tmp_path/'buffs_aprendidos.json').write_text(json.dumps({'29':345}))
    data = {'skill_profiles':[dict(skill_id=29,role='buff',enabled=False,effect_id=0)]}
    saved = save(data,path)
    assert saved['skill_profiles'][0]['effect_id'] == 345
    assert read(path)['skill_profiles'][0]['effect_id'] == 345
    assert not read(path)['skill_profiles'][0]['enabled']
