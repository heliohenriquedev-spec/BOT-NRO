import copy
import pytest
from nrobot.combat_rotation import CombatRotation
from nrobot.summon_queue import SummonQueue


def p(identity, priority=0, duration=0, effect=0):
    return dict(skill_id=identity, role='summon', enabled=True, level=1, interval=.1,
                effect_id=effect, summon_priority=priority, summon_duration=duration)


def state(profiles, effects=None, sp=100):
    return dict(state='tracking', player_position_recent=True, player_position=[10,10],
                player_id=1, player_sp=sp, own_effects=effects or {}, own_cast_until=0,
                recent_entities=[], learned_skills=[dict(skill_id=x['skill_id'], level=1,
                range=4, sp_cost=1, target_flags=2) for x in profiles])


def ack(identity, success=True):
    return dict(kind='skill_no_damage', skill_id=identity, source_id=1, target_id=1, success=success)


def effect(identity, active):
    return dict(kind='status_effect', entity_id=1, effect_id=identity, active=active)


def test_queue_is_exclusive_even_in_burst_and_rotates_after_configured_lifetime():
    profiles=[p(700,2,10),p(701,1,10)]
    r=CombatRotation(profiles,burst=True)
    s=state(profiles)
    a=r.plan(s,0);assert a['skill_id']==701;r.sent(a,0)
    assert r.plan(s,.1) is None
    r.observe([ack(701)],1,.2)
    assert r.plan(s,5) is None
    a=r.plan(s,10.3);assert a['skill_id']==700;r.sent(a,10.3)
    r.observe([ack(700)],1,10.4)
    a=r.plan(s,20.5);assert a['skill_id']==701


def test_effect_end_is_authoritative_even_if_configured_timer_elapsed():
    profiles=[p(700,0,5,90),p(701,1,5,91)]
    r=CombatRotation(profiles);s=state(profiles)
    a=r.plan(s,0);r.sent(a,0)
    r.observe([effect(90,True)],1,.1)
    s['own_effects']={90:True}
    assert r.plan(s,20) is None
    r.observe([effect(90,False)],1,20.2);s['own_effects'][90]=False
    a=r.plan(s,20.3);assert a['skill_id']==701
    assert r.summons.learned['700:1']['last_observed_duration']==20.1


def test_learns_single_own_effect_after_ack_and_measures_actual_end():
    profiles=[p(700),p(701,1)]
    r=CombatRotation(profiles);s=state(profiles)
    a=r.plan(s,0);r.sent(a,0)
    r.observe([effect(92,True)],1,.05)
    r.observe([ack(700)],1,.1)
    s['own_effects']={92:True}
    assert r.plan(s,.7) is None
    assert r.summons.learned['700:1']['effect_id']==92
    r.observe([effect(92,False)],1,30.1);s['own_effects'][92]=False
    assert r.plan(s,30.2)['skill_id']==701
    assert r.summons.learned['700:1']['last_observed_duration']==30


@pytest.mark.parametrize('ambiguous',[True,False])
def test_does_not_bind_ambiguous_or_other_skill_effects(ambiguous):
    profiles=[p(700)];r=CombatRotation(profiles);s=state(profiles)
    r.sent(r.plan(s,0),0)
    events=[effect(92,True),effect(93,True)] if ambiguous else [effect(92,True),ack(800)]
    r.observe(events+[ack(700)],1,.1)
    s['own_effects']={92:True,93:True}
    r.plan(s,1)
    assert not r.summons.learned
    assert r.summons.active['effect_id']==0
    # Attribution window finishes; unrelated combat must not be frozen forever.
    assert r.summons.active['learn_until']==-1


def test_ground_animation_removal_is_not_summon_death():
    profiles=[p(700),p(701,1)]
    r=CombatRotation(profiles);s=state(profiles)
    a=r.plan(s,0);a['ground_position']=[11,10];r.sent(a,0)
    r.observe([dict(kind='ground_effect',effect_id=77,source_id=1,position=[11,10])],1,.1)
    r.observe([dict(kind='ground_effect_removed',effect_id=77)],1,.3)
    assert r.plan(s,100) is None
    assert r.summons.active['skill_id']==700 and not r.summons.learned


def test_refusal_tries_next_ready_summon_unknown_execution_does_not_duplicate():
    profiles=[p(700),p(701,1)]
    r=CombatRotation(profiles);s=state(profiles)
    r.sent(r.plan(s,0),0);r.observe([ack(700,False)],1,.1)
    assert r.plan(s,.2)['skill_id']==701
    r.sent(r.plan(s,.2),.2)
    assert r.plan(s,10) is None
    assert r.summons.active['confirmed'] is False
    assert r.plan(s,50) is None


def test_existing_linked_summon_survives_disabled_profile_and_config_changes():
    profiles=[p(700,effect=90),p(701,1)]
    r=CombatRotation(profiles);s=state(profiles,{90:True})
    assert r.plan(s,0) is None and r.summons.active['skill_id']==700
    r.profiles[0]['enabled']=False
    assert r.plan(s,100) is None
    r.observe([effect(90,False)],1,101);s['own_effects'][90]=False
    assert r.plan(s,102)['skill_id']==701
    assert not r.summons.learned  # activation start was not observed


def test_user_observed_end_teaches_fallback_but_not_a_fake_server_duration():
    profiles=[p(700)]
    r=CombatRotation(profiles);s=state(profiles)
    r.sent(r.plan(s,0),0);r.plan(s,2)
    r.summons.finish(30,'user_observed_end')
    assert r.summons.learned['700:1']['user_observed_duration']==30
    r.sent(r.plan(s,31),31);r.observe([ack(700)],1,31.1)
    assert r.plan(s,60) is None
    assert r.plan(s,61.2)['skill_id']==700


def test_cooldown_and_sp_can_leave_gap_without_illegal_recasts():
    profiles=[p(700,0,1),p(701,1,1)]
    r=CombatRotation(profiles);s=state(profiles)
    r.sent(r.plan(s,0),0);r.observe([ack(700)],1,.1)
    r.ready={700:20,701:20}
    assert r.plan(s,5) is None
    assert r.plan(state(profiles,sp=0),21) is None
    assert r.plan(s,21)['skill_id']==701


def test_map_change_clears_live_state_but_keeps_learned_duration():
    q=SummonQueue();q.learned={'700:1':{'effect_id':90}}
    q.reserve(p(700),0);q.start(.1,'skill_ack')
    q.observe([{'kind':'map_change'}],1,1)
    assert not q.active and not q.waiting and q.learned


def test_summon_configuration_fields_and_self_cast_type():
    from nrobot.packet_settings import validate
    entry=p(700,4,45)
    assert validate({'skill_profiles':[entry]})['skill_profiles'][0]==entry
    for key,value in [('summon_duration',-1),('summon_duration',float('nan')),('summon_priority',1.5)]:
        with pytest.raises(ValueError):validate({'skill_profiles':[{**entry,key:value}]})
    r=CombatRotation([entry]);s=state([entry]);s['learned_skills'][0]['target_flags']=4
    assert r.plan(s,0)['cast_mode']=='self'

def test_ui_marks_only_learned_kuchiyose_and_saves_queue_fields():
    import os
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from nrobot.skill_panel import SkillPanel
    app=QApplication.instance() or QApplication([])
    panel=SkillPanel()
    panel.local_names={'A':'Kuchiyose: Katsuyu','B':'Kuchiyose: Akino','C':'Armadilha'}
    meta=[dict(skill_id=i,level=1,range=4,sp_cost=1,target_flags=2,name=name) for i,name in ((700,'A'),(701,'B'),(702,'C'))]
    panel.update_catalog(meta,{})
    panel.enable_kuchiyose()
    panel.rows[700]['priority'].setValue(2)
    panel.rows[701]['priority'].setValue(1)
    panel.rows[701]['duration'].setValue(45)
    profiles=panel.profiles()
    assert [p['skill_id'] for p in profiles if p['enabled']]==[700,701]
    assert [p['skill_id'] for p in SummonQueue().ordered(profiles)]==[701,700]
    assert next(p for p in profiles if p['skill_id']==701)['summon_duration']==45
    old=panel.rows[701]['duration']
    panel.update_catalog(meta,{})
    assert panel.rows[701]['duration'] is old
    panel.close()


def test_corrupt_learning_cache_cannot_crash_duration_measurement():
    from nrobot.summon_queue import validated_learning
    assert validated_learning(None)=={}
    cache=validated_learning({'bad':{},'700:1':{'effect_id':90,'samples':None,'user_observed_duration':float('nan')},
                              '701:1':{'effect_id':'90'}})
    assert cache=={'700:1':{'effect_id':90,'samples':[]}}


def test_configuration_toggle_preserves_one_active_summon(tmp_path):
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_hunt import PacketHunt
    relay=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    relay.hunt=PacketHunt();relay.apply_settings({'skill_profiles':[p(700)]})
    q=relay.rotation.summons;q.reserve(p(700),0);q.start(.1,'skill_ack')
    relay.apply_settings({'skills':False,'skill_profiles':[p(700)]})
    assert relay.rotation is None
    relay.apply_settings({'skills':True,'skill_profiles':[p(700)]})
    assert relay.rotation.summons is q and q.active['skill_id']==700
