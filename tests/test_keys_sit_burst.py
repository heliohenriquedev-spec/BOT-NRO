"""REDE-82: teclas configuráveis, sentar com jogador por perto, regras de falha e rajada."""
import asyncio
import struct
import time

import pytest

from nrobot.combat_rotation import CombatRotation
from nrobot.packet_encoder import SIT, STAND, body_action
from nrobot.packet_settings import DEFAULTS, HOTKEYS, validate


class Writer:
    def __init__(self):
        self.packets = []

    def write(self, data):
        self.packets.append(bytes(data))

    async def drain(self):
        pass


def test_sit_and_stand_are_the_action_request_without_a_target():
    sit = body_action(SIT, ticks=lambda: 42)
    assert len(sit) == 19 and struct.unpack_from('<H', sit)[0] == 0x190
    assert struct.unpack_from('<I', sit, 5)[0] == 0 and sit[-1] == 2
    assert body_action(STAND, ticks=lambda: 42)[-1] == 3
    with pytest.raises(ValueError):
        body_action(7)


def test_bot_sits_while_a_player_is_near_and_stands_before_resuming(tmp_path, monkeypatch):
    from nrobot.packet_hunt import PacketHunt
    from nrobot.session_relay import SessionRelay
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    relay.hunt = PacketHunt()
    relay.hunt.start()
    relay.upstream = Writer()
    relay.sit_on_players = True
    monkeypatch.setattr(type(relay.native_frames), 'ready', property(lambda self: True))
    observer = relay.tracker.observer
    observer.player_id, observer.player, observer.player_at = 1, [10, 10], time.monotonic()
    reasons = iter(['jogador 2003137 no campo de visao', 'jogador 2003137 no campo de visao', None])
    monkeypatch.setattr(relay.presence, 'reason', lambda position, now: next(reasons))

    async def scenario():
        assert await relay.update_presence_hold()
        assert await relay.update_presence_hold()  # sits only once
        assert not await relay.update_presence_hold()
    asyncio.run(scenario())
    actions = [packet[-1] for packet in relay.upstream.packets if struct.unpack_from('<H', packet)[0] == 0x190]
    assert actions == [SIT, STAND] and not relay.sitting


def test_hotkeys_are_validated():
    assert validate({**DEFAULTS, 'hotkey_hunt': 'F9', 'hotkey_minimap': 'Num 5'})['hotkey_hunt'] == 'F9'
    for wrong in ({'hotkey_hunt': 'F12'}, {'hotkey_hunt': 'End', 'hotkey_minimap': 'End'}, {'hotkey_minimap': 'A'}):
        with pytest.raises(ValueError):
            validate({**DEFAULTS, **wrong})
    with pytest.raises(ValueError):
        validate({**DEFAULTS, 'resume_delay': 5})  # at least 10 s
    assert HOTKEYS['Home'] == 0x24 and HOTKEYS['F1'] == 0x70


def profile(identity):
    return {'skill_id': identity, 'enabled': True, 'role': 'offensive', 'level': 10, 'interval': 5, 'effect_id': 0}


def state(distance=2):
    return {'state': 'tracking', 'player_position_recent': True, 'player_position': [10, 10], 'player_id': 1,
            'player_sp': 999, 'own_effects': {}, 'own_cast_until': 0,
            'learned_skills': [{'skill_id': i, 'level': 10, 'sp_cost': 10, 'range': r, 'target_flags': 1}
                               for i, r in ((1001, 9), (1002, 9), (1003, 3))],
            'recent_entities': [{'entity_id': 20, 'position': [10+distance, 10], 'position_age_seconds': .1}]}


def test_burst_sends_every_offensive_in_range_every_50_ms_without_waiting_answers():
    rotation = CombatRotation([profile(1001), profile(1002), profile(1003)], burst=True, burst_interval=.05)
    sent, now = [], 0.0
    while now < .6:
        action = rotation.plan(state(distance=6), now, 20)  # 1003 reaches 3 cells only
        if action is not None:
            rotation.sent(action, now)
            sent.append((round(now, 2), action['skill_id']))
        now = round(now+.01, 2)
    assert {skill for _, skill in sent} == {1001, 1002}
    gaps = [b[0]-a[0] for a, b in zip(sent, sent[1:])]
    assert min(gaps) >= .05-1e-9 and max(gaps) <= .06
    assert len(sent) >= 10 and not rotation.failures  # unanswered burst packets are not failures


def test_server_cooldown_still_holds_a_skill_in_burst():
    rotation = CombatRotation([profile(1001), profile(1002)], burst=True)
    rotation.observe([{'kind': 'skill_cooldown', 'skill_id': 1001, 'duration_ms': 3000}], 1, 0)
    skills = set()
    for step in range(10):
        action = rotation.plan(state(), step*.05, 20)
        rotation.sent(action, step*.05)
        skills.add(action['skill_id'])
    assert skills == {1002}


def test_failure_rules_can_be_switched_off(tmp_path):
    from nrobot.packet_hunt import PacketHunt
    from nrobot.session_relay import SessionRelay
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    relay.hunt = PacketHunt()
    relay.apply_settings({**DEFAULTS, 'species': [1037], 'limit_target_failures': False, 'defer_failed_targets': False})
    assert relay.hunt.SKILL_ATTEMPTS > 1000 and relay.hunt.TARGET_DEFER == 0
    assert relay.rotation.attempts > 1000 and relay.rotation.defer == .3
    relay.apply_settings({**DEFAULTS, 'species': [1037]})
    assert relay.hunt.SKILL_ATTEMPTS == DEFAULTS['skill_attempts'] and relay.rotation.defer == DEFAULTS['target_defer']


def test_resuming_retries_stand_if_native_stream_is_incomplete(tmp_path):
    from nrobot.packet_hunt import PacketHunt
    from nrobot.session_relay import SessionRelay
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    relay.hunt = PacketHunt()
    relay.hunt.start()
    relay.presence_hold = 'player near'
    relay.sitting = True
    assert asyncio.run(relay.update_presence_hold())
    assert relay.sitting and relay.presence_hold
    relay.upstream = Writer()
    assert not asyncio.run(relay.update_presence_hold())
    assert not relay.sitting and relay.presence_hold is None


def test_allowed_names_settings_roundtrip():
    assert validate({'allowed_players': [' Amigo ', 'Amigo']})['allowed_players'] == ['Amigo']
    with pytest.raises(ValueError):
        validate({'allowed_players': 'Amigo'})
