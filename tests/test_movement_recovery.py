"""REDE-32: recover from authoritative corrections without blind retries."""
import pytest

from nrobot.packet_hunt import PacketHunt


def state(player, entities=((20, (8, 0)),)):
    return {'state': 'tracking', 'player_position_recent': True, 'player_position': list(player),
            'recent_entities': [{'entity_id': i, 'position': list(p)} for i, p in entities]}


def walking(speed=400):
    hunt = PacketHunt()
    hunt.start()
    action = hunt.plan(state((0, 0)), 0, speed)
    hunt.sent(action, 0)
    return hunt, action


def test_own_correction_retains_target_and_replans_after_failed_step():
    hunt, action = walking()
    hunt.observe([{'kind': 'position', 'entity_id': 1, 'position': [0, 0]}], 1, .1)
    assert hunt.pending is None and hunt.enabled
    assert 20 not in hunt.excluded_until and hunt.target == 20
    assert hunt.movement_failures == 1
    assert tuple(action['destination']) in hunt.blocked_until
    assert hunt.plan(state((0, 0), ((20, (8, 0)), (21, (0, 1)))), .2) is None
    assert hunt.plan(state((0, 0), ((20, (8, 0)), (21, (0, 1)))), .3) is None
    assert hunt.target == 20
    events = hunt.drain_diagnostics()
    assert any(e['kind'] == 'movement_failed' and e['position'] == [0, 0] for e in events)
    assert hunt.drain_diagnostics() == []


def test_partial_progress_replans_from_correction_without_excluding_target():
    hunt, action = walking()
    hunt.observe([{'kind': 'position', 'entity_id': 1, 'position': [2, 0]}], 1, .1)
    assert hunt.pending is None and not hunt.excluded_until
    assert hunt.plan(state((2, 0)), .11) is None
    new = hunt.plan(state((2, 0)), .2)
    assert new['origin'] == [2, 0] and new['target_id'] == 20
    assert hunt.movement_corrections == 1


def test_shortened_server_route_adjusts_wait_without_claiming_arrival():
    hunt, action = walking(100)
    hunt.observe([{'kind': 'player_move', 'position': [0, 0], 'destination': [2, 0]}], 1, .05)
    assert hunt.pending['destination'] == [2, 0]
    assert hunt.pending['movement_acknowledged']
    assert hunt.pending['wait_until'] == pytest.approx(.25)
    assert hunt.plan(state((2, 0)), .1) is None
    new = hunt.plan(state((2, 0)), .4)
    assert new['target_id'] == 20 and new['origin'] == [2, 0]


def test_missing_acceptance_has_short_deadline_and_does_not_resend():
    hunt, action = walking(1000)
    assert action['wait_seconds'] >= 4
    assert hunt.plan(state((0, 0)), .89) is None
    assert hunt.pending
    assert hunt.plan(state((0, 0)), .91) is None
    assert hunt.pending is None and hunt.enabled
    assert hunt.plan(state((0, 0)), 1.1) is None
    assert hunt.moves == 1
    assert 'confirmação' in hunt.reason


def test_monster_motion_is_not_own_rejection_and_unrelated_route_is_not_ack():
    hunt, action = walking()
    hunt.observe([{'kind': 'position', 'entity_id': 20, 'position': [0, 0]},
                  {'kind': 'player_move', 'position': [0, 0], 'destination': [0, 8]}], 1, .1)
    assert not hunt.pending['movement_acknowledged']
    assert hunt.movement_failures == hunt.movement_corrections == 0
    assert hunt.drain_diagnostics()[0]['kind'] == 'target_motion'


def test_failed_destination_is_not_retried_for_a_different_target_without_map():
    hunt, action = walking()
    hunt.observe([{'kind': 'position', 'entity_id': 1, 'position': [0, 0]}], 1, .1)
    # A new target behind the same attempted waypoint must also wait.
    assert hunt.plan(state((0, 0), ((21, (9, 0)),)), .3) is None
    assert 21 not in hunt.excluded_until and hunt.target == 21
    assert hunt.moves == 1


def test_position_changed_before_send_discards_stale_command_without_sending(tmp_path):
    import asyncio
    import time
    from nrobot.session_relay import SessionRelay, HuntTargetChanged
    from nrobot.network_targets import Entity
    async def scenario():
        relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
        relay.hunt, action = walking()
        relay.hunt.pending = None
        class Writer:
            def write(self, payload): raise AssertionError('stale movement must not be sent')
            async def drain(self): pass
        relay.upstream = Writer()
        observer = relay.tracker.observer
        observer.player_id, observer.player, observer.player_at = 1, [1, 0], time.monotonic()
        observer.registry.update(Entity(20, 1051, 8, 0, time.monotonic(), 'monster'))
        with pytest.raises(HuntTargetChanged, match='corrigida'):
            await relay.send_hunt_action(action, game_gate=lambda: True)
        assert relay.hunt.enabled and relay.hunt.pending is None
    asyncio.run(scenario())
