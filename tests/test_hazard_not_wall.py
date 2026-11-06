from nrobot.map_navigation import CollisionMap
from nrobot.packet_hunt import PacketHunt


def test_monsters_around_a_character_standing_in_a_skill_area_are_not_behind_a_wall():
    collision = CollisionMap(30, 30, [1]*900)
    hazard = {(x, y) for x in range(10, 18) for y in range(10, 18)}
    collision.set_forbidden(hazard)
    hunt = PacketHunt.__new__(PacketHunt)
    hunt.wall_checks = {}
    hunt.events = []
    hunt.record = lambda kind, **data: hunt.events.append(kind)
    near = [{'entity_id': 1, 'position': [15, 14]}, {'entity_id': 2, 'position': [13, 16]}]
    assert hunt.reachable_targets(near, collision, (14, 14), 0) == near
    assert 'target_behind_wall' not in hunt.events
    assert collision.forbidden == frozenset(hazard)  # routes still keep off the area


def test_plain_view_keeps_real_walls():
    cells = [1]*900
    for y in range(30):
        cells[y*30+15] = 0
    collision = CollisionMap(30, 30, cells)
    collision.set_forbidden({(5, 5)})
    plain = collision.plain()
    assert plain.walkable((5, 5)) and not collision.walkable((5, 5))
    assert not plain.line_clear((10, 10), (20, 10))
