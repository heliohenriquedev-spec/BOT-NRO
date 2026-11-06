import copy
import json
from pathlib import Path
import pytest
from nrobot.map_behavior import validate, effective
from nrobot.map_combat import MapCombat, settings_for
from nrobot.combat_rotation import CombatRotation
from nrobot.entity_inventory import EntityInventory

@pytest.fixture
def config():
    result=json.loads(Path('exemplos/comportamentos/ra_fild03.json').read_text(encoding='utf-8'))['combat']
    result.pop('engagement',None);result.pop('idle_summon',None);result.pop('burst',None)
    result['emergency'].update(minimum_count=3,radius=5)
    result['control_radius']=8
    return result

def state(entities):
    return dict(state='tracking',player_id=1,player_position=[20,20],player_position_recent=True,player_sp=1000,
      learned_skills=[dict(skill_id=i,level=5,sp_cost=1,range=r,target_flags=1) for i,r in [(179,9),(182,9),(76,5),(524,6),(523,6),(62,3)]],
      recent_entities=entities,own_effects={12:True,207:True})

def entity(identity,species,x=21,y=20,body=0,health=0):
    return dict(entity_id=identity,species_id=species,kind='monster',position=[x,y],body_state=body,health_state=health,position_usable=True)

def rotation(config):
    from nrobot.packet_settings import DEFAULTS
    s=settings_for(config,DEFAULTS,state([])['learned_skills'])
    return CombatRotation(s['skill_profiles'],fast=True,priority=s['skill_priority'])

def test_jounin_sequence_requires_real_status(config):
    c=MapCombat(config);r=rotation(config)
    s=state([entity(10,1315),entity(11,1634)])
    intent=c.decide(s,r,100)
    assert intent['target_id']==11 and intent['skill_id']==179
    action=c.plan(s,r,100)
    assert action['control_status']=='stun'
    r.sent(action,100);c.sent(action,100)
    assert c.decide(s,r,100.1)['skill_id'] is None
    # An executed stun without a body-state change is not a successful stun.
    r.observe([dict(kind='skill_no_damage',skill_id=179,source_id=1,target_id=11,success=True)],1,100.1)
    assert c.decide(s,r,100.6)['skill_id']==182
    s['recent_entities'][1]['body_state']=4
    assert c.decide(s,r,100.6)['skill_id']==76
    s['recent_entities'][1]['health_state']=4
    assert c.decide(s,r,101)['target_id']==10
    assert c.decide(s,r,101)['mode']=='kill'

def test_fallback_silences_all_near_jounin_when_control_cooldowns(config):
    c=MapCombat(config);r=rotation(config)
    r.ready.update({179:200,182:200})
    s=state([entity(10,1315),entity(11,1634),entity(12,1634,22)])
    assert c.decide(s,r,100)['skill_id']==76
    s['recent_entities'][1]['health_state']=4
    assert c.decide(s,r,100)['target_id']==12
    s['recent_entities'][2]['health_state']=4
    assert c.decide(s,r,100)['target_id']==10

def test_radius_boundary(config):
    c=MapCombat(config);r=rotation(config)
    s=state([entity(10,1315),entity(11,1634,28)])
    assert c.decide(s,r,100)['target_id']==11
    s['recent_entities'][1]['position']=[29,20]
    assert c.decide(s,r,100)['target_id']==10

def test_doki_passive_and_resilence(config):
    c=MapCombat(config);r=rotation(config);s=state([entity(10,1177)])
    assert c.decide(s,r,100)['skill_id']==76
    assert not c.damage_allowed(10,s,r,100)
    s['recent_entities'][0]['health_state']=4
    assert c.damage_allowed(10,s,r,100)
    c.observe([dict(kind='normal_attack',source_id=1,target_id=10)],1,101)
    s['recent_entities'][0]['health_state']=0
    assert c.decide(s,r,102)['skill_id']==179
    s['recent_entities'][0]['body_state']=3
    assert c.decide(s,r,102)['skill_id']==76

def test_doki_is_controlled_before_leaving_then_returned(config):
    c=MapCombat(config);r=rotation(config)
    c.attacked.add(10)
    s=state([entity(10,1177),entity(11,1315)])
    assert c.decide(s,r,100,current=10)['target_id']==10
    s['recent_entities'][0]['body_state']=3
    assert c.decide(s,r,101,current=10)['target_id']==11
    s['recent_entities'].pop()
    assert c.decide(s,r,102)['skill_id']==76
    s['recent_entities'][0]['health_state']=4
    assert c.decide(s,r,103)['mode']=='kill'

def test_priority_reachability_and_no_mutation(config):
    c=MapCombat(config);r=rotation(config)
    s=state([entity(13,1177,health=4),entity(12,1831),entity(11,1634,30),entity(10,1315)])
    assert c.decide(s,r,100)['target_id']==10
    assert c.decide(s,r,100,reachable=lambda rows:[e for e in rows if e['species_id']!=1315])['target_id']==11
    original=copy.deepcopy(r.profiles)
    c.plan(s,r,100)
    assert r.profiles==original

def test_profiles_learned_only_and_patrol_unchanged(config):
    from nrobot.packet_settings import DEFAULTS
    base=copy.deepcopy(DEFAULTS)
    learned=state([])['learned_skills']+[dict(skill_id=29,level=5),dict(skill_id=532,level=3)]
    result=settings_for(config,base,learned)
    assert result['patrol']==base['patrol'] and result['patrol_spacing']==base['patrol_spacing']
    assert result['auto_attacks'] and result['fast_offensives'] and not result['skill_burst']
    assert {p['skill_id']:p['effect_id'] for p in result['skill_profiles'] if p['role']=='buff'}=={29:12,532:207}
    assert all(p['level']<=next(s['level'] for s in learned if s['skill_id']==p['skill_id']) for p in result['skill_profiles'])
    assert DEFAULTS==base
    result=settings_for(config,base,[])
    assert result['skill_profiles']==[]

def test_inventory_retains_health_state_and_clear_on_map():
    inv=EntityInventory()
    inv.observe([dict(kind='appearance',entity_id=10,species_id=1177,position=[1,1],health_state=4)],100)
    assert inv.entities[10]['health_state']==4
    inv.observe([dict(kind='option_change',entity_id=10,body_state=3,health_state=0)],101)
    assert inv.entities[10]['body_state']==3 and inv.entities[10]['health_state']==0
    inv.observe([dict(kind='map_change',map='other')],102)
    assert not inv.entities

def test_confirmed_status_clears_control_pending(config):
    c=MapCombat(config);r=rotation(config);s=state([entity(10,1634)])
    action=c.plan(s,r,100);r.sent(action,100)
    r.observe([dict(kind='option_change',entity_id=10,body_state=3,health_state=0)],1,100.1)
    assert 179 not in r.pending
    assert r.log[-1]['kind']=='rotation_control_confirmed'

def test_schema2_file_and_unknown_logic_rejected():
    data=json.loads(Path('exemplos/comportamentos/ra_fild03.json').read_text(encoding='utf-8'))
    assert validate(data)==data
    data['combat']['arbitrary_code']='run'
    with pytest.raises(ValueError):validate(data)

def test_health_state_decoding_from_real_packet_layouts():
    import struct
    from nrobot.packet_reader import decode
    for opcode,body_offset,health_offset,size in [(0x229,6,8,15),(0x119,6,8,13),(0x22a,8,10,58),(0x22c,9,11,65)]:
        raw=bytearray(size)
        struct.pack_into('<H',raw,0,opcode)
        struct.pack_into('<H',raw,body_offset,3)
        struct.pack_into('<H',raw,health_offset,4)
        event=decode(bytes(raw))
        assert event['body_state']==3 and event['health_state']==4

def test_control_uses_real_skill_range_and_global_delay(config):
    c=MapCombat(config);r=rotation(config)
    # Jounin triggers control at 8, but silence has only 5 cells of range.
    s=state([entity(10,1634,28,body=3)])
    assert c.decide(s,r,100)['skill_id']==76
    assert c.plan(s,r,100) is None
    s['recent_entities'][0]['position']=[25,20]
    assert c.plan(s,r,100)['skill_id']==76
    r.next_send=101
    assert c.plan(s,r,100) is None
    r.next_send=0
    s['skill_cooldowns']={76:101}
    assert c.plan(s,r,100) is None

def test_sleeping_target_kept_for_silence_and_doki_damage_gated(tmp_path,config):
    import asyncio
    import time
    from nrobot.network_targets import Entity
    from nrobot.packet_hunt import PacketHunt
    from nrobot.packet_settings import DEFAULTS
    from nrobot.session_relay import SessionRelay,HuntTargetChanged
    relay=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    relay.hunt=PacketHunt()
    relay.apply_settings(settings_for(config,DEFAULTS,state([])['learned_skills']))
    relay.map_combat=MapCombat(config)
    relay.map_combat_map='ra_fild03'
    observer=relay.tracker.observer
    now=time.monotonic()
    observer.player_id,observer.player,observer.player_at=1,[20,20],now
    observer.map_name='ra_fild03.gat'
    observer.skills={s['skill_id']:s for s in state([])['learned_skills']}
    observer.sp=1000
    identity=110000001
    relay.inventory.observe([dict(kind='appearance',entity_id=identity,species_id=1177,position=[21,20],body_state=4,health_state=0,object_type=5)],now)
    observer.registry.update(Entity(identity,1177,21,20,now,'monster'))
    relay.collision_map=lambda:None
    assert not relay.asleep(identity)
    snapshot=relay.status()
    assert snapshot['recent_entities'][0]['body_state']==4
    assert not relay.map_damage_allowed(identity,snapshot,now)
    relay.hunt.start()
    class Writer:
        packets=[]
        def write(self,p):self.packets.append(p)
        async def drain(self):pass
    relay.upstream=Writer()
    with pytest.raises(HuntTargetChanged,match='controle de status'):
        asyncio.run(relay.send_hunt_action(dict(kind='attack',target_id=identity),game_gate=lambda:True))
    assert not relay.upstream.packets
    # A sleeping monster may receive silence, even though normal hunts skip sleeping targets.
    action=relay.plan_map_rotation(snapshot,now,identity)
    assert action['skill_id']==76 and action['control_status']=='silence'
    relay.settings['require_collision']=False  # fake session has no map file; no real socket is used
    assert asyncio.run(relay.send_rotation_action(action,game_gate=lambda:True))
    assert len(relay.upstream.packets)==1 and relay.map_combat.history[identity]['silence']>0
    relay.inventory.observe([dict(kind='option_change',entity_id=identity,body_state=4,health_state=4)],now+.1)
    assert relay.map_damage_allowed(identity,relay.status(),now+.1)
