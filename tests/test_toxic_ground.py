import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from nrobot.toxic_ground import ToxicGround
from nrobot.map_navigation import CollisionMap,server_line
from nrobot.map_combat import MapCombat
from test_map_combat import entity
from test_map_combat_focus import setup,targeting,relay_for

@pytest.fixture
def config():return json.loads(Path('exemplos/comportamentos/ra_fild03.json').read_text(encoding='utf-8'))['combat']

def ground(identity=1,position=(20,20),unit=146,visible=True):
    return dict(kind='ground_effect',effect_id=identity,position=list(position),effect_type=unit,source_id=500,visible=visible)

def inventory():return SimpleNamespace(entities={500:dict(species_id=1831)})

def test_received_units_overlap_removal_and_map_reset():
    t=ToxicGround();inv=inventory()
    t.observe([ground(1),ground(2)],inv,100)
    assert t.cells(100)=={(20,20)}
    t.observe([dict(kind='ground_effect_removed',effect_id=1)],inv,101)
    assert (20,20) in t.cells(101)
    t.observe([ground(2,visible=False)],inv,102)
    assert not t.cells(102)
    t.observe([ground(),dict(kind='map_transfer',map='other')],inv,103)
    assert not t.cells(103)

def test_predict_only_explicit_salamandra_cast_and_cancel_without_removing_real_units():
    t=ToxicGround();inv=inventory()
    cast=dict(kind='skill_cast',source_id=500,skill_id=140,position=[20,20],duration_ms=1500)
    t.observe([cast],inv,100)
    cross={(19,20),(20,19),(20,20),(20,21),(21,20)}
    assert t.cells(101)==cross
    t.observe([ground(),dict(kind='skill_cast_cancel',source_id=500)],inv,101)
    assert t.cells(101)==cross  # cancel clears only the forecast, not the observed active field
    t.observe([dict(kind='ground_effect_removed',effect_id=1)],inv,101.5)
    t.observe([{**cast,'source_id':999}],inv,102)
    assert not t.cells(102)  # unrelated source is not attributed to the Salamandra
    t.observe([{**cast,'position':[0,0]}],inv,102)
    assert t.cells(102)=={(0,0),(1,0),(0,1)}  # the cross is clipped at the map edge
    t.observe([cast],inv,110)
    assert t.cells(113)==cross
    assert not t.cells(113.6)  # the forecast expires when no active server unit remains

def test_route_detours_toxic_cells_and_escape_handles_start_inside():
    t=ToxicGround();t.observe([ground(position=(22,20))],inventory(),100)
    c=CollisionMap(50,50,bytes([1])*2500)
    c.hazard_cells=t.cells(100);c.set_forbidden(c.hazard_cells)
    assert not c.segment((20,20),(24,20),max_steps=4)
    path=c.route((20,20),(24,20),exact=True)
    assert path and all(tuple(p) not in t.cells(100) for p in path)
    t.observe([ground(2,(20,20),253)],inventory(),101)
    c.hazard_cells=t.cells(101);c.set_forbidden(c.hazard_cells)
    destination=t.escape(c,(20,20),set(),101)
    assert destination is not None and destination not in t.cells(101)
    assert max(abs(destination[i]-20) for i in (0,1))<=4

def test_namekuji_strict_hp_and_four_cell_radius(config):
    for hp,maximum,expected in [(599,1000,True),(600,1000,False),(601,1000,False),(0,1000,False),(None,1000,False),(100,None,False)]:
        c,r,s=setup(config,[]);s.update(player_hp=hp,player_max_hp=maximum)
        assert c.idle_clear(s)==expected
        a=c.plan(s,r,100)
        assert bool(a and a['skill_id']==729)==expected
    c,r,s=setup(config,[])
    s['visible_monsters']=[entity(10,1037,24)]
    assert not c.idle_clear(s)
    s['visible_monsters'][0]['position']=[25,20]
    assert c.idle_clear(s)

def test_control_nine_and_four_jounin_take_absolute_combat_priority(config):
    c,r,s=setup(config,[entity(10,1634,29)])
    targeting(c,10)
    assert c.decide(s,r,100)['skill_id']==179
    s['recent_entities'][0]['position']=[30,20]
    assert c.decide(s,r,100)['mode']=='kill'  # approach, then control on entering 9
    for count,trigger in [(3,False),(4,True)]:
        c,r,s=setup(config,[entity(10+i,1634,26+i) for i in range(count)])
        s['learned_skills'].append(dict(skill_id=500,level=1,sp_cost=1,range=0,target_flags=4))
        intent=c.decide(s,r,100)
        assert bool(intent and intent['mode']=='emergency')==trigger
        if trigger:
            a=c.plan(s,r,100)
            assert a['skill_id']==500 and a['emergency_stage']=='prepare'

def test_hp_received_preserved_on_map_transfer_and_new_connection_unknown():
    from nrobot.network_observer import Observer
    o=Observer({1315})
    assert o.hp is None and o.max_hp is None
    o.apply(dict(kind='player_stat',stat_type=5,value=500),100)
    o.apply(dict(kind='player_stat',stat_type=6,value=1000),100)
    o.apply(dict(kind='map_transfer',map='other'),101)
    assert o.hp==500 and o.max_hp==1000
    o.clear()
    assert o.hp is None and o.max_hp is None

def test_send_move_rechecks_cloud_appearing_after_planning(tmp_path,config):
    from nrobot.session_relay import HuntTargetChanged
    relay,now=relay_for(tmp_path,config)
    action=relay.plan_group_or_hunt(relay.status(),now,150,relay.collision_map())
    assert action and action['purpose']=='patrol'
    relay.toxic_ground.observe([ground(position=action['destination'])],relay.inventory,now)
    with pytest.raises(HuntTargetChanged,match='Nevoa toxica'):
        asyncio.run(relay.send_hunt_action(action,game_gate=lambda:True))
    assert not relay.upstream.packets

def test_hazard_guard_escapes_and_respects_pause_and_manual_control(tmp_path,config):
    relay,now=relay_for(tmp_path,config)
    relay.toxic_ground.observe([ground()],relay.inventory,now)
    assert asyncio.run(relay.avoid_toxic_ground(lambda:True))
    assert len(relay.upstream.packets)==1
    assert relay.hunt.reason=='desviando da nevoa toxica'
    relay.hunt.pause('paused');relay.toxic_hold_until=0
    assert not asyncio.run(relay.avoid_toxic_ground(lambda:True))
    relay.hunt.start();relay.manual_control=lambda now:True
    assert not asyncio.run(relay.avoid_toxic_ground(lambda:True))
    assert len(relay.upstream.packets)==1

def test_guard_interrupts_walk_before_entering_future_cloud(tmp_path,config):
    relay,now=relay_for(tmp_path,config)
    o=relay.tracker.observer
    o.player_motion=dict(origin=[20,20],destination=[24,20],position=[20,20],at=now,duration=1)
    relay.toxic_ground.observe([ground(position=(22,20))],relay.inventory,now)
    assert asyncio.run(relay.avoid_toxic_ground(lambda:True))
    assert len(relay.upstream.packets)==1
    record=json.loads((tmp_path/'caca_eventos.jsonl').read_text(encoding='utf-8').splitlines()[-1])
    assert record['kind']=='toxic_ground_stop' and record['destination']==[20,20]

def test_quest_collision_does_not_drop_hazards_when_allowing_portal(tmp_path,config):
    relay,now=relay_for(tmp_path,config)
    c=relay.collision_map();c.hazard_cells=frozenset({(22,20)})
    c.set_forbidden(c.hazard_cells)
    nav=relay.quests.navigation('ra_fild03',c,relay.portals,dict(kind='move',position=[24,20]))
    assert not nav.walkable((22,20))
