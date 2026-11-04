import math
import struct
import pytest
from nrobot.packet_hunt import PacketHunt
from nrobot.network_observer import Observer
from nrobot.map_navigation import CollisionMap
from nrobot.packet_reader import decode
from nrobot.continuous_observer import ContinuousTracker


def state(player,monster):
    return dict(state='tracking',player_position_recent=True,player_position=player,engagement_range=6,
                recent_entities=[dict(entity_id=111000001,position=monster,position_age_seconds=.1)])


def test_range_six_kites_to_five_without_passing_the_requested_spacing():
    hunt=PacketHunt();hunt.auto_attacks=False;hunt.melee_approach=False;hunt.kite=True;hunt.start()
    collision=CollisionMap(40,40,bytes([1])*1600)
    action=hunt.plan(state([20,20],[21,20]),0,200,collision)
    assert action['purpose']=='keep_distance' and action['destination']==[16,20]
    assert math.dist(action['destination'],[21,20])==5
    assert hunt.plan(state([16,20],[21,20]),1,200,collision) is None
    approach=hunt.plan(state([15,20],[21,20]),2,200,collision)
    assert approach['destination']==[16,20]


def test_kiting_does_not_reuse_rejected_cells_or_cross_them():
    hunt=PacketHunt();hunt.auto_attacks=False;hunt.melee_approach=False;hunt.kite=True;hunt.start()
    collision=CollisionMap(40,40,bytes([1])*1600)
    hunt.blocked_until[(16,20)]=10
    action=hunt.plan(state([20,20],[21,20]),0,200,collision)
    assert action['destination']!=[16,20]
    assert collision.segment([20,20],action['destination'],{(16,20)},max_steps=4)
    assert math.dist(action['destination'],[21,20])<=5


def test_monster_position_correction_overrides_motion_with_exact_received_cell():
    tracker=ContinuousTracker({1037},player_ttl=None,idle_timeout=None,entity_ttl=None)
    o=tracker.observer;o.player=[10,10];o.player_at=0
    o.apply(dict(kind='appearance',entity_id=111000001,species_id=1037,position=[12,10],walk_speed_ms=200),0)
    o.apply(dict(kind='move',entity_id=111000001,position=[12,10],destination=[18,10]),.1)
    assert o.registry.entities[111000001].destination==(18,10)
    o.apply(decode(struct.pack('<HIHH',0x88,111000001,13,11)),.2)
    entity=o.registry.entities[111000001]
    assert entity.combat_bounds(50)==([[13,11]],False)
    assert entity.destination is None and entity.path is None
    e=tracker.snapshot(.3)['recent_entities'][0]
    assert e['last_received_position']==[13,11] and e['position_source']=='server_cell'


def test_own_broadcast_walk_keeps_destination_path_and_acknowledges_hunt():
    o=Observer({1037});o.player_id=2003137;o.player=[10,10];o.player_at=0
    event=dict(kind='move',entity_id=2003137,position=[10,10],destination=[14,10])
    o.apply(event,0)
    assert o.player==[14,10] and o.player_motion['destination']==[14,10]
    assert o.combat_positions(0)[0]==[10,10]
    hunt=PacketHunt();hunt.start();hunt.sent(dict(kind='move',target_id=111000001,
                    origin=[10,10],destination=[14,10],wait_seconds=.8),0)
    hunt.observe([event],2003137,.1)
    assert hunt.pending['movement_acknowledged']


def test_moving_appearance_uses_collision_path_not_line_through_wall():
    cells=bytearray([1])*400
    for y in range(4,10):cells[y*20+7]=0
    collision=CollisionMap(20,20,cells)
    o=Observer({1037});o.collision_provider=lambda:collision
    o.apply(dict(kind='appearance',entity_id=111000001,species_id=1037,position=[5,6],
                 destination=[9,6],walk_speed_ms=200),0)
    e=o.registry.entities[111000001]
    assert e.path is not None
    for step in range(30):
        for cell in e.combat_bounds(step*.1)[0]:assert collision.walkable(cell)


def test_unresolved_path_keeps_received_endpoints_instead_of_inventing_a_cell(monkeypatch):
    o=Observer({1037});monkeypatch.setattr(o,'walk_path',lambda a,b:None)
    o.apply(dict(kind='appearance',entity_id=111000001,species_id=1037,position=[5,6],
                 destination=[9,6],walk_speed_ms=200),0)
    e=o.registry.entities[111000001]
    assert e.motion_uncertain and e.combat_bounds(10)==([[5,6],[9,6]],False)


def test_diagonal_kite_reaches_five_and_waits_for_diagonal_travel_time():
    hunt=PacketHunt();hunt.auto_attacks=False;hunt.melee_approach=False;hunt.kite=True;hunt.start()
    collision=CollisionMap(40,40,bytes([1])*1600)
    action=hunt.plan(state([20,20],[21,21]),0,200,collision)
    assert math.dist(action['destination'],[21,21])==5
    dx,dy=[abs(action['destination'][i]-[20,20][i]) for i in (0,1)]
    assert dx and dy
    assert action['wait_seconds']==pytest.approx((max(dx,dy)+.4*min(dx,dy))*.2)
