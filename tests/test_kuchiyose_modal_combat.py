import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import pytest
from nrobot.combat_rotation import CombatRotation
from nrobot.session_relay import SessionRelay
from nrobot.network_observer import Observer
from nrobot.skill_panel import SkillPanel
from nrobot.kuchiyose_dialog import KuchiyoseDialog
from PySide6.QtWidgets import QApplication, QDialog


def profile(i, priority, cooldown):
    return dict(skill_id=i,enabled=True,role='summon',level=1,interval=cooldown,effect_id=0,
                summon_priority=priority,summon_duration=1)


def state(profiles):
    return dict(state='tracking',player_position_recent=True,player_position=[10,10],player_id=1,
                player_sp=100,own_effects={},own_cast_until=0,
                recent_entities=[dict(entity_id=20,kind='monster',position=[12,10],position_age_seconds=.1)],
                learned_skills=[dict(skill_id=p['skill_id'],level=1,target_flags=2,range=4,sp_cost=1) for p in profiles])


@pytest.mark.parametrize('mode,expected',[('cycle',[700,701,702]),('priority',[700,701,700])])
def test_modal_queue_modes_choose_continuous_cycle_or_highest_ready(mode,expected):
    profiles=[profile(700,0,2),profile(701,1,10),profile(702,2,10)]
    r=CombatRotation(profiles);r.summons.mode=mode;s=state(profiles);ids=[]
    for now in (0,1.2,2.4):
        a=r.plan(s,now);ids.append(a['skill_id']);r.sent(a,now)
        r.observe([dict(kind='skill_no_damage',skill_id=a['skill_id'],source_id=1,target_id=1,success=True)],1,now+.01)
    assert ids==expected


@pytest.mark.parametrize('entity',[None,dict(entity_id=20,kind='player',position=[11,10]),
                                  dict(entity_id=20,kind='monster',position=[30,10]),
                                  dict(entity_id=20,kind='monster',position=[11,10],position_age_seconds=10)])
def test_kuchiyose_needs_recent_nearby_target_monster(entity):
    profiles=[profile(700,0,2)];s=state(profiles)
    s['recent_entities']=[entity] if entity else []
    assert CombatRotation(profiles).plan(s,0,20) is None


def test_animation_wait_is_ignored_but_server_cooldown_and_global_delay_remain():
    p=profile(700,0,1);p['role']='offensive'
    s=state([p]);s['learned_skills'][0]['target_flags']=1
    r=CombatRotation([p],ignore_animation=True)
    r.observe([dict(kind='normal_attack',source_id=1,target_id=20,source_motion_ms=30000)],1,0)
    a=r.plan(s,0,20);assert a
    r.sent(a,0)
    r.observe([dict(kind='skill_damage',skill_id=700,level=1,source_id=1,target_id=20,
                    damage_raw=100,source_motion_ms=30000),dict(kind='skill_cooldown',skill_id=700,duration_ms=2000)],1,.1)
    assert r.next_send < 1
    assert r.plan(s,1,20) is None
    assert r.plan(s,2.2,20)


def test_movement_survives_cast_and_skill_send_while_nonmovement_stays_gated(tmp_path):
    relay=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    relay.rotation=CombatRotation([profile(700,0,2)])
    relay.rotation.next_send=10;relay.tracker.observer.cast_until=20
    move={'kind':'move','purpose':'keep_distance'}
    assert relay.after_rotation_action(move,skill_sent=True,now=1) is move
    assert relay.after_rotation_action(move,now=1) is move
    assert relay.after_rotation_action({'kind':'attack'},now=1) is None
    assert relay.after_rotation_action({'kind':'attack'},attack_turn=True,now=1)
    observer=Observer({1037});observer.free_cast_movement=True
    observer.player_id=1;observer.player=[14,10];observer.player_at=0
    observer.player_motion=dict(origin=[10,10],destination=[14,10],at=0,duration=2)
    motion=observer.player_motion
    observer.apply(dict(kind='skill_cast',source_id=1,skill_id=700,duration_ms=2000),.1)
    assert observer.player_motion is motion
    assert observer.cast_until==2.1


def test_kuchiyose_only_editable_in_modal_save_cancel_and_persistence(monkeypatch):
    app=QApplication.instance() or QApplication([])
    panel=SkillPanel();panel.local_names={'A':'Kuchiyose: Katsuyu','B':'Kunai'}
    meta=[dict(skill_id=700,level=1,sp_cost=1,range=4,target_flags=2,name='A'),
          dict(skill_id=701,level=1,sp_cost=1,range=4,target_flags=1,name='B')]
    panel.update_catalog(meta,{})
    assert panel.table.isRowHidden(panel.rows[700]['index'])
    assert not panel.table.isRowHidden(panel.rows[701]['index'])
    before=copy.deepcopy(panel.profiles())
    monkeypatch.setattr(KuchiyoseDialog,'exec',lambda d:QDialog.Rejected)
    panel.open_kuchiyose();assert panel.profiles()==before
    def accept(d):
        assert set(d.rows)=={700}
        d.rows[700]['enabled'].setChecked(True)
        d.rows[700]['duration'].setValue(60)
        d.rows[700]['cooldown'].setValue(600)
        d.rows[700]['priority'].setValue(2)
        d.mode.setCurrentIndex(d.mode.findData('priority'))
        return QDialog.Accepted
    monkeypatch.setattr(KuchiyoseDialog,'exec',accept)
    panel.open_kuchiyose()
    p=next(p for p in panel.profiles() if p['skill_id']==700)
    assert p['enabled'] and p['role']=='summon' and p['summon_duration']==60 and p['interval']==600 and p['summon_priority']==2
    assert panel.summon_queue_mode=='priority'
    from nrobot.packet_settings import validate
    assert validate({'summon_queue_mode':panel.summon_queue_mode,'skill_profiles':panel.profiles()})['summon_queue_mode']=='priority'
    panel.close()
