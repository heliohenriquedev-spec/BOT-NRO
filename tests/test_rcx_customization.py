"""User appearance, learned-only previews and direct terrain channel regressions."""
import ctypes as C
import json
import struct
import time
from nrobot import rcx_settings
from nrobot.rcx_renderer import RcxRenderer, Shared
from nrobot.ground_cells import GroundCells
from nrobot.rcx_stream import Publisher, Reader


ON=dict(show_allies=True,show_enemies=True)


def all_on(config=None):
    """RCX acting on every effect for both sides (each skill starts with none since sides_version 2).
    Entries given explicitly keep their own sides."""
    config=dict(config or {});effects=dict(config.get('effects') or {})
    for row in rcx_settings.catalog():
        effects[str(row['unit_type'])]={**ON,**effects.get(str(row['unit_type']),{})}
    config['effects']=effects
    return config


def renderer(state, config=None, sides=True):
    r=RcxRenderer();r.shared=Shared();r.enabled=True
    if sides:config=all_on(config)
    if config:r.configure(config)
    r.update(state);r.feed();return r


def test_skill_colors_symbols_and_disabled_effect_survive_restart():
    value=rcx_settings.save({'effects':{'131':dict(show_allies=False,show_enemies=False)},'skill_styles':{'288':dict(fill='#27ab80',symbol='cross',opacity=40,radius=5,shape='square')}})
    assert rcx_settings.load()==value
    state={'ground_cells':{'map':'test','effects':[dict(position=[10,10],effect_type=157),dict(position=[11,10],effect_type=131)]}}
    r=renderer(state,rcx_settings.load())
    assert r.shared.count==1
    cell=r.shared.cells[0]
    assert cell.fill==rcx_settings.argb('#27ab80',40) and cell.symbol==2
    r.close()


def test_two_skills_sharing_unit_have_individual_appearance_when_identified():
    config=rcx_settings.validate({'skill_styles':{'89':dict(fill='#ff0000'), '85':dict(fill='#00ff00')}})
    r=renderer({'ground_cells':{'map':'test','effects':[dict(position=[10,10],effect_type=134,skill_id=89),dict(position=[11,10],effect_type=134,skill_id=85)]}},config)
    assert r.shared.cells[0].fill!=r.shared.cells[1].fill
    r.close()


def test_previews_only_use_learned_ground_skills_and_default_area_uses_level():
    config=rcx_settings.validate({})
    skills=[dict(skill_id=288,level=1,target_flags=2),dict(skill_id=89,level=0,target_flags=2),dict(skill_id=524,level=10,target_flags=1)]
    definitions=rcx_settings.preview_definitions(config,skills)
    assert [(d['skill_id'],d['radius']) for d in definitions]==[(288,3)]
    config['skill_styles']['288']=dict(radius=2,shape='diamond',area_override=True)
    assert rcx_settings.preview_definitions(config,skills)[0]['radius']==2


def test_own_cast_preview_expires_and_does_not_create_confirmed_units():
    g=GroundCells();now=time.monotonic()
    g.observe([dict(kind='skill_cast',source_id=1,skill_id=288,position=[10,10],duration_ms=3000)],own_id=1,now=now)
    assert g.snapshot()['cells']==[]
    assert g.snapshot()['casts'][0]['expires']==now+3
    state={'learned_skills':[dict(skill_id=288,level=1,target_flags=2)],'ground_cells':g.snapshot()}
    r=renderer(state)
    assert r.shared.count==49
    state['ground_cells']['casts'][0]['expires']=now-1
    r.feed();assert r.shared.count==0
    g.observe([dict(kind='skill_cast',source_id=2,skill_id=288,position=[20,20],duration_ms=3000)],own_id=1)
    assert len(g.casts)==1  # another caster cannot become the local aim preview
    g.observe([dict(kind='skill_failed',skill_id=288)],own_id=1)
    assert not g.casts
    r.close()


def test_direct_stream_updates_without_ui_refresh_and_stale_stream_clears(tmp_path):
    path=tmp_path/'ground.ipc';publisher=Publisher(path)
    publisher.publish(dict(map='test',cells=[]))
    r=renderer({'ground_cells':{'feed_ipc':str(path)}})
    try:
        publisher.publish(dict(map='test',effects=[dict(position=[10,10],effect_type=157)]))
        r.state_at=0  # a busy GUI does not interrupt a fresh independent relay stream
        r.feed();assert r.shared.count==1
        publisher.publish(dict(map='next',cells=[]))
        r.feed();assert r.shared.count==0 and r.shared.map_name==b'next'
        publisher.memory[12:16]=struct.pack('<I',(int(time.monotonic()*1000)-3000)&0xffffffff)
        r.feed();assert not r.shared.selection_preview
    finally:r.close();publisher.close()


def test_stream_ignores_incomplete_frame(tmp_path):
    path=tmp_path/'ground.ipc';publisher=Publisher(path);reader=Reader(path)
    try:
        publisher.publish({'cells':[[1,2]]});assert reader.read()['cells']==[[1,2]]
        publisher.memory[4:8]=struct.pack('<I',3)
        publisher.memory[16:30]=b'incomplete....'
        assert reader.read()['cells']==[[1,2]]
    finally:reader.close();publisher.close()


def test_panel_edits_one_skill_and_keeps_others_on_restart(tmp_path):
    from nrobot.rcx_panel import RcxPanel
    p=RcxPanel()
    p.update_state({'learned_skills':[dict(skill_id=288,level=5,target_flags=2,name='Proteger Terreno')]})
    p.only_learned.setChecked(True)
    assert p.current=='skill:288'
    p.symbol.setCurrentIndex(p.symbol.findData('diamond'));p.area_override.setChecked(True);p.radius.setValue(4);p.shutdown();p.close()
    saved=rcx_settings.load()
    assert saved['skill_styles']['288']['symbol']=='diamond' and saved['skill_styles']['288']['radius']==4
    q=RcxPanel();assert q.config==saved;q.close()


def test_area_spell_effect_expansion_is_preserved_with_per_skill_style():
    r=renderer({'ground_cells':{'map':'test','effects':[dict(effect_type=134,skill_id=89,position=[10,10],area=[10,10,4])]}})
    assert r.shared.count==81
    r.close()

def select_skill(panel, identity):
    for i in range(panel.effects.count()):
        item=panel.effects.item(i)
        if item.data(256)=='skill:'+str(identity):
            panel.effects.setCurrentItem(item)
            return
    raise AssertionError('skill not listed')


def test_edit_is_on_disk_immediately_without_waiting_for_timer_or_shutdown():
    from nrobot.rcx_panel import RcxPanel
    p=RcxPanel();select_skill(p,288)
    p.opacity.setValue(43)
    assert rcx_settings.load()['skill_styles']['288']['opacity']==43
    assert not p.save_timer.isActive()
    p.close()


def test_two_open_panels_do_not_erase_other_skill_preferences():
    from nrobot.rcx_panel import RcxPanel
    p=RcxPanel();q=RcxPanel()
    select_skill(p,288);select_skill(q,89)
    p.opacity.setValue(43);q.opacity.setValue(52)
    value=rcx_settings.load()
    assert value['skill_styles']['288']['opacity']==43
    assert value['skill_styles']['89']['opacity']==52
    p.close();q.close()


def test_two_open_panels_preserve_other_fields_on_same_skill():
    from nrobot.rcx_panel import RcxPanel
    p=RcxPanel();q=RcxPanel()
    select_skill(p,288);select_skill(q,288)
    p.set_color(p.fill,'#112233');p.edited()
    q.opacity.setValue(52)
    value=rcx_settings.load()['skill_styles']['288']
    assert value['fill']=='#112233' and value['opacity']==52
    p.close();q.close()


def test_renderer_failure_cannot_prevent_saving(monkeypatch):
    from nrobot.rcx_panel import RcxPanel
    p=RcxPanel();select_skill(p,288)
    def fail(value):raise ValueError('renderer unavailable')
    monkeypatch.setattr(p.renderer,'configure',fail)
    p.opacity.setValue(44)
    assert rcx_settings.load()['skill_styles']['288']['opacity']==44
    assert 'salvas' in p.save_status.text() and 'falha ao aplicar' in p.save_status.text()
    p.close()


def test_save_button_commits_typed_value_and_reload_matches():
    from nrobot.rcx_panel import RcxPanel
    p=RcxPanel();select_skill(p,288)
    p.opacity.setKeyboardTracking(False);p.opacity.lineEdit().setText('47')
    p.save_now_button.click()
    assert rcx_settings.load()['skill_styles']['288']['opacity']==47
    p.close()
    q=RcxPanel();select_skill(q,288);assert q.opacity.value()==47;q.close()

def test_further_edits_in_stale_panel_do_not_revert_merged_colors():
    from nrobot.rcx_panel import RcxPanel
    p=RcxPanel();q=RcxPanel();select_skill(p,288);select_skill(q,288)
    p.set_color(p.fill,'#112233');p.edited()
    q.opacity.setValue(51)
    q.opacity.setValue(52)
    assert q.fill.property('rcx_color')=='#112233'
    assert rcx_settings.load()['skill_styles']['288']['fill']=='#112233'
    p.close();q.close()


def test_normal_area_model_is_still_shown_after_changing_color():
    from nrobot.rcx_panel import RcxPanel
    p=RcxPanel();select_skill(p,288)
    radius=p.radius.value();shape=p.shape.currentData()
    p.set_color(p.fill,'#112233');p.edited()
    assert p.radius.value()==radius and p.shape.currentData()==shape
    assert not p.area_override.isChecked()
    p.close()

def test_save_error_keeps_edits_for_explicit_retry(monkeypatch):
    from nrobot.rcx_panel import RcxPanel
    p=RcxPanel();select_skill(p,288)
    original=rcx_settings.save
    def blocked(value):raise OSError('arquivo ocupado')
    monkeypatch.setattr(rcx_settings,'save',blocked)
    p.opacity.setValue(46)
    assert 'Falha ao salvar' in p.save_status.text()
    assert p.config['skill_styles']['288']['opacity']==46
    monkeypatch.setattr(rcx_settings,'save',original)
    p.save_now_button.click()
    assert rcx_settings.load()['skill_styles']['288']['opacity']==46
    p.close()

def test_further_edits_keep_per_skill_preview_preferences_from_other_panel():
    from nrobot.rcx_panel import RcxPanel
    p=RcxPanel();q=RcxPanel();select_skill(p,288);select_skill(q,288)
    p.set_color(p.preview_color,'#112233');p.edited()
    q.opacity.setValue(51);q.opacity.setValue(52)
    assert q.preview_color.property('rcx_color')=='#112233'
    assert rcx_settings.load()['skill_styles']['288']['preview_fill']=='#112233'
    p.close();q.close()


def test_immediate_save_keeps_normal_multidigit_keyboard_entry_working():
    from PySide6.QtTest import QTest
    from nrobot.rcx_panel import RcxPanel
    p=RcxPanel();select_skill(p,288)
    p.opacity.lineEdit().selectAll();QTest.keyClicks(p.opacity.lineEdit(),'47')
    assert p.opacity.value()==47
    assert rcx_settings.load()['skill_styles']['288']['opacity']==47
    p.close()

def test_desperado_is_included_as_self_skill_and_uses_its_own_visual_style():
    config=rcx_settings.validate({'skill_styles':{'516':dict(fill='#22aa66',outline='#ff0000',symbol='cross',opacity=60)}})
    learned=[dict(skill_id=516,level=10,target_flags=4)]
    definition=rcx_settings.preview_definitions(config,learned)[0]
    assert definition['skill_id']==516 and definition['self_centered'] and definition['radius']==3
    state={'learned_skills':learned,'ground_cells':{'map':'test','cells':[],
        'casts':[dict(skill_id=516,position=[20,20],expires=time.monotonic()+2)]}}
    r=renderer(state,config)
    assert r.shared.count==49 and r.shared.preview_count==0  # centred on caster, never mouse targeting
    assert r.shared.cells[0].fill==rcx_settings.argb('#22aa66',60)
    assert r.shared.cells[0].symbol==2
    config['skill_styles']['516']['fill']='#aa2266'
    r.configure(all_on(config))
    assert r.shared.cells[0].fill==rcx_settings.argb('#aa2266',60)
    r.close()


def test_desperado_native_request_uses_current_character_cell_without_confirming_cast(tmp_path):
    from nrobot.session_relay import SessionRelay
    r=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    o=r.tracker.observer;o.player_id=1;o.player=[20,30];o.player_at=time.monotonic()
    o.skills[516]=dict(skill_id=516,level=10,target_flags=4)
    assert not r.preview_rcx_self_skill(516,2,time.monotonic())
    assert r.preview_rcx_self_skill(516,1,time.monotonic())
    snapshot=r.ground_cells.snapshot()
    assert snapshot['requests'][0]['position']==[20,30] and snapshot['cells']==[] and not snapshot['casts']
    o.skills.clear()
    assert not r.preview_rcx_self_skill(516,1,time.monotonic())


def test_desperado_confirmed_unit_uses_the_announced_self_cast_area(tmp_path):
    from nrobot.session_relay import SessionRelay
    r=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    o=r.tracker.observer;o.player_id=1;o.player=[20,30];o.player_at=time.monotonic()
    o.skills[516]=dict(skill_id=516,level=10,target_flags=4)
    now=time.monotonic()
    assert r.preview_rcx_self_skill(516,1,now,confirmed=True)
    r.ground_cells.observe([dict(kind='ground_effect',effect_id=5,source_id=1,effect_type=134,position=[20,30],visible=True)],own_id=1,now=now+.1)
    snapshot=r.ground_cells.snapshot()
    assert len(snapshot['cells'])==49 and snapshot['effects'][0]['skill_id']==516
    assert not snapshot['casts']

def test_default_desperado_preview_inherits_effect_appearance():
    config=rcx_settings.validate({'preview_color':'#800002','skill_styles':{'516':dict(rcx_settings.DEFAULT_STYLE)}})
    definitions=rcx_settings.preview_definitions(config,[dict(skill_id=516,level=10,target_flags=4)])
    assert rcx_settings.preview_visual(config,definitions[0])[0]==rcx_settings.argb('#808080',70)


def test_native_desperado_frame_records_request_without_painting_or_sending_any_packet(tmp_path):
    from nrobot.session_relay import SessionRelay
    from nrobot.client_frame_guard import ClientFrameGuard
    from nrobot.packet_encoder import skill
    r=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    r.native_frames=ClientFrameGuard(fallback={0x72:25})
    o=r.tracker.observer;o.player_id=1;o.player=[20,30];o.player_at=time.monotonic()
    o.skills[516]=dict(skill_id=516,level=10,target_flags=4)
    published=[];r.publish_ground_cells=lambda:published.append(r.ground_cells.snapshot())
    r.inspect_native_frames(skill(1,516,10))
    assert published and published[0]['requests'][0]['skill_id']==516
    assert published[0]['requests'][0]['position']==[20,30] and not published[0]['casts']
    assert r.upstream is None

def test_editing_desperado_radius_automatically_enables_override_and_updates_rendering():
    from nrobot.rcx_panel import RcxPanel
    rcx_settings.save({'skill_styles':{'516':dict(show_allies=True)}})
    p=RcxPanel();select_skill(p,516)
    assert not p.area_override.isChecked() and p.radius.isEnabled()
    p.renderer.shared=Shared();p.renderer.enabled=True
    p.renderer.update({'learned_skills':[dict(skill_id=516,level=10,target_flags=4)],
        'ground_cells':dict(map='test',casts=[dict(skill_id=516,position=[20,20],expires=time.monotonic()+10)])})
    p.radius.setValue(5)
    assert p.area_override.isChecked() and p.renderer.shared.count==121
    assert rcx_settings.load()['skill_styles']['516']['radius']==5
    p.area_override.setChecked(False)
    assert p.radius.value()==3 and p.radius.isEnabled() and p.renderer.shared.count==49
    p.close()


def test_editing_shape_automatically_enables_override_and_survives_reopening():
    from nrobot.rcx_panel import RcxPanel
    p=RcxPanel();select_skill(p,516)
    p.shape.setCurrentIndex(p.shape.findData('diamond'))
    assert p.area_override.isChecked()
    p.close()
    q=RcxPanel();select_skill(q,516)
    assert q.area_override.isChecked() and q.shape.currentData()=='diamond'
    q.close()


def test_saving_typed_radius_activates_override_before_saving():
    from nrobot.rcx_panel import RcxPanel
    p=RcxPanel();select_skill(p,516)
    p.radius.setKeyboardTracking(False);p.radius.lineEdit().setText('6')
    p.save_now_button.click()
    saved=rcx_settings.load()['skill_styles']['516']
    assert saved['area_override'] and saved['radius']==6
    p.close()

def test_trap_aim_preview_is_ready_before_any_cast_packet_arrives():
    learned=[dict(skill_id=117,level=5,target_flags=2)]
    r=renderer({'learned_skills':learned,'ground_cells':{'map':'hospital2','effects':[],'casts':[]}})
    assert r.shared.selection_preview==1 and r.shared.preview_count==1
    definition=r.shared.previews[0]
    assert definition.skill_id==117 and definition.radius==1 and definition.shape==1
    assert r.shared.count==0  # no confirmed units or cast invented before clicking
    r.close()


def test_increasing_center_only_radius_switches_to_an_area_for_cursor_preview():
    from nrobot.rcx_panel import RcxPanel
    p=RcxPanel();select_skill(p,117)
    p.shape.setCurrentIndex(p.shape.findData('point'))
    p.radius.setValue(4)
    assert p.shape.currentData()=='square' and p.area_override.isChecked()
    saved=rcx_settings.load()
    definition=rcx_settings.preview_definitions(saved,[dict(skill_id=117,level=5,target_flags=2)])[0]
    assert definition['radius']==4 and len(list(rcx_settings.footprint(20,20,definition['radius'],definition['shape'])))==81
    p.close()


def test_disabling_aim_preview_does_not_invent_confirmed_units():
    r=renderer({'learned_skills':[dict(skill_id=117,level=5,target_flags=2)],'ground_cells':{'map':'test','cells':[]}})
    r.configure(rcx_settings.validate({'selection_preview':False}))
    assert r.shared.preview_count==0 and r.shared.count==0
    r.close()

def test_unacknowledged_ground_request_never_paints_and_failure_clears_request():
    g=GroundCells();now=time.monotonic();g.request_cast(117,[20,20],now)
    r=renderer({'learned_skills':[dict(skill_id=117,level=5,target_flags=2)],'ground_cells':g.snapshot()})
    assert r.shared.count==0 and not g.casts
    g.observe([dict(kind='skill_failed',skill_id=117)],own_id=1,now=now+.1)
    assert not g.requests and not g.casts
    r.close()


def test_cast_cancel_packet_removes_cast_area_immediately_but_not_real_units():
    from nrobot.packet_reader import decode
    g=GroundCells();now=time.monotonic()
    g.observe([dict(kind='skill_cast',skill_id=117,source_id=1,position=[20,20],duration_ms=5000),
        dict(kind='ground_effect',source_id=2,effect_id=5,effect_type=145,position=[30,30],visible=True)],own_id=1,now=now)
    assert g.casts
    cancel=decode(struct.pack('<HI',0x1b9,1))
    assert cancel['kind']=='skill_cast_cancel'
    g.observe([cancel],own_id=1,now=now+.1)
    assert not g.casts and not g.requests and g.snapshot()['cells']==[[30,30]]


def test_trap_active_area_is_3x3_and_configured_radius_updates_both_aim_and_active_model():
    r=renderer({'learned_skills':[dict(skill_id=117,level=5,target_flags=2)],
        'ground_cells':dict(map='test',effects=[dict(position=[20,20],effect_type=145)])})
    assert r.shared.count==9 and r.shared.previews[0].radius==1
    r.configure(all_on(rcx_settings.validate({'skill_styles':{'117':dict(radius=2,shape='square',area_override=True)}})))
    assert r.shared.count==25 and r.shared.previews[0].radius==2
    r.update({'ground_cells':dict(map='test',effects=[])})
    r.feed();assert r.shared.count==0
    r.close()


def test_skill_id_is_automatic_read_only_and_legacy_overrides_cannot_remap():
    from nrobot.rcx_panel import RcxPanel
    c=rcx_settings.validate({'effects':{'126':dict(skill_id=516)},'skill_styles':{'117':dict(skill_id=516)}})
    assert c['effects']['126']['skill_id']==0 and c['skill_styles']['117']['skill_id']==117
    definitions=rcx_settings.preview_definitions(c,[dict(skill_id=117,level=5,target_flags=2),dict(skill_id=516,level=10,target_flags=4)])
    assert next(d for d in definitions if d['skill_id']==117)['unit_type']==145
    p=RcxPanel();select_skill(p,117)
    assert p.skill_id.isReadOnly() and p.skill_id.value()==117
    select_skill(p,516);assert p.skill_id.value()==516
    p.close()

def test_preview_editor_is_below_effect_and_old_link_checkbox_is_removed():
    from nrobot.rcx_panel import RcxPanel
    from PySide6.QtWidgets import QCheckBox
    p=RcxPanel();select_skill(p,117)
    assert not any('Usar estas cores' in c.text() for c in p.findChildren(QCheckBox))
    parent=p.preview_box.parentWidget();layout=parent.layout()
    assert layout.itemAt(layout.indexOf(p.preview_box)-1).widget() is p.fill.parentWidget()
    assert p.preview_color.property('rcx_color')==p.fill.property('rcx_color')
    assert p.preview_outline.property('rcx_color')==p.outline.property('rcx_color')
    assert p.preview_symbol.currentData()==p.symbol.currentData()
    assert p.preview_opacity.value()==p.opacity.value()
    p.close()


def test_preview_appearance_inherits_until_customized_and_is_saved_per_skill():
    from nrobot.rcx_panel import RcxPanel
    p=RcxPanel();select_skill(p,117)
    p.set_color(p.fill,'#112233');p.edited()
    assert p.preview_color.property('rcx_color')=='#112233'
    p.set_color(p.preview_color,'#aabbcc');p.edited()
    p.set_color(p.fill,'#223344');p.edited()
    assert p.preview_color.property('rcx_color')=='#aabbcc'
    select_skill(p,516);assert p.preview_color.property('rcx_color')!='#aabbcc'
    p.close()
    q=RcxPanel();select_skill(q,117)
    assert q.preview_color.property('rcx_color')=='#aabbcc' and q.fill.property('rcx_color')=='#223344'
    q.close()


def test_each_skill_can_disable_aim_or_cast_without_disabling_confirmed_effects():
    c=rcx_settings.validate({'skill_styles':{'117':dict(selection_preview=False,cast_preview=False),
                                          '288':dict(selection_preview=True)}})
    r=renderer({'learned_skills':[dict(skill_id=117,level=5,target_flags=2),dict(skill_id=288,level=5,target_flags=2)],
        'ground_cells':dict(map='test',effects=[dict(position=[20,20],effect_type=145)],
            casts=[dict(skill_id=117,position=[30,30],expires=time.monotonic()+3)])},c)
    assert r.shared.count==9
    assert [p.skill_id for p in r.shared.previews[:r.shared.preview_count]]==[288]
    r.close()
