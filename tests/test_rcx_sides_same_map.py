from nrobot.rcx_sides import Sides


def test_respawn_on_same_map_keeps_pvp_rule():
    sides = Sides()
    sides.observe([{'kind': 'map_change', 'map': 'bat_c02.gat'}, {'kind': 'map_property', 'value': 3}], 1, 0)
    sides.observe([{'kind': 'map_change', 'map': 'bat_c02.gat'}], 1, 1)
    assert sides.describe() == 'PvP'
    sides.observe([{'kind': 'map_change', 'map': 'prontera.gat'}], 1, 2)
    assert sides.describe() == 'sem PvP'
