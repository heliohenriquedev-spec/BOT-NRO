import random

from nrobot.map_navigation import CollisionMap
from nrobot.packet_patrol import PacketPatrol


def test_new_scan_does_not_reverse_an_unfinished_trip():
    patrol=PacketPatrol()
    patrol.update_focus([50,20],1)
    patrol.goal=(50,20)
    patrol.update_focus([10,50],2)
    assert patrol.focus==[50,20] and patrol.goal==(50,20)


def test_scan_does_not_return_to_any_reached_cluster_until_next_cycle():
    patrol=PacketPatrol()
    collision=CollisionMap(100,100,[1]*10000)
    patrol.update_focus([40,40],1)
    patrol.plan([40,40],2,100,collision)
    patrol.update_focus([75,75],3)
    patrol.plan([75,75],4,100,collision)
    patrol.update_focus([42,42],5)
    assert patrol.focus is None
    patrol.new_cycle([75,75])
    patrol.update_focus([42,42],6)
    assert patrol.focus==[42,42]


def test_resume_rotates_circuit_without_dropping_unvisited_points():
    collision=CollisionMap(100,100,[1]*10000)
    patrol=PacketPatrol(rng=random.Random(7))
    patrol.plan([10,10],0,100,collision)
    old_goal=patrol.goal_block
    original=list(patrol.sweep_order)
    assert old_goal in patrol.remaining
    patrol.plan([75,75],4,100,collision)
    assert old_goal in patrol.remaining and old_goal not in patrol.done
    index=original.index(patrol.sweep_order[0])
    assert patrol.sweep_order==original[index:]+original[:index]
    distances=patrol.tour.distances([75,75])
    pending=patrol.remaining-set(patrol.deferred)
    assert distances[patrol.next_block([75,75])] <= min(distances[b] for b in pending)+patrol.tour.spacing*.5
