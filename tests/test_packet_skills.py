"""REDE-36: skill availability, exact wire fields, response and fallback."""
import asyncio
import struct
import time

import pytest

from nrobot.packet_reader import decode
from nrobot.packet_hunt import PacketHunt
from nrobot.network_observer import Observer
from nrobot.network_targets import Entity
from nrobot.session_relay import SessionRelay, HuntTargetChanged


def metadata():
    return {'skill_id': 524, 'level': 10, 'sp_cost': 20, 'range': 7, 'target_flags': 1, 'name': 'Kunai'}


def ready(sp=100):
    return {'state': 'tracking', 'player_position_recent': True, 'player_position': [10, 10],
            'recent_entities': [{'entity_id': 20, 'position': [11, 10]}],
            'player_sp': sp, 'learned_skills': [metadata()], 'player_position_age_seconds': 3}


def hunt():
    result = PacketHunt(use_skills=True)
    result.start()
    return result


def test_skill_list_add_update_and_sp_decode_into_observer():
    entry = struct.pack('<HIHHH24sB', 524, 1, 10, 20, 7, b'Kunai', 0)
    packet = struct.pack('<HH', 0x10f, 4+len(entry))+entry
    event = decode(packet)
    assert event['skills'] == [metadata()]
    observer = Observer({1037})
    observer.apply(event, 0)
    observer.apply(decode(struct.pack('<HHI', 0xb0, 7, 100)), 0)
    assert observer.sp == 100 and observer.skills[524] == metadata()
    update = decode(struct.pack('<5HB', 0x10e, 524, 10, 18, 7, 0))
    observer.apply(update, 1)
    assert observer.skills[524]['sp_cost'] == 18
    assert decode(struct.pack('<H', 0x111)+entry)['skills'] == [metadata()]
    observer.clear()
    assert observer.sp is None and not observer.skills


@pytest.mark.parametrize('sp,skills', [(None, [metadata()]), (19, [metadata()]), (100, []),
                                     (100, [{**metadata(), 'level': 9}])])
def test_unknown_or_insufficient_resources_fall_back_to_normal(sp, skills):
    planner = hunt()
    state = ready(sp)
    state['learned_skills'] = skills
    assert planner.plan(state, 0) == {'kind': 'attack', 'target_id': 20}


def test_skill_waits_for_matching_response_and_respects_cooldown():
    planner = hunt()
    action = planner.plan(ready(), 0)
    assert action == {'kind': 'skill', 'target_id': 20, 'skill_id': 524, 'level': 10}
    planner.sent(action, 0)
    assert planner.plan(ready(), .1) is None
    response = {'kind': 'skill_damage', 'source_id': 1, 'target_id': 20, 'skill_id': 524, 'level': 10, 'damage_raw': 100}
    planner.observe([{**response, 'source_id': 2}, {**response, 'target_id': 21},
                     {**response, 'skill_id': 525}, {**response, 'level': 9}], 1, .2)
    assert planner.pending and planner.confirmed_skills == 0
    planner.observe([response], 1, .3)
    assert planner.confirmed_skills == planner.confirmed_attacks == 1
    assert planner.plan(ready(), .4) is None
    assert planner.plan(ready(), .5)['kind'] == 'skill'
    assert planner.plan(ready(), 1.1)['kind'] == 'skill'


def test_skill_waits_for_recent_target_instead_of_old_snapshot():
    planner = hunt()
    state = ready()
    state['recent_entities'][0]['position_age_seconds'] = 4.359
    assert planner.plan(state, .1) is None
    assert planner.pending is None and planner.confirmed_attacks == 0
    assert 'antiga' in planner.skill_reason
    state['recent_entities'][0]['position_age_seconds'] = .1
    planner.start()
    assert planner.plan(state, 2.1)['kind'] == 'skill'


def test_reached_moving_destination_with_old_start_position_does_not_wait_forever():
    planner = hunt()
    state = ready()
    state['player_position'] = [320, 20]
    state['recent_entities'][0].update(position=[315, 28], destination=[320, 20], position_age_seconds=4.797)
    assert planner.plan(state, 0) is None
    assert planner.target is None and 20 in planner.excluded_until
    state['recent_entities'].append({'entity_id': 21, 'position': [321, 20], 'position_age_seconds': .1})
    assert planner.plan(state, .1)['target_id'] == 21


def test_skill_failure_and_timeout_allow_validated_retry_without_basic_fallback():
    for failure in (True, False):
        planner = hunt()
        planner.sent(planner.plan(ready(), 0), 0)
        if failure:
            planner.observe([decode(struct.pack('<4H2B', 0x110, 524, 0, 0, 0, 1))], 1, .1)
        else:
            assert planner.plan(ready(), 4.1) is None
        assert planner.enabled
        assert not planner.skill_disabled and planner.skill_failures == 1
        assert planner.plan(ready(), 5)['kind'] == 'skill'
        planner.start()
        assert planner.plan(ready(), 6)['kind'] == 'skill'


def test_removal_does_not_confirm_skill_damage():
    planner = hunt()
    planner.sent(planner.plan(ready(), 0), 0)
    planner.observe([{'kind': 'remove', 'entity_id': 20}], 1, .1)
    assert planner.pending is None and planner.confirmed_skills == 0


def test_three_unconfirmed_attempts_defer_only_that_target_then_allow_later_retry():
    planner = hunt()
    for index in range(3):
        state = ready()
        now = index*2
        action = planner.plan(state, now)
        assert action['kind'] == 'skill'
        planner.sent(action, now)
        assert planner.plan(state, now+1.6) is None
    assert planner.enabled and 20 in planner.excluded_until
    assert planner.plan(state, 6) is None
    assert planner.plan(state, 14)['kind'] == 'skill'
    assert planner.confirmed_attacks == 0


def test_configured_interval_timeout_attempt_count_and_deferral_control_execution():
    planner = hunt()
    planner.SKILL_INTERVAL, planner.SKILL_RESPONSE_TIMEOUT = .3, 1
    planner.SKILL_ATTEMPTS, planner.TARGET_DEFER = 2, 3
    for now in (0, 1.5):
        action = planner.plan(ready(), now)
        assert action['kind'] == 'skill'
        planner.sent(action, now)
        assert planner.pending['deadline'] == now+1
        assert planner.skill_ready_at == now+.3
        assert planner.plan(ready(), now+1.01) is None
    assert planner.excluded_until[20] == 5.51
    assert planner.plan(ready(), 5) is None
    assert planner.plan(ready(), 6)['kind'] == 'skill'


def test_moving_target_destination_is_used_for_approach_and_range_is_bounded():
    planner = hunt()
    state = ready()
    state['recent_entities'][0].update(position=[12, 10], destination=[20, 10], position_age_seconds=.1)
    action = planner.plan(state, 0)
    assert action['kind'] == 'move' and action['destination'] == [14, 10]
    state['recent_entities'][0].update(position=[15, 10], destination=[16, 10])
    assert planner.plan(state, .1)['kind'] == 'skill'  # both endpoints inside server range 6
    state['recent_entities'][0]['destination'] = [17, 10]
    assert planner.plan(state, .2)['kind'] == 'move'


def test_relay_accepts_chasing_destination_even_when_step_moves_away_from_old_start(tmp_path):
    async def scenario():
        relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
        relay.hunt = PacketHunt()
        relay.hunt.start()
        class Writer:
            def __init__(self): self.packets = []
            def write(self, data): self.packets.append(data)
            async def drain(self): pass
        relay.upstream = Writer()
        observer = relay.tracker.observer
        observer.player_id, observer.player, observer.player_at = 1, [10, 10], time.monotonic()
        observer.registry.update(Entity(20, 1051, 8, 10, time.monotonic(), 'monster', destination=(20, 10)))
        action = relay.hunt.plan(relay.status(), time.monotonic())
        assert action['destination'] == [14, 10]
        await relay.send_hunt_action(action, game_gate=lambda: True)
        assert len(relay.upstream.packets) == 1 and relay.hunt.pending is not None
    asyncio.run(scenario())


@pytest.mark.parametrize('opcode,size,damage_format,level_offset', [
    (0x114, 31, '<H', 26), (0x1de, 33, '<I', 28)])
def test_both_server_skill_damage_formats_confirm_matching_cast(opcode, size, damage_format, level_offset):
    packet = bytearray(size)
    struct.pack_into('<HHII', packet, 0, opcode, 524, 1, 20)
    struct.pack_into(damage_format, packet, 24, 1234)
    struct.pack_into('<H', packet, level_offset, 10)
    event = decode(bytes(packet))
    assert event['skill_id'] == 524 and event['source_id'] == 1 and event['target_id'] == 20
    assert event['level'] == 10 and event['damage_raw'] == 1234
    planner = hunt()
    planner.sent(planner.plan(ready(), 0), 0)
    planner.observe([event], 1, .2)
    assert planner.confirmed_skills == 1 and planner.pending is None


def test_relay_checks_sp_again_and_encodes_correct_target_skill_and_level(tmp_path):
    async def scenario():
        relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
        relay.hunt = hunt()
        class Writer:
            def __init__(self): self.packets = []
            def write(self, data): self.packets.append(data)
            async def drain(self): pass
        relay.upstream = Writer()
        observer = relay.tracker.observer
        observer.player_id, observer.player, observer.player_at = 1, [10, 10], time.monotonic()-3
        observer.registry.update(Entity(20, 1051, 11, 10, time.monotonic(), 'monster'))
        observer.sp, observer.skills = 100, {524: metadata()}
        action = relay.hunt.plan(relay.status(), time.monotonic())
        observer.sp = 10
        with pytest.raises(HuntTargetChanged, match='SP'):
            await relay.send_hunt_action(action, game_gate=lambda: True)
        assert not relay.upstream.packets
        observer.sp = 100
        await relay.send_hunt_action(action, game_gate=lambda: True)
        payload = relay.upstream.packets[0]
        assert len(payload) == 25
        assert struct.unpack_from('<H', payload)[0] == 0x72
        assert struct.unpack_from('<H', payload, 6)[0] == 10
        assert struct.unpack_from('<H', payload, 10)[0] == 524
        assert struct.unpack_from('<I', payload, 21)[0] == 20
        assert relay.hunt.pending['kind'] == 'skill'
    asyncio.run(scenario())
