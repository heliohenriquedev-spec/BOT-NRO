import copy
import json
from pathlib import Path
import pytest
from nrobot.map_combat import MapCombat,settings_for
from nrobot.combat_rotation import CombatRotation
from nrobot.packet_settings import DEFAULTS
from test_map_combat import state,entity,rotation

@pytest.fixture
def config():
    result=json.loads(Path('exemplos/comportamentos/ra_fild03.json').read_text(encoding='utf-8'))['combat']
    result.pop('engagement',None);result.pop('idle_summon',None);result.pop('burst',None)
    return result

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


@pytest.mark.parametrize('confirmation',['skill_damage','option_change'])
def test_burst_does_not_send_silence_during_confirmed_stun_delay(config,confirmation):
    c=MapCombat(config);r=rotation(config);r.burst=True
    s=state([entity(10,1634)])
    action=c.plan(s,r,100)
    assert action['control_status']=='stun'
    r.sent(action,100);c.sent(action,100)
    if confirmation=='skill_damage':
        event=dict(kind='skill_damage',skill_id=179,source_id=1,target_id=10,level=5,damage_raw=1)
    else:
        event=dict(kind='option_change',entity_id=10,body_state=3,health_state=0)
    r.observe([event],1,100.05)
    s['recent_entities'][0]['body_state']=3
    assert c.plan(s,r,100.25) is None
    assert c.plan(s,r,100.51)['control_status']=='silence'


def test_silence_requires_interior_range_before_cast(config):
    c=MapCombat(config);r=rotation(config)
    s=state([entity(10,1634,25,20,body=3)])
    assert c.plan(s,r,100) is None  # exactly 5 cells: first approach inside the range
    s['player_position']=[21,20]
    assert c.plan(s,r,100.05) is None  # 4 cells is still outside the approach threshold
    s['player_position']=[22,20]
    assert c.plan(s,r,100.1)['skill_id']==76
    assert r.range_margin==0  # the margin belongs to this control action only


def test_silence_three_cell_limit_also_bounds_overridden_range_and_movement(config):
    c=MapCombat(config);r=rotation(config)
    for profile in r.profiles:
        if profile['skill_id']==76:profile['range_override']=10
    s=state([entity(10,1634,24,20,body=3)])
    assert c.plan(s,r,100) is None  # override does not allow silence from 4 cells away
    s['recent_entities'][0]['position']=[23,20]
    s['combat_player_positions']=[[20,20],[19,20]]
    assert c.plan(s,r,100) is None  # movement uncertainty still puts us outside 3
    s['combat_player_positions']=[[20,20]]
    assert c.plan(s,r,100)['control_status']=='silence'
    for profile in r.profiles:
        if profile['skill_id']==76:profile['range_override']=2
    assert c.plan(s,r,100) is None  # shorter configured range is still respected


def test_unconfirmed_silence_does_not_inherit_long_damage_deferral(config):
    c=MapCombat(config);r=rotation(config)
    s=state([entity(10,1634,21,20,body=3)])
    for now in (100,102,104):
        action=c.plan(s,r,now)
        assert action['control_status']=='silence'
        r.sent(action,now)
        r._fail(76,now+1.5,'sem confirmação')
    assert c.plan(s,r,106)['skill_id']==76  # no 8-second pause after the third missing answer
    r.observe([dict(kind='skill_cooldown',skill_id=76,duration_ms=5000)],1,106)
    assert c.plan(s,r,108) is None  # actual server cooldowns remain authoritative

def test_two_jounin_or_third_beyond_five_does_not_trigger(config):
    for rows in ([entity(10,1634),entity(11,1634,22)], [entity(10,1634),entity(11,1634,22),entity(12,1634,26)]):
        c=MapCombat(config);r=rotation(config)
        assert c.decide(state(rows),r,100)['mode']=='control'

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
