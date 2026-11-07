import time

from nrobot.ground_cells import GroundCells
from nrobot import rcx_settings
from test_rcx_customization import renderer
from test_bg_entry import relay


def cast(source,position,skill=288):
    return dict(kind='skill_cast',source_id=source,skill_id=skill,position=position,duration_ms=2000,level=1)


def test_other_cast_visible_without_learning_skill_and_cancel_is_scoped():
    g=GroundCells();now=time.monotonic()
    g.observe([cast(2,[10,10]),cast(3,[30,30])],own_id=1,now=now)
    assert len(g.snapshot()['casts'])==2 and g.snapshot()['cells']==[]
    r=renderer({'ground_cells':g.snapshot(),'learned_skills':[]})
    assert r.shared.count==98 and r.shared.preview_count==0
    g.observe([dict(kind='skill_cast_cancel',source_id=2)],own_id=1,now=now+.1)
    r.update({'ground_cells':g.snapshot()});r.feed()
    assert r.shared.count==49
    r.close()


def test_ally_enemy_filters_apply_to_casts_and_real_units_separately():
    g=GroundCells();now=time.monotonic()
    g.observe([cast(2,[10,10]),cast(3,[30,30])],own_id=1,now=now)
    data=g.snapshot();data.update(own_id=1,allied_ids=[2])
    data['effects']=[dict(position=[50,50],effect_type=157,source_id=2),dict(position=[60,60],effect_type=157,source_id=3)]
    config={'skill_styles':{'288':dict(show_allies=False,show_enemies=True)}}
    r=renderer({'ground_cells':data},config)
    assert r.shared.count==50
    assert any(r.shared.cells[i].x==60 and r.shared.cells[i].y==60 for i in range(r.shared.count))
    r.configure({'skill_styles':{'288':dict(show_allies=True,show_enemies=False)}})
    assert r.shared.count==50
    assert any(r.shared.cells[i].x==50 and r.shared.cells[i].y==50 for i in range(r.shared.count))
    r.configure({'skill_styles':{'288':dict(show_allies=False,show_enemies=False)}})
    assert r.shared.count==0
    r.close()


def test_older_skill_damage_does_not_cancel_new_cast_and_expiry_hides_it():
    g=GroundCells();now=time.monotonic()
    g.observe([cast(2,[10,10])],own_id=1,now=now)
    g.observe([dict(kind='skill_damage',source_id=2,skill_id=89)],own_id=1,now=now+.1)
    assert g.external_casts[2]['skill_id']==288
    data=g.snapshot();data['casts'][0]['expires']=now-1
    r=renderer({'ground_cells':data})
    assert r.shared.count==0
    r.close()


def test_existing_styles_start_with_both_filters_enabled_and_persist_changes():
    value=rcx_settings.save({'skill_styles':{'288':{'fill':'#123456'}}})
    style=rcx_settings.style_for(value,157,288)
    assert style['show_allies'] and style['show_enemies']
    value['skill_styles']['288']['show_enemies']=False
    rcx_settings.save(value)
    assert not rcx_settings.load()['skill_styles']['288']['show_enemies']


def test_relay_classifies_party_guild_and_own_sources(tmp_path):
    r=relay(tmp_path);r.registry.players.update({'1':{'party':'Grupo'},'2':{'party':'Grupo'},'3':{'party':'Outro'}})
    r.ground_cells.observe([cast(2,[10,10]),cast(3,[20,20])],own_id=1,now=time.monotonic())
    ground=r.rcx_ground_snapshot()
    assert ground['own_id']==1 and 2 in ground['allied_ids'] and 3 not in ground['allied_ids']


def test_rcx_panel_side_checkboxes_save_per_selected_skill():
    from PySide6.QtWidgets import QApplication
    from nrobot.rcx_panel import RcxPanel
    app=QApplication.instance() or QApplication([])
    panel=RcxPanel()
    assert panel.show_allies.isChecked() and panel.show_enemies.isChecked()
    key=panel.current;panel.show_allies.setChecked(False);panel.save_now()
    section='skill_styles' if key.startswith('skill:') else 'effects'
    assert rcx_settings.load()[section][key.split(':')[1]]['show_allies'] is False
    panel.close()
