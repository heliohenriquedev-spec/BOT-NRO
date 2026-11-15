import asyncio

from nrobot.packet_patrol import PacketPatrol
from nrobot.map_navigation import CollisionMap
from test_bg_entry import relay


def test_suspension_sends_nothing_and_clears_existing_scan_destination(tmp_path):
    r=relay(tmp_path)
    patrol=r.hunt.patrol=PacketPatrol()
    patrol.focus=[40,40];patrol.goal=(40,40)
    patrol.route_cache=[(20,20),(40,40)]
    r.hunt.pending=dict(kind='move',purpose='patrol',destination=[40,40])
    r.mob_scan.goal=dict(position=[40,40]);generation=r.mob_scan._generation
    def must_not_send():raise AssertionError('automatic scan should not reach network checks')
    asyncio.run(r.send_mob_scan(game_gate=must_not_send))
    assert r.mob_scan.goal is None and r.mob_scan._generation>generation
    assert patrol.focus is None and patrol.goal is None and patrol.route_cache is None
    assert r.hunt.pending is None
    asyncio.run(r.send_mob_scan(game_gate=must_not_send))
    assert r.mob_scan._generation==generation+1  # no repeated resets on every tick
    assert r.status()['showmobs_suspended'] and r.status()['showmobs_goal'] is None


def test_open_maps_use_one_persistent_linear_plan_and_reuse_distance_matrix():
    patrol=PacketPatrol()
    collision=CollisionMap(70,70,[1]*4900)
    patrol.plan([10,10],0,100,collision)
    assert patrol.linear and patrol.corridor_plan
    assert patrol.tour._plan_matrix is patrol.tour._sweep_distances
    original=list(patrol.corridor_plan)
    first=patrol.next_block([10,10])
    patrol.heading=(-1,-1)
    assert patrol.next_block([11,11])==first
    assert patrol.corridor_plan==original


def test_collision_patrol_leaves_a_repeated_corner_without_resetting_coverage():
    patrol=PacketPatrol()
    collision=CollisionMap(70,70,[1]*4900)
    position=(10,10)
    patrol.plan(position,0,100,collision)
    blocked=patrol.goal_block
    cycle=patrol.cycle_number
    # Real server movement keeps returning to the same two cells.
    for i in range(10):
        point=(10+i%2,10)
        origin=(11-i%2,10)
        patrol.reached(point,origin,now=i+1)
    assert patrol.escape_next
    seen=set(patrol.done)
    action=patrol.plan(position,11,100,collision)
    assert action and action['purpose']=='patrol'
    assert blocked in patrol.deferred and blocked in patrol.remaining
    assert blocked not in patrol.done
    assert patrol.goal_block!=blocked and not patrol.escape_next
    assert patrol.cycle_number==cycle and seen<=patrol.done


def test_collision_patrol_suppresses_a_scan_goal_that_causes_a_loop():
    patrol=PacketPatrol()
    collision=CollisionMap(70,70,[1]*4900)
    patrol.plan((10,10),0,100,collision)
    patrol.update_focus([60,60],1)
    patrol.plan((10,10),1,100,collision)
    patrol.escape_next=True
    action=patrol.plan((10,10),2,100,collision)
    assert action and patrol.focus is None
    assert patrol.focus_suppressed==(60,60)
    patrol.update_focus([61,60],3)
    assert patrol.focus is None


def test_repeated_arrival_reports_do_not_abandon_the_showmobs_monster():
    patrol=PacketPatrol()
    collision=CollisionMap(90,90,[1]*8100)
    collision.name='yuno_fild08.gat'
    position=[10,10]
    patrol.plan(position,0,60,collision)
    patrol.update_focus([75,75],1)
    for i in range(20):
        action=patrol.plan(position,2+i,60,collision)
        if patrol.focus_reached is not None:break
        assert action and patrol.focus==[75,75]
        origin=position;position=action['destination']
        # The relay observes position, acknowledges the move, and the hunt
        # confirms its pending step: three reports of the same actual arrival.
        patrol.observe_position(position,2+i+.3,collision.name)
        patrol.reached(position,origin,now=2+i+.4)
        patrol.reached(position,origin,now=2+i+.5)
        assert not patrol.escape_next and patrol.loop_escapes==0
    assert patrol.focus_reached==(75,75)
    assert patrol.focus_suppressed is None
