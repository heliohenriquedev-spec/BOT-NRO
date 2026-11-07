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
