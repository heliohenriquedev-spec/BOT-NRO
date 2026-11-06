import asyncio
import copy
import json
import time
from pathlib import Path
import pytest
from nrobot.map_combat import MapCombat,settings_for
from nrobot.combat_rotation import CombatRotation
from nrobot.packet_settings import DEFAULTS
from test_map_combat import state,entity

@pytest.fixture
def config():return json.loads(Path('exemplos/comportamentos/ra_fild03.json').read_text(encoding='utf-8'))['combat']

def setup(config,entities):
    s=state(entities)
    s.update(player_hp=500,player_max_hp=1000)
    s['learned_skills'] += [dict(skill_id=729,level=4,sp_cost=150,range=4,target_flags=2),
        dict(skill_id=357,level=3,sp_cost=22,range=0,target_flags=4),dict(skill_id=775,level=1,sp_cost=100,range=9,target_flags=4),dict(skill_id=370,level=10,sp_cost=350,range=2,target_flags=1)]
    s['own_effects'][105]=True
    c=MapCombat(config)
    settings=settings_for(config,DEFAULTS,s['learned_skills'])
    r=CombatRotation(settings['skill_profiles'],fast=True,priority=settings['skill_priority'],burst=settings['skill_burst'],burst_interval=settings['skill_burst_interval'])
    return c,r,s

def targeting(c,identity,now=100,target=1,kind='normal_attack'):
    c.observe([dict(kind=kind,source_id=identity,target_id=target)],1,now)

def test_only_close_observed_targeting_and_target_changes(config):
    # Isolate target evidence from the profile's Salamandra approach exception.
    config['engagement']['approach_species']=[]
    c,r,s=setup(config,[entity(10,1315),entity(11,1831)])
    assert c.decide(s,r,100) is None  # visibility alone is not aggression
    targeting(c,11)
    assert c.decide(s,r,100)['target_id']==11
    targeting(c,10,target=2)
    assert c.decide(s,r,100)['target_id']==11
    targeting(c,10,kind='skill_cast')
    assert c.decide(s,r,100)['target_id']==10
    s['recent_entities'][0]['position']=[29,20]
    assert c.decide(s,r,100)['target_id']==10  # ranged attacker is approached instead of ignored at 9 cells
    assert c.decide(s,r,111) is None
    # A self buff cast does not falsely say the monster stopped targeting the player.
    targeting(c,11,now=112)
    targeting(c,11,now=112.1,target=11,kind='skill_cast')
    assert c.decide(s,r,112.2)['target_id']==11
    targeting(c,11,now=113,target=2)
    assert c.decide(s,r,113) is None

def test_salamandra_no_basic_and_no_selection_outside_skill_range(config):
    c,r,s=setup(config,[entity(10,1831,28)])
    targeting(c,10)
    assert c.no_chase(1831) and not c.basic_allowed(10,s)
    # Sogu has a reported range of 9, so the stationary self cast may be used here.
    a=c.plan(s,r,100)
    assert a['skill_id']==775 and a['role']=='buff' and a['target_id']==s['player_id']
    assert a['effect_id']==0 and a['effect_duration']==15 and 'combat_target_id' not in a
    s['learned_skills']=[v for v in s['learned_skills'] if v['skill_id']!=775]
    # The map profile explicitly permits a limited approach to nearby Salamandras.
    decision=c.decide(s,r,100)
    assert decision and decision['target_id']==10
    s['recent_entities'][0]['position']=[30,20]
    assert c.decide(s,r,100) is None  # beyond the configured 9-cell approach radius


def test_idle_namekuji_empty_area_sp_cooldown_and_unselected_monsters(config):
    c,r,s=setup(config,[])
    a=c.plan(s,r,100)
    assert a['skill_id']==729 and a['idle_summon'] and a['cast_mode']=='ground'
    assert a['combat_target_id'] is None
    r.sent(a,100)
    after_summon=r.plan(c.idle_state(s),101)
    assert after_summon is None or after_summon['skill_id']!=729
    assert r.ready[729]==130
    c2,r2,s2=setup(config,[])
    # Isolate the summon cooldown from independently maintained map buffs.
    r2.profiles=[p for p in r2.profiles if p['role']!='buff']
    s2['visible_monsters']=[entity(40,1037,24)]  # not one of the four targets
    assert not c2.idle_clear(s2)
    action=c2.plan(s2,r2,100)
    assert action is None or action['skill_id']!=729
    s2['visible_monsters'][0]['position']=[29,20]
    assert c2.idle_clear(s2)
    s2['player_sp']=0
    assert c2.plan(s2,r2,100) is None
    s2['player_sp']=1000;s2['skill_cooldowns']={729:150}
    assert c2.plan(s2,r2,100) is None

def test_idle_summon_never_holds_offensives_for_nearby_monster(config):
    c,r,s=setup(config,[entity(10,1315)])
    targeting(c,10)
    s=c.idle_state(s)
    assert not r.summon_maintenance_required(s,100,10)
    a=c.plan(s,r,100)
    assert a and a['role']=='offensive' and a['skill_id']!=729

def test_dai_senkou_renews_on_missing_effect_and_sogu_is_self_buff(config):
    c,r,s=setup(config,[])
    s['visible_monsters']=[entity(99,1037)]  # blocks idle summon, not buffs
    s['own_effects'][105]=False
    a=c.plan(s,r,100)
    assert a['skill_id']==357 and a['role']=='buff' and a['effect_id']==105 and a['level']==3
    s['own_effects'][105]=True
    a=c.plan(s,r,100)
    assert a['skill_id']==775 and a['role']=='buff' and a['target_id']==s['player_id']
    c,r,s=setup(config,[entity(10,1831,28)])
    targeting(c,10)
    a=c.plan(s,r,100)
    assert a['skill_id']==775 and a['role']=='buff' and a['target_id']==s['player_id']
    assert a['effect_id']==0 and a['effect_duration']==15 and 'combat_target_id' not in a
    s['skill_cooldowns']={775:200}
    assert c.plan(s,r,100) is None

def relay_for(tmp_path,config):
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_hunt import PacketHunt
    from nrobot.map_navigation import CollisionMap
    c,r,s=setup(config,[])
    relay=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    relay.hunt=PacketHunt()
    relay.apply_settings(settings_for(config,DEFAULTS,s['learned_skills']))
    relay.map_combat=c;relay.map_combat_map='ra_fild03'
    o=relay.tracker.observer;now=time.monotonic()
    o.player_id=1;o.player=[20,20];o.player_at=now;o.map_name='ra_fild03.gat';o.sp=1000
    o.hp=500;o.max_hp=1000
    o.skills={v['skill_id']:v for v in s['learned_skills']};o.effects={12:True,207:True,105:True}
    collision=CollisionMap(60,60,bytes([1])*3600)
    relay.collision_map=lambda:collision
    relay.hunt.start()
    class Writer:
        def __init__(self):self.packets=[]
        def write(self,p):self.packets.append(p)
        async def drain(self):pass
    relay.upstream=Writer()
    return relay,now

def add_monster(relay,identity,species,point,now):
    from nrobot.network_targets import Entity
    relay.inventory.observe([dict(kind='appearance',entity_id=identity,species_id=species,object_type=5,position=point)],now)
    if species in relay.tracker.observer.species:
        relay.tracker.observer.registry.update(Entity(identity,species,*point,now,'monster'))

def test_relay_does_not_chase_or_attack_salamandra(tmp_path,config):
    from nrobot.session_relay import HuntTargetChanged
    relay,now=relay_for(tmp_path,config)
    add_monster(relay,110000001,1831,[25,20],now)
    targeting(relay.map_combat,110000001,now=now)
    s=relay.status()
    assert relay.plan_group_or_hunt(s,now,150,relay.collision_map()) is None
    assert relay.hunt.auto_movement  # only the current target is stationary
    assert not relay.map_damage_allowed(110000001,s,now,basic=True)
    with pytest.raises(HuntTargetChanged,match='controle de status'):
        asyncio.run(relay.send_hunt_action(dict(kind='attack',target_id=110000001),game_gate=lambda:True))
    assert not relay.upstream.packets

def test_unengaged_monsters_dont_become_chase_target(tmp_path,config):
    relay,now=relay_for(tmp_path,config)
    add_monster(relay,110000001,1315,[25,20],now)
    action=relay.plan_group_or_hunt(relay.status(),now,150,relay.collision_map())
    assert action is None or action.get('purpose')=='patrol'
    assert relay.hunt.target is None

def test_idle_summon_send_rechecks_all_monsters_under_lock(tmp_path,config):
    relay,now=relay_for(tmp_path,config)
    a=relay.plan_map_rotation(relay.status(),now,None)
    assert a['skill_id']==729
    # An unselected monster appears after planning, before sending.
    add_monster(relay,110000005,1037,[24,20],now)
    s=relay.status()
    assert s['recent_entities']==[] and not s['idle_summon_clear']
    assert not asyncio.run(relay.send_rotation_action(a,game_gate=lambda:True))
    assert not relay.upstream.packets
    relay.inventory.observe([dict(kind='remove',entity_id=110000005,reason=0)],now+.1)
    a=relay.plan_map_rotation(relay.status(),now+.1,None)
    assert a and a['idle_summon']
    assert asyncio.run(relay.send_rotation_action(a,game_gate=lambda:True))
    assert len(relay.upstream.packets)==1 and relay.rotation.summons.waiting['skill_id']==729

def test_rasengan_restricted_to_ninkame_and_salamandra(config):
    for species,expected in [(1315,370),(1831,370),(1634,None),(1177,None)]:
        c,r,s=setup(config,[entity(10,species,21,health=4)])
        targeting(c,10)
        for p in r.profiles:
            if p['skill_id']!=370:r.ready[p['skill_id']]=200
        a=c.plan(s,r,100)
        assert (a['skill_id'] if a else None)==expected
    c,r,s=setup(config,[entity(10,1831,23)])
    targeting(c,10)
    for p in r.profiles:
        if p['skill_id']!=370:r.ready[p['skill_id']]=200
    assert c.plan(s,r,100) is None  # range 2; do not pursue to use Rasengan

def test_burst_profile_fast_offensives_but_cooldowns_and_controls_are_guarded(config):
    c,r,s=setup(config,[entity(10,1315,21)])
    targeting(c,10)
    assert r.burst and r.burst_interval==.05
    for p in r.profiles:
        if p['skill_id']!=370:r.ready[p['skill_id']]=200
    a=c.plan(s,r,100)
    assert a['skill_id']==370
    r.sent(a,100)
    assert r.pending[370]['burst_sent']
    assert c.plan(s,r,100.04) is None
    assert c.plan(s,r,100.06)['skill_id']==370
    s['skill_cooldowns']={370:150}
    assert c.plan(s,r,100.06) is None
    # Negative status attempts remain non-burst and await their own confirmation.
    c,r,s=setup(config,[entity(11,1634,21)])
    targeting(c,11)
    a=c.plan(s,r,100)
    assert a['control_status']=='stun'
    r.sent(a,100);c.sent(a,100)
    assert not r.pending[179]['burst_sent']
    assert c.plan(s,r,100.06) is None
