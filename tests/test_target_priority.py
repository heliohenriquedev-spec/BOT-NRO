from nrobot.packet_hunt import PacketHunt


def state(player, targets):
    return {'state': 'tracking', 'player_position_recent': True, 'player_position': player,
            'recent_entities': [{'entity_id': identity, 'position': position} for identity, position in targets]}


def test_nearer_target_does_not_preempt_locked_target():
    hunt = PacketHunt()
    hunt.start()
    action = hunt.plan(state([10, 10], [(20, [30, 10])]), 0, 100)
    hunt.sent(action, 0)
    targets = [(20, [30, 10]), (21, [15, 10])]
    assert hunt.plan(state([10, 10], targets), .1) is None
    hunt.observe([{'kind': 'position', 'entity_id': 1, 'position': [14, 10]}], 1, .2)
    assert hunt.plan(state([14, 10], targets), .3)['target_id'] == 20
    assert 20 not in hunt.excluded_until
    assert not any(e['kind'] == 'target_switched' for e in hunt.drain_diagnostics())
    assert hunt.plan(state([14, 10], [(20, [30, 10])]), .4)['target_id'] == 20


def test_small_distance_difference_does_not_change_focus():
    hunt = PacketHunt()
    hunt.start()
    hunt.plan(state([10, 10], [(20, [20, 10])]), 0)
    action = hunt.plan(state([10, 10], [(20, [20, 10]), (21, [19, 10])]), .1)
    assert action['target_id'] == 20


def test_focus_survives_new_candidates_and_long_chase():
    hunt = PacketHunt()
    hunt.start()
    assert hunt.plan(state([10, 10], [(20, [20, 10])]), 0)['target_id'] == 20
    assert hunt.plan(state([10, 10], [(20, [20, 10]), (21, [11, 10])]), 1)['target_id'] == 20
    assert 20 not in hunt.excluded_until
    assert hunt.plan(state([10, 10], [(20, [20, 10])]), 2)['target_id'] == 20
    # Progressing chase is not abandoned by the old 35-second/12-step cap.
    hunt.attempts = 100
    assert hunt.plan(state([10, 10], [(20, [20, 10])]), 100)['target_id'] == 20
