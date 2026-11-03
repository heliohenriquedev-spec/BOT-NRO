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
                recent_entities=[dict(entity_id=20,position=[12,10],position_age_seconds=.1)], learned_skills=[dict(skill_id=x['skill_id'], level=1,
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


def test_linked_effect_can_end_earlier_than_configured_duration():
    profiles=[p(700,0,30,90),p(701,1,30,91)]
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
    assert r.plan(s,100) is None  # process the unanswered request
    assert r.plan(s,100.5)['skill_id']==700  # bounded probe, not an inferred death
    assert r.summons.active['skill_id']==700 and not r.summons.learned


def test_refusal_tries_next_ready_summon_unknown_execution_does_not_duplicate():
    profiles=[p(700),p(701,1)]
    r=CombatRotation(profiles);s=state(profiles)
    r.sent(r.plan(s,0),0);r.observe([ack(700,False)],1,.1)
    assert r.plan(s,.2)['skill_id']==701
    r.sent(r.plan(s,.2),.2)
    assert r.plan(s,10) is None
    assert r.summons.active['confirmed'] is False
    assert r.plan(s,50)['skill_id']==701  # retry only the same unconfirmed summon


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
    profiles={x['skill_id']:x for x in panel.profiles()}
    panel.apply_kuchiyose({i:{**profiles[i],'enabled':True,'summon_duration':0,'summon_priority':0} for i in (700,701)},'cycle')
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

def test_summon_maintenance_not_starved_by_unconfirmed_offensive_during_kite():
    profiles=[p(700,0,10)]
    offensive=dict(skill_id=800,role='offensive',enabled=True,level=1,interval=.1,effect_id=0)
    r=CombatRotation(profiles+[offensive]);s=state(profiles+[offensive])
    s['learned_skills'][1]['target_flags']=1
    r.sent({**offensive,'kind':'skill','target_id':20,'sp_cost':1},0)
    # Current position is near the enemy while the acknowledged destination is far away.
    s['player_position']=[30,30];s['combat_player_positions']=[[10,10],[10,11]]
    a=r.plan(s,.2,20)
    assert a['skill_id']==700 and a['cast_mode']=='ground'


def test_unknown_lifetime_probes_same_summon_only_after_interval():
    profiles=[p(700),p(701,1)]
    profiles[0]['interval']=30
    r=CombatRotation(profiles);s=state(profiles)
    r.sent(r.plan(s,0),0);r.plan(s,2)
    assert r.plan(s,29) is None
    a=r.plan(s,30.1)
    assert a['skill_id']==700
    r.sent(a,30.1)
    assert r.plan(s,31) is None
    assert r.plan(s,35) is None

def combat_with_summon(sp=100, reach=6):
    profiles=[p(700,0,10),dict(skill_id=800,role='offensive',enabled=True,level=1,interval=.1,effect_id=0)]
    s=state(profiles,sp=sp)
    s['learned_skills'][0]['sp_cost']=50
    s['learned_skills'][1].update(target_flags=1,range=reach,sp_cost=1)
    return CombatRotation(profiles),s


def test_maintenance_reserves_sp_instead_of_spending_it_on_offensives():
    r,s=combat_with_summon(sp=40)
    assert r.summon_maintenance_required(s,0,20)
    assert r.plan(s,0,20) is None
    s['player_sp']=50
    assert r.plan(s,1,20)['role']=='summon'


def test_maintenance_waits_for_summon_cooldown_before_offensives():
    r,s=combat_with_summon();r.ready[700]=5
    assert r.plan(s,0,20) is None
    a=r.plan(s,5,20);assert a['role']=='summon';r.sent(a,5)
    assert r.plan(s,5.2,20) is None  # pending summon cannot be starved by another cast
    r.observe([ack(700)],1,5.3)
    assert not r.summon_maintenance_required(s,6,20)
    assert r.plan(s,6,20)['role']=='offensive'


def test_long_range_kite_approaches_summon_radius_then_resumes_offensive_range():
    from nrobot.packet_hunt import PacketHunt
    r,s=combat_with_summon(reach=24)
    s['recent_entities'][0]['position']=[30,10]
    assert r.engagement_range(s)==24
    assert r.navigation_range(s,0,20)==11
    s['engagement_range']=r.navigation_range(s,0,20)
    hunt=PacketHunt();hunt.auto_attacks=False;hunt.start()
    a=hunt.plan(s,0)
    assert a['kind']=='move' and a['destination'][0]>10
    # A confirmed summon restores ordinary ranged spacing.
    entry={**r.profiles[0],'kind':'skill','target_id':1,'sp_cost':50}
    r.sent(entry,0);r.observe([ack(700)],1,.1)
    assert r.navigation_range(s,1,20)==24


def test_summon_chooses_nearby_fresh_monster_if_locked_one_is_far():
    r,s=combat_with_summon()
    s['recent_entities'][0]['position']=[30,10]
    s['recent_entities'].append(dict(entity_id=21,kind='monster',position=[12,10],position_age_seconds=.1))
    assert r.plan(s,0,20)['combat_target_id']==21


def test_maintenance_blocks_basic_attack_but_keeps_retrieving_and_free_cast_movement(tmp_path):
    from nrobot.session_relay import SessionRelay
    relay=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    relay.rotation=CombatRotation([p(700)])
    assert relay.after_rotation_action({'kind':'attack'},summon_maintenance=True,attack_turn=True,now=0) is None
    move={'kind':'move','purpose':'keep_distance'}
    assert relay.after_rotation_action(move,summon_maintenance=True,now=0) is move
    assert relay.after_rotation_action(move,summon_maintenance=True,hold_movement=True,now=0) is None
    assert relay.after_rotation_action(move,summon_maintenance=True,skill_sent=True,now=0) is move


def test_ground_summon_checks_own_cell_without_requiring_monster_shot_line(tmp_path,monkeypatch):
    import asyncio,time,struct
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_hunt import PacketHunt
    from nrobot.network_targets import Entity
    from nrobot.map_navigation import CollisionMap
    relay=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    relay.hunt=PacketHunt();relay.hunt.start();relay.hunt.target=111000001
    relay.rotation=CombatRotation([p(700,0,10)])
    o=relay.tracker.observer;now=time.monotonic()
    o.player_id,o.player,o.player_at,o.sp=1,[10,10],now,100
    o.skills={700:dict(skill_id=700,level=1,sp_cost=1,range=4,target_flags=2)}
    o.registry.update(Entity(111000001,1051,12,10,now,'monster'))
    cells=bytearray([1])*900
    for y in range(30):cells[y*30+11]=0
    collision=CollisionMap(30,30,cells)
    assert not collision.line_clear([10,10],[12,10])
    monkeypatch.setattr(relay,'collision_map',lambda:collision)
    class Writer:
        def __init__(self):self.packets=[]
        def write(self,p):self.packets.append(p)
        async def drain(self):pass
    relay.upstream=Writer()
    action=relay.rotation.plan(relay.status(),now,111000001)
    assert asyncio.run(relay.send_rotation_action(action,game_gate=lambda:True))
    packet=relay.upstream.packets[0]
    point=[struct.unpack_from('<H',packet,12)[0],struct.unpack_from('<H',packet,20)[0]]
    assert collision.walkable(point) and collision.line_clear([10,10],point)

@pytest.mark.parametrize('mode',['cycle','priority'])
def test_duration_20_cooldown_46_switches_to_other_at_20_not_46(mode):
    profiles=[p(700,0,20),p(701,1,20)]
    for entry in profiles:entry['interval']=46
    r=CombatRotation(profiles);r.summons.mode=mode;s=state(profiles)
    a=r.plan(s,0);assert a['skill_id']==700;r.sent(a,0);r.observe([ack(700)],1,0)
    assert r.plan(s,19.99) is None
    a=r.plan(s,20);assert a['skill_id']==701
    status=r.snapshot(20)['summons']['cooldowns']
    assert status['700']['remaining_seconds']==26
    r.sent(a,20);r.observe([ack(701)],1,20)
    assert r.plan(s,39.99) is None
    assert r.plan(s,40) is None  # first recovers at 46, second at 66
    assert r.plan(s,45.99) is None
    a=r.plan(s,46);assert a['skill_id']==700  # NOT 66 (20+46)


def test_single_duration_20_cooldown_46_has_26_second_gap():
    entry=p(700,0,20);entry['interval']=46
    r=CombatRotation([entry]);s=state([entry])
    r.sent(r.plan(s,0),0);r.observe([ack(700)],1,0)
    assert r.plan(s,20) is None
    assert r.summons.active is None
    assert r.snapshot(20)['summons']['cooldowns']['700']['remaining_seconds']==26
    assert r.plan(s,46)['skill_id']==700


def test_modal_explains_single_summon_gap_and_displays_individual_cooldown():
    import os,time
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from nrobot.kuchiyose_dialog import KuchiyoseDialog
    app=QApplication.instance() or QApplication([])
    entry=p(700,0,20);entry['interval']=46
    dialog=KuchiyoseDialog([(700,'Kuchiyose A',entry)],runtime={'cooldowns':{'700':{'ready_at':time.monotonic()+26}}})
    assert '26s' in dialog.timing_note.text()
    assert float(dialog.table.item(0,5).text().split()[0]) > 25
    dialog.close()


@pytest.mark.parametrize('mode',['cycle','priority'])
def test_configured_duration_20_does_not_wait_for_cooldown_effect_46(mode):
    profiles=[p(700,0,20),p(701,1,20)]
    for entry in profiles:entry['interval']=46
    r=CombatRotation(profiles);r.summons.mode=mode
    # Historical automatic link might actually represent a 46s cooldown status.
    r.summons.learned={'700:1':{'effect_id':90},'701:1':{'effect_id':91}}
    s=state(profiles)
    r.sent(r.plan(s,0),0)
    r.observe([effect(90,True),ack(700)],1,0);s['own_effects'][90]=True
    assert r.plan(s,19.99) is None
    a=r.plan(s,20);assert a['skill_id']==701
    r.sent(a,20);r.observe([effect(91,True),ack(701)],1,20);s['own_effects'][91]=True
    assert r.plan(s,40) is None
    assert r.summons.active is None  # stale effect must not resurrect A or B
    assert r.plan(s,46)['skill_id']==700


def test_explicit_duration_ends_queue_occupation_even_with_manual_link_still_active():
    profiles=[p(700,0,20,90),p(701,1,20,91)]
    for entry in profiles:entry['interval']=46
    r=CombatRotation(profiles);s=state(profiles)
    r.sent(r.plan(s,0),0);r.observe([effect(90,True),ack(700)],1,0)
    s['own_effects'][90]=True
    assert r.plan(s,20)['skill_id']==701
    assert r.plan(s,20)['skill_id']==701  # repeated planning cannot restore expired A
    assert r.ready[700]==46
