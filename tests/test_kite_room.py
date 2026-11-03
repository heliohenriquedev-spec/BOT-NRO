import math

from nrobot.map_navigation import CollisionMap
from nrobot.packet_hunt import PacketHunt
from tests.test_map_skills_melee import hunt_state


def kite_hunt():
    hunt = PacketHunt()
    hunt.auto_attacks = False
    hunt.start()
    return hunt


def field(walls):
    cells = bytearray([1]*(40*40))
    for x, y in walls:
        cells[y*40+x] = 0
    return CollisionMap(40, 40, cells)


def test_cornered_against_a_wall_kites_sideways_to_open_ground():
    # Wall right behind (x <= 8); the monster comes from the east.
    collision = field([(x, y) for x in range(9) for y in range(40)])
    retreat = kite_hunt().plan(hunt_state([9, 20], [11, 20]), 0, collision=collision)
    assert retreat['purpose'] == 'keep_distance'
    destination = retreat['destination']
    assert destination[1] != 20 and collision.segment([9, 20], destination, max_steps=4)
    assert math.dist(destination, [11, 20]) >= 2


def test_dead_end_pocket_is_left_instead_of_backing_deeper():
    # A dead-end pocket (closed at x <= 5) open only to the east, where the monster is.
    walls = [(x, y) for x in range(0, 20) for y in (16, 24)] + [(x, y) for x in range(0, 6) for y in range(16, 25)]
    walls += [(x, y) for x in range(0, 20) for y in range(0, 16)] + [(x, y) for x in range(0, 20) for y in range(25, 40)]
    walls = [w for w in walls if not (6 <= w[0] < 20 and 19 <= w[1] <= 21)]
    collision = field(walls)
    hunt = kite_hunt()
    retreat = hunt.plan(hunt_state([8, 20], [11, 20]), 0, collision=collision)
    # Backing into the pocket leaves no room: it slips past the monster toward open ground.
    assert retreat['reposition'] and retreat['destination'][0] >= 9
    assert collision.segment([8, 20], retreat['destination'], max_steps=4)
    assert math.dist(retreat['destination'], [11, 20]) >= 2


def test_open_ground_keeps_the_plain_retreat():
    retreat = kite_hunt().plan(hunt_state([20, 20], [22, 20]), 0, collision=field([]))
    assert retreat['purpose'] == 'keep_distance' and not retreat.get('reposition')
    assert retreat['destination'][0] < 20
