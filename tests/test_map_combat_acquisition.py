import asyncio
import copy
import json
from pathlib import Path
import pytest
from nrobot.map_combat import MapCombat
from test_map_combat import state,entity,rotation
from test_map_combat_focus import setup,targeting,relay_for,add_monster

@pytest.fixture
def config():return json.loads(Path('exemplos/comportamentos/ra_fild03.json').read_text(encoding='utf-8'))['combat']

def test_acquire_distant_target_and_keep_it_as_it_crosses_eight(config):
    c,r,s=setup(config,[entity(10,1315,33)])
    assert c.decide(s,r,100)['target_id']==10
    assert c.pull_id==10
    s['recent_entities'][0]['position']=[27,20]
    assert c.decide(s,r,101)['target_id']==10  # still no incoming attack yet
    s['recent_entities'][0]['position']=[25,20]
    assert c.plan(s,r,101)['role']=='offensive'

def test_doki_passive_selected_without_targeting_but_silenced_before_damage(config):
    c,r,s=setup(config,[entity(10,1177,24)])
    intent=c.decide(s,r,100)
    assert intent['target_id']==10 and intent['skill_id']==76
    assert not kill_intent(c,10,s,r,100)
    s['recent_entities'][0]['health_state']=4
    assert c.decide(s,r,101)['mode']=='kill'
    assert kill_intent(c,10,s,r,101)

def test_nearby_threat_preempts_distant_acquisition(config):
    c,r,s=setup(config,[entity(10,1315,33),entity(11,1634,24)])
    targeting(c,11)
    assert c.decide(s,r,100)['target_id']==11
    assert c.decide(s,r,100)['mode']=='control'

@pytest.mark.parametrize('body_state',[3,4])
def test_controlled_jounin_is_approached_to_silence_range_even_during_cooldown(tmp_path,config,body_state):
    relay,now=relay_for(tmp_path,config)
    identity=110000001
    add_monster(relay,identity,1634,[26,20],now)  # visible, but no longer targeting us
    relay.inventory.entities[identity]['body_state']=body_state
    relay.tracker.observer.skill_cooldowns[76]=now+8

    state=relay.status()
    intent=relay.map_combat_intent(relay.active_map_combat(),state,now)
    assert intent and intent['mode']=='control' and intent['skill_id']==76
    action=relay.plan_group_or_hunt(state,now,150,relay.collision_map())
    assert action and action['kind']=='move' and action['target_id']==identity
    assert action['destination']==[23,20]  # approach to 3 cells before silence


def test_silence_approach_preempts_pending_attack_on_another_target(tmp_path,config):
    relay,now=relay_for(tmp_path,config)
    identity=110000001
    add_monster(relay,identity,1634,[26,20],now)
    relay.inventory.entities[identity]['body_state']=3
    relay.hunt.target=110000002
    relay.hunt.pending=dict(kind='attack',target_id=110000002,deadline=now+1)
    action=relay.plan_group_or_hunt(relay.status(),now,150,relay.collision_map())
    assert action and action['kind']=='move' and action['target_id']==identity
    assert action['control_skill_id']==76 and action['destination']==[23,20]


def test_imported_buff_rules_survive_into_live_rotation(tmp_path,config):
    relay,now=relay_for(tmp_path,config)
    profiles={p['skill_id']:p for p in relay.rotation.profiles}
    assert profiles[532]['only_when_clear_radius']==9
    assert profiles[775]['effect_duration']==15
    add_monster(relay,110000001,1634,[22,20],now)
    relay.tracker.observer.effects[207]=False
    action=relay.plan_map_rotation(relay.status(),now)
    assert action is None or action['skill_id']!=532

def test_no_pursuit_salamandra_and_no_stealing_from_known_other_target(config):
    c,r,s=setup(config,[entity(10,1831,33)])
    assert c.decide(s,r,100) is None
    s['recent_entities']=[entity(11,1315,33)]
    targeting(c,11,target=2)
    assert c.decide(s,r,100) is None

def test_ranged_attacker_is_not_forgotten_outside_eight(config):
    c,r,s=setup(config,[entity(10,1315,30)])
    s['visible_monsters']=[*s['recent_entities'],entity(12,1037,22)]
    targeting(c,10)
    assert c.decide(s,r,100)['target_id']==10

def test_first_offensive_does_not_wait_for_buff_renewal(config):
    c,r,s=setup(config,[entity(10,1315,21)])
    targeting(c,10)
    s['own_effects'][105]=False
    a=c.plan(s,r,100)
    assert a['role']=='offensive'
    c.sent(a,100)
    # After starting damage, ordinary buff maintenance takes its turn again.
    assert c.plan(s,r,100.1)['skill_id']==357

def test_ignored_visible_monster_no_longer_cancels_patrol_send(tmp_path,config):
    config['engagement']['proactive_species']=[1177]  # explicitly configure aggression-only Ninkames
    relay,now=relay_for(tmp_path,config)
    add_monster(relay,110000001,1315,[25,20],now)  # not targeting us, not passive exception
    action=relay.plan_group_or_hunt(relay.status(),now,150,relay.collision_map())
    assert action and action['purpose']=='patrol'
    asyncio.run(relay.send_hunt_action(action,game_gate=lambda:True))
    assert len(relay.upstream.packets)==1

def test_log_ninkame_coordinates_now_produce_approach(tmp_path,config):
    relay,now=relay_for(tmp_path,config)
    from nrobot.map_navigation import CollisionMap
    relay.collision_map=lambda:CollisionMap(400,400,bytes([1])*160000)
    observer=relay.tracker.observer
    observer.player=[121,252]
    observer.player_at=now
    add_monster(relay,111902894,1315,[113,257],now)
    action=relay.plan_group_or_hunt(relay.status(),now,150,relay.collision_map())
    assert action and action['kind']=='move' and action['target_id']==111902894
    assert action.get('purpose')!='patrol'
    asyncio.run(relay.send_hunt_action(action,game_gate=lambda:True))
    assert len(relay.upstream.packets)==1


def kill_intent(combat, identity, state, rotation, now):
    """The map behavior plans a kill on this monster (what the relay's map_damage_allowed asks)."""
    intent = combat.decide(state, rotation, now, current=identity)
    return bool(intent and intent['mode'] == 'kill' and intent['target_id'] == identity)


def test_doki_is_attacked_anyway_when_the_silence_does_not_come(config):
    c=MapCombat(config);r=rotation(config)
    s=state([entity(10,1177,22)])
    first=c.decide(s,r,100)
    assert first['mode']=='control'  # silence first
    later=c.decide(s,r,102.5)  # 2.5 s without the silence: attacked normally
    assert later['mode']=='kill' and later['target_id']==10
