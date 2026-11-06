import copy
import json
from pathlib import Path
import pytest
from nrobot.map_combat import MapCombat,settings_for
from nrobot.map_emergency import Emergency
from nrobot.combat_rotation import CombatRotation
from nrobot.packet_settings import DEFAULTS
from test_map_combat import state,entity,rotation

@pytest.fixture
def config():
    result=json.loads(Path('exemplos/comportamentos/ra_fild03.json').read_text(encoding='utf-8'))['combat']
    result.pop('engagement',None);result.pop('idle_summon',None);result.pop('burst',None)
    result['emergency'].update(minimum_count=3,radius=5)
    return result

def emergency_state():
    s=state([entity(10,1634),entity(11,1634,22),entity(12,1634,25)])
    s['learned_skills'] += [dict(skill_id=500,level=1,sp_cost=1,range=0,target_flags=4),dict(skill_id=668,level=0,sp_cost=0,range=0,target_flags=4)]
    return s

def test_profile_uses_max_learned_even_if_panel_level_was_lower(config):
    base=copy.deepcopy(DEFAULTS)
    base['skill_profiles']=[dict(skill_id=179,level=1),dict(skill_id=182,level=2),dict(skill_id=76,level=1),dict(skill_id=532,level=3)]
    learned=state([])['learned_skills']+[dict(skill_id=532,level=5)]
    profiles=settings_for(config,base,learned)['skill_profiles']
    assert {p['skill_id']:p['level'] for p in profiles}=={s['skill_id']:s['level'] for s in learned}

def test_imagem_falsa_twenty_seconds_survives_effect_loss_failure_and_map():
    p=dict(skill_id=532,enabled=True,role='buff',level=5,interval=.5,effect_id=207)
    r=CombatRotation([p])
    s=state([])
    s['learned_skills']=[dict(skill_id=532,level=5,sp_cost=38,range=0,target_flags=4)]
    s['own_effects']={207:False}
    a=r.plan(s,100);r.sent(a,100)
    r.observe([dict(kind='skill_no_damage',skill_id=532,source_id=1,target_id=1,success=True)],1,100.1)
    r.observe([dict(kind='status_effect',effect_id=207,entity_id=1,active=True)],1,100.2)
    r.observe([dict(kind='status_effect',effect_id=207,entity_id=1,active=False)],1,101)
    assert r.plan(s,119.9) is None
    # Mapping transitions clear ordinary readiness, but never this real cooldown.
    r.reset_session()
    assert r.plan(s,119.9) is None
    assert r.plan(s,120.3)['skill_id']==532
    # A refused attempt does not restart another 20 seconds.
    a=r.plan(s,120.3);r.sent(a,120.3)
    r.observe([dict(kind='skill_failed',skill_id=532)],1,120.4)
    assert r.plan(s,122)['skill_id']==532

def test_manual_success_also_starts_imagem_falsa_cooldown():
    r=CombatRotation([])
    r.observe([dict(kind='skill_no_damage',skill_id=532,source_id=1,target_id=1,success=True)],1,100)
    assert r.cooldown_floor[532]==120

def test_control_can_preempt_unconfirmed_damage_after_global_delay(config):
    c=MapCombat(config);r=rotation(config)
    s=state([entity(10,1315),entity(11,1634)])
    a=dict(kind='skill',skill_id=524,role='offensive',level=5,interval=.5,effect_id=0,target_id=10,sp_cost=1)
    r.sent(a,100)
    assert c.plan(s,r,100.2) is None
    assert c.plan(s,r,100.5)['skill_id']==179
    # Immunity/missing status must not teach a fictitious slower global delay.
    a=c.plan(s,r,100.5);r.sent(a,100.5)
    r.last_confirmed_at=100.4
    before=r.after_skill_delay
    r._fail(179,102,'sem confirma\u00e7\u00e3o')
    assert r.after_skill_delay==before

def test_emergency_threshold_three_confirmations_then_unlock_and_escape(config):
    c=MapCombat(config);r=rotation(config);s=emergency_state()
    assert c.decide(s,r,100)['mode']=='emergency'
    for number in range(3):
        now=100+number
        a=c.plan(s,r,now)
        assert a['skill_id']==500 and a['target_id']==1
        r.sent(a,now);c.sent(a,now)
        assert c.emergency.confirmed==number
        assert c.plan(s,r,now+.1) is None
        ack=dict(kind='skill_no_damage',skill_id=500,source_id=1,target_id=1,success=True)
        c.observe([ack],1,now+.2);r.observe([ack],1,now+.2)
        c.observe([ack],1,now+.21)  # duplicated acknowledgement never adds a fourth seal
        assert c.emergency.confirmed==number+1
    assert c.emergency.phase=='area'
    assert c.plan(s,r,103) is None  # still level 0: never invent availability
    s['learned_skills'][-1]['level']=4
    a=c.plan(s,r,103)
    assert a['skill_id']==668 and a['level']==4
    r.sent(a,103);c.sent(a,103)
    ack=dict(kind='skill_no_damage',skill_id=668,source_id=1,target_id=1,success=True)
    c.observe([ack],1,103.1);r.observe([ack],1,103.1)
    assert c.emergency.phase=='retreat'
    assert not kill_intent(c,10,s,r,104)
    # Distance alone does not mean off-screen; wait for disappearance from received visibility.
    for e in s['recent_entities']:e['position']=[40,40]
    assert c.decide(s,r,104)['phase']=='retreat'
    s['recent_entities']=[]
    assert c.decide(s,r,105) is None and c.emergency.phase is None

def test_two_jounin_or_third_beyond_five_does_not_trigger(config):
    for rows in ([entity(10,1634),entity(11,1634,22)], [entity(10,1634),entity(11,1634,22),entity(12,1634,26)]):
        c=MapCombat(config);r=rotation(config)
        assert c.decide(state(rows),r,100)['mode']=='control'

def test_unconfirmed_seals_drop_the_sequence_and_the_fight_goes_on(config):
    c=MapCombat(config);r=rotation(config);s=emergency_state()
    a=c.plan(s,r,100);c.sent(a,100);r.sent(a,100)
    c.observe([dict(kind='skill_no_damage',skill_id=500,source_id=1,target_id=1,success=False)],1,100.1)
    assert c.emergency.confirmed==0
    intent=c.decide(s,r,113)  # 12 s without the seals: no escape, normal combat
    assert c.emergency.phase is None and (intent is None or intent['mode']!='emergency')
    later=c.decide(s,r,120)  # and no new emergency for a while
    assert later is None or later['mode']!='emergency'


def test_two_seals_without_answer_drop_the_sequence_early(config):
    c=MapCombat(config);r=rotation(config);s=emergency_state()
    assert c.decide(s,r,100)['mode']=='emergency'
    c.emergency.waiting=dict(skill_id=500,stage='prepare',deadline=101)
    c.decide(s,r,101.5)
    c.emergency.waiting=dict(skill_id=500,stage='prepare',deadline=103)
    intent=c.decide(s,r,103.5)
    assert c.emergency.phase is None and (intent is None or intent['mode']!='emergency')

def test_retreat_walks_valid_route_away_and_does_not_touch_patrol(config):
    from nrobot.map_navigation import CollisionMap
    from nrobot.packet_hunt import PacketHunt
    collision=CollisionMap(60,60,bytes([1])*3600)
    c=MapCombat(config);r=rotation(config);s=emergency_state()
    c.decide(s,r,100);c.emergency.phase='retreat'
    hunt=PacketHunt(patrol=True);hunt.start()
    patrol=hunt.patrol
    a=c.emergency.retreat(s,hunt,collision,101,150)
    assert a['purpose']=='map_retreat' and a['target_id'] is None
    assert collision.segment(a['origin'],a['destination'],max_steps=4)
    assert a['destination'][0]<20
    assert hunt.patrol is patrol
    hunt.pending={'kind':'move'}
    assert c.emergency.retreat(s,hunt,collision,101,150) is None

def test_emergency_retreat_can_be_sent_without_patrol_interrupt(tmp_path,config):
    import asyncio
    import time
    from nrobot.map_navigation import CollisionMap
    from nrobot.network_targets import Entity
    from nrobot.packet_hunt import PacketHunt
    from nrobot.session_relay import SessionRelay
    relay=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    relay.hunt=PacketHunt()
    relay.apply_settings(settings_for(config,DEFAULTS,emergency_state()['learned_skills']))
    relay.map_combat=MapCombat(config);relay.map_combat_map='ra_fild03'
    o=relay.tracker.observer;now=time.monotonic()
    o.map_name='ra_fild03.gat';o.player_id=1;o.player=[20,20];o.player_at=now;o.sp=1000
    o.skills={s['skill_id']:s for s in emergency_state()['learned_skills']}
    for number,x in enumerate((21,22,25)):
        identity=110000000+number
        relay.inventory.observe([dict(kind='appearance',entity_id=identity,species_id=1634,position=[x,20],object_type=5)],now)
        o.registry.update(Entity(identity,1634,x,20,now,'monster'))
    collision=CollisionMap(60,60,bytes([1])*3600)
    relay.collision_map=lambda:collision
    relay.hunt.start()
    s=relay.status()
    assert relay.map_combat.decide(s,relay.rotation,now)['mode']=='emergency'
    relay.map_combat.emergency.phase='retreat'
    action=relay.plan_group_or_hunt(s,now,150,collision)
    assert action['purpose']=='map_retreat'
    class Writer:
        packets=[]
        def write(self,p):self.packets.append(p)
        async def drain(self):pass
    relay.upstream=Writer()
    asyncio.run(relay.send_hunt_action(action,game_gate=lambda:True))
    assert len(relay.upstream.packets)==1


def kill_intent(combat, identity, state, rotation, now):
    """The map behavior plans a kill on this monster (what the relay's map_damage_allowed asks)."""
    intent = combat.decide(state, rotation, now, current=identity)
    return bool(intent and intent['mode'] == 'kill' and intent['target_id'] == identity)


def test_jounin_put_to_sleep_and_silenced_is_attacked_normally(config):
    c=MapCombat(config);r=rotation(config)
    jounin=entity(10,1634);jounin['body_state']=4  # asleep
    s=state([jounin])
    c.history[10]={'sleep':50,'silence':51}  # controlled by us long ago: no longer targeting the player
    c.statuses=lambda e:dict(stun=False,sleep=True,silence=True)
    intent=c.decide(s,r,100)
    assert intent and intent['mode']=='kill' and intent['target_id']==10
