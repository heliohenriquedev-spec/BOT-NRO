import asyncio
import time
import pytest
from nrobot.packet_hunt import PacketHunt
from nrobot.map_navigation import CollisionMap
from nrobot.network_targets import Entity
from nrobot.session_relay import SessionRelay, HuntTargetChanged


def state(monster):
    return dict(state='tracking',player_position_recent=True,player_position=[10,10],player_sp=100,
                engagement_range=6,learned_skills=[],recent_entities=[dict(entity_id=20,position=monster,
                position_age_seconds=.1)])


def test_two_cells_must_approach_then_attack_without_losing_target():
    collision=CollisionMap(30,30,bytes([1])*900)
    hunt=PacketHunt();hunt.start()
    s=state([12,10]);action=hunt.plan(s,0,collision=collision)
    assert action['kind']=='move' and action['destination']==[11,10]
    assert hunt.target==20 and not hunt.excluded_until
    s['player_position']=[11,10]
    action=hunt.plan(s,1,collision=collision)
    assert action==dict(kind='attack',target_id=20)


def test_toggle_switches_between_melee_approach_kite_and_holding_at_skill_range():
    collision=CollisionMap(30,30,bytes([1])*900)
    hunt=PacketHunt();hunt.start();s=state([12,10])
    hunt.melee_approach,hunt.kite=False,True
    retreat=hunt.plan(s,0,collision=collision)
    assert retreat['purpose']=='keep_distance'
    hunt.melee_approach,hunt.kite=True,False
    approach=hunt.plan(s,1,collision=collision)
    assert approach['destination']==[11,10] and approach.get('purpose')!='keep_distance'
    hunt.melee_approach,hunt.kite=False,True
    assert hunt.plan(s,2,collision=collision)['purpose']=='keep_distance'
    assert hunt.target==20


def test_both_off_waits_at_skill_range_without_walking_or_retreating():
    collision=CollisionMap(30,30,bytes([1])*900)
    hunt=PacketHunt();hunt.start();hunt.melee_approach=hunt.kite=False
    assert hunt.plan(state([12,10]),0,collision=collision) is None  # in skill range: no walk, no retreat
    far=hunt.plan(state([25,10]),1,collision=collision)
    assert far['kind']=='move' and far['destination'][0]<=19  # only up to the skills' range (6)


def test_basic_attack_interleaves_only_with_the_target_in_reach():
    collision=CollisionMap(30,30,bytes([1])*900)
    hunt=PacketHunt();hunt.start();hunt.melee_approach=hunt.kite=False
    assert hunt.plan(state([11,10]),0,collision=collision)==dict(kind='attack',target_id=20)
    hunt.auto_attacks=False
    assert hunt.plan(state([11,10]),1,collision=collision) is None


def test_old_settings_keep_their_behaviour_and_both_movements_cannot_be_on():
    from nrobot.packet_settings import validate
    old_kite=validate({'auto_attacks':False})
    assert (old_kite['melee_approach'],old_kite['kite'])==(False,True)
    old_melee=validate({'auto_attacks':True})
    assert (old_melee['melee_approach'],old_melee['kite'])==(True,False)
    assert validate({'auto_attacks':True,'melee_approach':False,'kite':False})['kite'] is False
    with pytest.raises(ValueError,match='kite'):
        validate({'melee_approach':True,'kite':True})


def test_blocked_diagonal_is_not_basic_attack_reach():
    cells=bytearray([1])*900;cells[10*30+11]=0
    collision=CollisionMap(30,30,cells)
    hunt=PacketHunt();hunt.start()
    action=hunt.plan(state([11,11]),0,collision=collision)
    assert action['kind']=='move' and collision.walkable(action['destination'])
    assert not collision.melee_reachable([10,10],[11,11])


def test_revalidation_keeps_target_and_does_not_defer_it():
    hunt=PacketHunt();hunt.start();hunt.target=20;hunt.engaged=20
    hunt.replan_action(1,'alvo mudou de celula')
    assert hunt.target==hunt.engaged==20 and not hunt.excluded_until
    assert hunt.ready_at==1.05


def test_planned_adjacent_attack_passes_relay_validation(tmp_path,monkeypatch):
    relay=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    relay.hunt=PacketHunt();relay.hunt.start()
    observer=relay.tracker.observer;now=time.monotonic()
    observer.player_id,observer.player,observer.player_at=1,[10,10],now
    observer.registry.update(Entity(20,1051,12,10,now,'monster'))
    collision=CollisionMap(30,30,bytes([1])*900)
    monkeypatch.setattr(relay,'collision_map',lambda:collision)
    class Writer:
        def __init__(self):self.packets=[]
        def write(self,p):self.packets.append(p)
        async def drain(self):pass
    relay.upstream=Writer()
    s=relay.status();s['engagement_range']=6
    action=relay.hunt.plan(s,now,collision=collision)
    assert action['kind']=='move' and action['destination']==[11,10]
    observer.player=[11,10]
    s=relay.status();s['engagement_range']=6
    action=relay.hunt.plan(s,now+.1,collision=collision)
    assert action['kind']=='attack'
    asyncio.run(relay.send_hunt_action(action,game_gate=lambda:True))
    assert len(relay.upstream.packets)==1
