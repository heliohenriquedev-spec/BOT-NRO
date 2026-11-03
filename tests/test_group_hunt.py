import asyncio
import math
import os
import time
import pytest
from nrobot.group_hunt import GroupHunt
from nrobot.packet_settings import validate
from nrobot.packet_hunt import PacketHunt
from nrobot.session_relay import SessionRelay,HuntTargetChanged
from nrobot.network_targets import Entity
from nrobot.map_navigation import CollisionMap
from nrobot.combat_rotation import CombatRotation


@pytest.fixture
def relay(tmp_path,monkeypatch):
    r=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    r.hunt=PacketHunt()
    r.apply_settings(dict(group_enabled=True,group_leader='Lider',group_members=['Amigo'],patrol=False))
    r.hunt.start()
    now=time.monotonic();o=r.tracker.observer
    o.player_id,o.player,o.player_at,o.sp=2000001,[10,10],now,100
    o.walk_speed_ms=200
    r.player_names[2000002]='Lider'
    r.player_tracks[2000002]=Entity(2000002,26,20,10,now,'player')
    collision=CollisionMap(40,40,bytes([1])*1600)
    monkeypatch.setattr(r,'collision_map',lambda:collision)
    class Writer:
        def __init__(self):self.packets=[]
        def write(self,p):self.packets.append(p)
        async def drain(self):pass
    r.upstream=Writer()
    return r,collision


def test_follow_path_is_valid_and_sendable_without_patrol(relay):
    r,c=relay;now=time.monotonic()
    action=r.plan_group_or_hunt(r.status(),now,200,c)
    assert action['purpose']=='group_follow' and action['target_id'] is None
    assert c.segment([10,10],action['destination'],max_steps=4)
    assert math.dist(action['destination'],[20,10])<10
    asyncio.run(r.send_hunt_action(action,game_gate=lambda:True))
    assert len(r.upstream.packets)==1


def test_only_follow_rejects_direct_attack_and_skill(relay):
    r,c=relay;r.settings['group_follow_only']=True
    o=r.tracker.observer;now=time.monotonic();o.player=[18,10]
    o.registry.update(Entity(111000001,1037,19,10,now,'monster'))
    r.group.target_id=111000001;r.group.target_at=now
    action=r.plan_group_or_hunt(r.status(),now,200,c)
    assert action is None  # already close to leader, do not attack nearby monster
    with pytest.raises(HuntTargetChanged):
        asyncio.run(r.send_hunt_action(dict(kind='attack',target_id=111000001),game_gate=lambda:True))
    o.skills[29]=dict(skill_id=29,level=1,sp_cost=1,range=0,target_flags=4)
    r.rotation=CombatRotation([dict(skill_id=29,level=1,enabled=True,role='buff',effect_id=12,interval=1)])
    action=r.rotation.plan(r.status(),now)
    assert not asyncio.run(r.send_rotation_action(action,game_gate=lambda:True))
    assert not r.upstream.packets


def test_follower_uses_leader_target_even_when_another_monster_is_closer(relay):
    r,c=relay;o=r.tracker.observer;now=time.monotonic();o.player=[18,10]
    o.registry.update(Entity(111000001,1037,19,10,now,'monster'))
    o.registry.update(Entity(111000002,1037,23,10,now,'monster'))
    r.group.observe([dict(kind='normal_attack',source_id=2000002,target_id=111000002)],2000002,now)
    action=r.plan_group_or_hunt(r.status(),now,200,c)
    assert action['target_id']==111000002 and r.hunt.target==111000002
    with pytest.raises(HuntTargetChanged):
        asyncio.run(r.send_hunt_action(dict(kind='attack',target_id=111000001),game_gate=lambda:True))


def test_leader_target_change_and_disappearance_are_respected(relay):
    r,c=relay;now=time.monotonic()
    r.group.observe([dict(kind='skill_cast',source_id=2000002,target_id=111000001)],2000002,now)
    assert r.group.target_id==111000001
    r.group.observe([dict(kind='skill_damage',source_id=2000002,target_id=111000002)],2000002,now)
    assert r.group.target_id==111000002
    r.player_tracks.clear()
    assert r.plan_group_or_hunt(r.status(),now,200,c) is None
    assert not r.upstream.packets and not r.group_combat_allowed()


def test_stale_follow_move_is_revalidated_when_leader_moves(relay):
    r,c=relay;now=time.monotonic()
    action=r.plan_group_or_hunt(r.status(),now,200,c)
    r.player_tracks[2000002]=Entity(2000002,26,10,20,now,'player')
    with pytest.raises(HuntTargetChanged):
        asyncio.run(r.send_hunt_action(action,game_gate=lambda:True))
    assert not r.upstream.packets


def test_no_independent_hunt_or_patrol_when_leader_is_missing(relay):
    r,c=relay;now=time.monotonic()
    r.player_tracks.clear()
    r.tracker.observer.registry.update(Entity(111000001,1037,11,10,now,'monster'))
    assert r.plan_group_or_hunt(r.status(),now,200,c) is None
    assert r.hunt.target is None


def test_group_names_are_allowed_but_unlisted_players_still_hold(relay):
    r,_=relay
    r.presence.remember_names({2000002:'LIDER',2000003:'Amigo',2000004:'Outro'})
    assert r.presence.ignored(2000002) and r.presence.ignored(2000003)
    assert not r.presence.ignored(2000004)


def test_same_named_players_are_ambiguous_and_not_followed():
    group=GroupHunt();names={2000002:'Lider',2000003:'Lider'}
    assert group.leader({'group_leader':'Lider'},names,{2000002:object(),2000003:object()}) is None


def test_group_settings_validate_and_roundtrip():
    v=validate(dict(group_enabled=True,group_leader=' Lider ',group_follow_only=True,group_distance=4))
    assert v['group_leader']=='Lider' and v['group_follow_only']
    for settings in (dict(group_enabled=True),dict(group_distance=1),dict(group_role='bad')):
        with pytest.raises(ValueError):validate(settings)


def test_group_panel_fields_save_without_starting_connection(monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from nrobot.packet_panel import PacketPanel
    app=QApplication.instance() or QApplication([])
    panel=PacketPanel();panel.group_enabled.setChecked(True);panel.group_leader.setText('Lider')
    panel.group_only.setChecked(True);panel.group_members.setPlainText('Amigo\nOutro membro')
    settings=validate(panel.settings())
    assert settings['group_follow_only'] and settings['group_members']==['Amigo','Outro membro']
    panel.save_timer.stop();monkeypatch.setattr(panel,'save_ui',lambda:None);panel.close()


def test_hidden_leader_is_not_followed_at_stale_coordinates(relay):
    r,c=relay;now=time.monotonic()
    r.presence.observe([dict(kind='option_change',entity_id=2000002,option=0x40)],2000001,now)
    assert r.group_leader_id() is None
    assert r.plan_group_or_hunt(r.status(),now,200,c) is None
    assert not r.group_combat_allowed()
