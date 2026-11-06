import random

from nrobot.map_navigation import CollisionMap
from nrobot.mob_scan import MobScan
from nrobot.packet_patrol import PacketPatrol


def split_map():
    """Two open areas with a full wall between them: the right side cannot be walked to."""
    width, height = 120, 60
    return CollisionMap(width, height, [int(x != 60) for y in range(height) for x in range(width)])


def test_unreachable_showmobs_spot_is_put_aside_and_the_patrol_walks_again():
    collision = split_map()
    patrol = PacketPatrol(8, random.Random(1), spacing=8)
    patrol.plan((10, 30), 0.0, 150, collision)
    patrol.update_focus([100, 30], 1.0)  # on the other side of the wall
    position, moves = (10, 30), []
    for i in range(30):  # walking along the partial route up to the wall, as the game would
        move = patrol.plan(position, 1.0+i*.5, 150, collision)
        moves.append(move)
        if move is not None:
            position = tuple(move['destination'])
        if patrol.focus is None:
            break
    assert patrol.focus is None and patrol.focus_suppressed == (100, 30)
    assert any(m is not None for m in moves)  # it walks on instead of standing still
    patrol.update_focus([100, 30], 10.0)
    assert patrol.focus is None  # not retaken right away


def test_reachable_far_showmobs_spot_is_walked_to():
    collision = CollisionMap(200, 200, [1]*40000)
    patrol = PacketPatrol(8, random.Random(1), spacing=8)
    patrol.plan((5, 5), 0.0, 150, collision)
    patrol.update_focus([190, 190], 1.0)
    move = patrol.plan((5, 5), 1.0, 150, collision)
    assert move is not None and patrol.focus == [190, 190]


def test_a_lone_monster_far_away_is_not_a_destination():
    scan = MobScan()
    scan.start('field', [1], 0, True); scan.sent(1, 0)
    scan.observe([dict(kind='viewpoint', mark_type=1, npc_id=1, position=[150, 150])], .1)
    assert scan.finish([5, 5], 4, collision=CollisionMap(200, 200, [1]*40000)) is None and scan.goal is None
