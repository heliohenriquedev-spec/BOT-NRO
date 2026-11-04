"""REDE-67/68: captured character target and user-defined skill priority."""
import asyncio
import struct
import time

from nrobot.combat_rotation import CombatRotation
from nrobot.packet_encoder import attack, skill
from nrobot.packet_hunt import PacketHunt
from nrobot.packet_settings import DEFAULTS, validate
from nrobot.session_relay import SessionRelay


def _state(skills, entities=((20, [12, 10]),), sp=500):
    return {'state': 'tracking', 'player_position_recent': True, 'player_position': [10, 10],
            'player_id': 1, 'player_sp': sp, 'own_effects': {},
            'learned_skills': [{'skill_id': i, 'level': 10, 'sp_cost': 10, 'range': 9, 'target_flags': 1} for i in skills],
            'recent_entities': [{'entity_id': i, 'position': p} for i, p in entities]}


def _profiles(*ids):
    return [{'skill_id': i, 'enabled': True, 'role': 'offensive', 'level': 10, 'interval': 5, 'effect_id': 0} for i in ids]


def test_user_priority_picks_first_usable_skill_in_order():
    rotation = CombatRotation(_profiles(1001, 1002, 1003), priority=[1003, 1001, 1002])
    action = rotation.plan(_state((1001, 1002, 1003)), 0, 20)
    assert action['skill_id'] == 1003
    rotation.sent(action, 0)
    rotation.observe([{'kind': 'skill_damage', 'skill_id': 1003, 'source_id': 1, 'target_id': 20, 'level': 10, 'damage_raw': 1}], 1, .1)
    action = rotation.plan(_state((1001, 1002, 1003)), 1, 20)
    assert action['skill_id'] == 1001  # 1003 on its interval: next in the user's order
    rotation.sent(action, 1)
    rotation.observe([{'kind': 'skill_damage', 'skill_id': 1001, 'source_id': 1, 'target_id': 20, 'level': 10, 'damage_raw': 1}], 1, 1.1)
    action = rotation.plan(_state((1001, 1002, 1003)), 2, 20)
    assert action['skill_id'] == 1002
    rotation.sent(action, 2)
    rotation.observe([{'kind': 'skill_damage', 'skill_id': 1002, 'source_id': 1, 'target_id': 20, 'level': 10, 'damage_raw': 1}], 1, 2.1)
    assert rotation.plan(_state((1001, 1002, 1003)), 6, 20)['skill_id'] == 1003  # REDE-83: the cycle starts again


def test_priority_cycle_lets_later_skills_go_when_the_first_is_ready_again_at_once():
    rotation = CombatRotation(_profiles(1001, 1002, 1003), priority=[1001, 1002, 1003], fast=True)
    used, now = [], 0.0
    for _ in range(6):
        action = rotation.plan(_state((1001, 1002, 1003)), now, 20)
        rotation.sent(action, now)
        rotation.observe([{'kind': 'skill_damage', 'skill_id': action['skill_id'], 'source_id': 1, 'target_id': 20,
                           'level': 10, 'damage_raw': 1}], 1, now+.01)
        used.append(action['skill_id'])
        now += 1
    assert used == [1001, 1002, 1003, 1001, 1002, 1003]


def test_priority_skips_skill_without_sp_and_throws_share_one_slot():
    rotation = CombatRotation(_profiles(1001, 523, 524), priority=['throws', 1001])
    assert rotation.order == {523: 0, 524: 0, 1001: 1}
    state = _state((1001,), sp=500)
    state['learned_skills'][0]['sp_cost'] = 900
    assert rotation.plan(state, 0, 20) is None and 'SP' in rotation.reason


def test_priority_setting_is_validated():
    assert validate({**DEFAULTS, 'species': [1037], 'skill_priority': [1001, 'throws']})['skill_priority'] == [1001, 'throws']
    for bad in ([1001, 1001], ['x'], [0], 'throws'):
        try:
            validate({**DEFAULTS, 'species': [1037], 'skill_priority': bad})
        except ValueError:
            continue
        raise AssertionError(bad)


def _relay(tmp_path):
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    relay.hunt = PacketHunt();relay.hunt.start()
    observer = relay.tracker.observer
    observer.player_id = 1;observer.player = [10, 10];observer.player_at = time.monotonic()
    appearance = {'kind': 'appearance', 'entity_id': 2003137, 'species_id': 26, 'position': [13, 10],
                  'object_type': 0, 'walk_speed_ms': 150}
    relay.presence.observe([appearance], 1, time.monotonic())
    relay.inventory.observe([appearance, {'kind': 'name', 'entity_id': 2003137, 'name': 'Radiance'}], time.monotonic())
    return relay


def test_click_on_character_with_armed_tool_captures_it(tmp_path):
    relay = _relay(tmp_path)
    relay.inspect_native_frames(attack(2003137, ticks=lambda: 42))
    assert relay.captured_player is None  # tool not armed: an ordinary click captures nothing
    relay.capture_armed_until = time.monotonic()+20
    relay.inspect_native_frames(skill(2003137, 5, 1, ticks=lambda: 42))
    assert relay.captured_player == {'entity_id': 2003137, 'name': 'Radiance', 'origin': 'clique no jogo'}
    assert relay.capture_armed_until == 0 and relay.hunt.priority_target == 2003137
    entity = relay.tracker.observer.registry.entities[2003137]
    assert entity.kind == 'player' and [entity.x, entity.y] == [13, 10]
    assert relay.presence.reason([10, 10], time.monotonic()) is None  # the target itself never holds the bot
    assert [e['entity_id'] for e in relay.status()['recent_entities']] == [2003137]
    relay.release_player()
    assert 2003137 not in relay.tracker.observer.registry.entities and relay.presence.reason([10, 10], time.monotonic())


def test_clicking_a_monster_or_self_does_not_capture(tmp_path):
    relay = _relay(tmp_path)
    relay.capture_armed_until = time.monotonic()+20
    relay.inspect_native_frames(attack(110830885, ticks=lambda: 42))
    relay.inspect_native_frames(attack(1, ticks=lambda: 42))
    assert relay.captured_player is None and relay.capture_armed_until > 0


def test_hunt_attacks_captured_character_before_closer_monster(tmp_path):
    relay = _relay(tmp_path)
    assert relay.capture_player(2003137, 'painel')
    state = {'state': 'tracking', 'player_position_recent': True, 'player_position': [10, 10],
             'recent_entities': [{'entity_id': 20, 'position': [11, 10]}, {'entity_id': 2003137, 'position': [12, 10]}]}
    relay.hunt.plan(state, 0, 100)
    assert relay.hunt.target == 2003137 and relay.hunt.engaged == 2003137

    async def send():
        class Writer:
            def __init__(self): self.packets = []
            def write(self, data): self.packets.append(data)
            async def drain(self): pass
        relay.upstream = Writer()
        relay.tracker.observer.species = {1037}
        relay.hunt.pending, relay.hunt.ready_at = None, 0
        relay.tracker.observer.registry.update(
            relay.tracker.observer.registry.entities[2003137].__class__(2003137, 26, 11, 10, time.monotonic(), 'player'))
        await relay.send_hunt_action({'kind': 'attack', 'target_id': 2003137}, game_gate=lambda: True)
        return relay.upstream.packets
    packets = asyncio.run(send())
    assert len(packets) == 1 and struct.unpack_from('<I', packets[0], 5)[0] == 2003137


def test_pvp_targets_are_opt_in_and_cleared_on_map_change(tmp_path):
    from nrobot.packet_settings import DEFAULTS

    relay = _relay(tmp_path)
    relay.apply_settings({**DEFAULTS, 'pvp_enabled': True, 'pvp_targets': [2003137],
                          'pvp_first': True})
    now = time.monotonic()
    players = [{'kind': 'appearance', 'entity_id': identity, 'species_id': 26,
                'position': [13, 10], 'object_type': 0}
               for identity in (2003137, 2003138)]
    relay.presence.observe(players, 1, now)
    relay.track_players(players)
    relay.sync_pvp_targets()
    assert relay.player_target_allowed(2003137)
    assert not relay.player_target_allowed(2003138)
    assert len(relay.players_nearby()) == 2
    state = {'player_position': [10, 10], 'recent_entities': [
        {'entity_id': 2003137, 'position': [13, 10]},
        {'entity_id': 110830885, 'position': [11, 10]},
    ]}
    assert relay.prioritize_pvp(state)['recent_entities'] == state['recent_entities'][:1]

    relay.begin_map_observation()
    relay.track_players([{'kind': 'move', 'entity_id': 2003137, 'position': [12, 10]}])
    assert not relay.players_nearby()
    assert not relay.player_target_allowed(2003137)

    relay.presence.observe(players, 1, now)
    relay.track_players(players)
    relay.apply_settings({**DEFAULTS, 'pvp_enabled': True, 'pvp_all': True})
    assert relay.player_target_allowed(2003138)
    relay.apply_settings(DEFAULTS)
    assert not relay.player_target_allowed(2003138)
    assert 2003138 not in relay.tracker.observer.registry.entities


def test_players_checked_in_the_pvp_list_reach_the_automatic_battle(tmp_path):
    """Before, only a captured player was a combat candidate: the PvP list chose nobody."""
    from nrobot.packet_settings import DEFAULTS
    relay = _relay(tmp_path)
    relay.apply_settings({**DEFAULTS, 'pvp_enabled': True, 'pvp_targets': [2003137], 'species': [], 'pvp_first': True})
    now = time.monotonic()
    players = [{'kind': 'appearance', 'entity_id': identity, 'species_id': 26, 'position': [13, 10], 'object_type': 0}
               for identity in (2003137, 2003138)]
    relay.presence.observe(players, 1, now)
    relay.track_players(players)
    relay.sync_pvp_targets()
    state = relay.status()
    assert [(e['entity_id'], e['kind']) for e in state['recent_entities']] == [(2003137, 'player')]
    relay.hunt.start()
    action = relay.hunt.plan(state, now, 100)
    assert action['target_id'] == 2003137
    relay.apply_settings({**DEFAULTS, 'pvp_enabled': True, 'pvp_targets': [], 'species': []})
    assert not relay.status()['recent_entities']  # unchecked: no longer a target


def test_priority_is_dropped_when_the_player_leaves_the_screen(tmp_path):
    relay = _relay(tmp_path)
    assert relay.capture_player(2003137, 'painel')
    now = time.monotonic()
    assert not relay.expire_captured(now)  # on screen: kept
    relay.presence.players.discard(2003137)
    assert not relay.expire_captured(now+1)  # just left: a moment of grace
    assert not relay.expire_captured(now+2)
    assert relay.expire_captured(now+4.5)
    assert relay.captured_player is None and relay.hunt.priority_target is None
    assert 2003137 not in relay.tracker.observer.pinned


def test_priority_survives_a_short_blink_and_is_dropped_in_hide(tmp_path):
    relay = _relay(tmp_path)
    assert relay.capture_player(2003137, 'painel')
    now = time.monotonic()
    relay.presence.players.discard(2003137)
    relay.expire_captured(now)
    relay.presence.players.add(2003137)
    assert not relay.expire_captured(now+2) and not relay.expire_captured(now+5)  # back in view: kept
    relay.presence.hidden[2003137] = {'option': 0x40, 'seen_at': now, 'position': [13, 10]}
    relay.expire_captured(now+6)
    assert relay.expire_captured(now+9.5) and relay.captured_player is None


def test_pvp_table_checks_targets_and_one_priority():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from nrobot.pvp_panel import PvpTargets, TARGET, PRIORITY
    panel = PvpTargets()
    asked, cleared, changed = [], [], []
    panel.priority_requested.connect(asked.append)
    panel.priority_cleared.connect(lambda: cleared.append(True))
    panel.targets_changed.connect(lambda: changed.append(True))
    state = {'players_nearby': [{'entity_id': 2003137, 'name': 'Radiance', 'distance': 3.0},
                                {'entity_id': 2003138, 'name': None, 'distance': 5.0}]}
    panel.update_state(state)
    assert panel.table.rowCount() == 2
    panel.table.item(1, TARGET).setCheckState(Qt.Checked)
    assert panel.targets == {2003138} and changed
    panel.table.item(0, PRIORITY).setCheckState(Qt.Checked)
    assert asked == [2003137]
    panel.update_state({**state, 'captured_player': {'entity_id': 2003137, 'name': 'Radiance', 'origin': 'painel'}})
    assert panel.table.item(0, PRIORITY).checkState() == Qt.Checked and 'Radiance' in panel.status.text()
    panel.table.item(0, PRIORITY).setCheckState(Qt.Unchecked)
    assert cleared
