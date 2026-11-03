import asyncio
import math
import os
import struct
import time
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication
from nrobot.combat_rotation import CombatRotation
from nrobot.packet_encoder import ground_skill
from nrobot.packet_hunt import PacketHunt
from nrobot.packet_settings import validate
from nrobot.session_relay import SessionRelay
from nrobot.network_targets import Entity
from nrobot.map_navigation import CollisionMap


def profile(role='offensive', distance=None):
    return dict(skill_id=1001, enabled=True, role=role, level=1, interval=30,
                effect_id=0, range_override=distance)


def snapshot(flags=4, distance=1, reach=0):
    return dict(state='tracking', player_position_recent=True, player_position=[10,10],
                player_id=1, player_sp=100, own_effects={}, own_cast_until=0,
                learned_skills=[dict(skill_id=1001, name='Custom', level=1, sp_cost=1,
                                     range=reach, target_flags=flags)],
                recent_entities=[dict(entity_id=20, position=[10+distance,10], position_age_seconds=.1)])


@pytest.mark.parametrize('flags', [4,16])
def test_self_offensive_uses_own_id_but_requires_nearby_enemy(flags):
    r=CombatRotation([profile()])
    assert r.plan(snapshot(flags, distance=3), 0, 20) is None
    a=r.plan(snapshot(flags), 0, 20)
    assert a['target_id']==1 and a['combat_target_id']==20 and a['cast_mode']=='self'
    r.sent(a,0)
    r.observe([dict(kind='skill_damage', skill_id=1001, source_id=1, target_id=20, level=1, damage_raw=50)],1,.2)
    assert r.confirmed==1 and not r.pending


def test_self_offensive_success_ack_is_execution_not_fake_damage():
    r=CombatRotation([profile()]);a=r.plan(snapshot(),0,20);r.sent(a,0)
    r.observe([dict(kind='skill_no_damage', skill_id=1001, source_id=1, target_id=1, success=True)],1,.1)
    assert not r.pending and r.confirmed==0 and r.buff_confirmed==0
    assert r.log[-1]['kind']=='rotation_execution_confirmed'


def test_override_controls_planning_navigation_and_basic_attack_priority():
    p=profile(distance=5);r=CombatRotation([p]);s=snapshot(flags=1,distance=5,reach=2)
    assert r.engagement_range(s)==5 and r.plan(s,0,20)
    assert r.soonest_offensive(s,0,20)==0
    s['recent_entities'][0]['position']=[16,10]
    assert r.plan(s,0,20) is None and math.isinf(r.soonest_offensive(s,0,20))
    p['range_override']=None
    assert r.engagement_range(s)==2


def test_invocation_needs_ground_type_but_no_enemy_and_respects_interval():
    p=profile('summon');r=CombatRotation([p],fast=True,burst=True)
    s=snapshot(flags=2,reach=4);entities=s['recent_entities'];s['recent_entities']=[]
    assert r.plan(s,0) is None  # summons require nearby targets
    s['recent_entities']=entities
    a=r.plan(s,0)
    assert a['cast_mode']=='ground' and a['target_id']==1
    r.sent(a,0)
    assert r.plan(s,2) is None  # no acknowledgement: still respects the 30s interval
    assert r.plan(s,30.1)['skill_id']==1001  # unknown lifetime permits a bounded retry of the same summon
    s['learned_skills'][0]['target_flags']=1
    assert CombatRotation([p]).plan(s,0) is None


def test_ground_packet_has_native_fields_and_frame_size():
    from nrobot.client_frame_guard import ClientFrameGuard
    a=ground_skill(10,20,1001,3,ticks=lambda:42)
    assert len(a)==22 and struct.unpack_from('<H',a)[0]==0x113
    assert struct.unpack_from('<H',a,5)[0]==3 and struct.unpack_from('<H',a,9)[0]==1001
    assert struct.unpack_from('<H',a,12)[0]==10 and struct.unpack_from('<H',a,20)[0]==20
    guard=ClientFrameGuard()
    assert guard.feed(a[:10])==[] and not guard.ready
    assert guard.feed(a[10:])==[0x113] and guard.ready


@pytest.mark.parametrize('distance',[None,0,8,32])
def test_profile_settings_preserve_custom_distance(distance):
    p=profile('summon',distance)
    assert validate({'skill_profiles':[p]})['skill_profiles'][0]==p


@pytest.mark.parametrize('distance',[-1,33,True,1.5])
def test_invalid_distances_are_rejected(distance):
    with pytest.raises(ValueError):validate({'skill_profiles':[profile(distance=distance)]})


class Writer:
    def __init__(self):self.packets=[]
    def write(self,p):self.packets.append(p)
    async def drain(self):pass


@pytest.mark.parametrize('ground',[False,True])
def test_relay_sends_self_or_ground_packet_and_validates_cells(tmp_path,monkeypatch,ground):
    r=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    r.hunt=PacketHunt();r.hunt.start();r.hunt.target=20
    r.rotation=CombatRotation([profile('summon' if ground else 'offensive')])
    o=r.tracker.observer;now=time.monotonic()
    o.player_id,o.player,o.player_at,o.sp=1,[10,10],now,100
    o.skills={1001:dict(skill_id=1001,level=1,sp_cost=1,range=3 if ground else 0,target_flags=2 if ground else 4)}
    o.registry.update(Entity(20,1051,10,11,now,'monster'))
    r.upstream=Writer()
    cells=bytearray([1]*30*30)
    if ground:cells[10*30+11]=0
    collision=CollisionMap(30,30,cells)
    monkeypatch.setattr(r,'collision_map',lambda:collision)
    a=r.rotation.plan(r.status(),now,20)
    assert asyncio.run(r.send_rotation_action(a,game_gate=lambda:True))
    packet=r.upstream.packets[-1]
    if ground:
        point=[struct.unpack_from('<H',packet,12)[0],struct.unpack_from('<H',packet,20)[0]]
        assert len(packet)==22 and collision.walkable(point) and point!=[11,10]
    else:assert len(packet)==25 and struct.unpack_from('<I',packet,21)[0]==1


def test_ui_locks_names_and_preserves_skill_range_across_refresh(tmp_path,monkeypatch):
    from nrobot.packet_panel import PacketPanel
    from nrobot.skill_panel import SkillPanel
    app=QApplication.instance() or QApplication([])
    p=PacketPanel()
    assert p.allowed_players.isReadOnly()
    p.edit_allowed_players.click();assert not p.allowed_players.isReadOnly()
    p.edit_allowed_players.click();assert p.allowed_players.isReadOnly()
    p.save_timer.stop()
    panel=SkillPanel();meta=snapshot()['learned_skills']
    panel.update_catalog(meta,{})
    row=panel.rows[1001];row['range'].setValue(7);row['role'].setCurrentIndex(0)
    for _ in range(5):panel.update_catalog(meta,{})
    assert panel.rows[1001]['range'] is row['range'] and panel.profiles()[0]['range_override']==7
    row['range'].setValue(-1)
    assert panel.profiles()[0]['range_override'] is None
    # Prevent this smoke test from writing the real user's settings on close.
    monkeypatch.setattr(p,'autosave',lambda:None)
    monkeypatch.setattr(p,'save_ui',lambda:None)
    p.save_timer.stop()
    p.close();panel.close()
