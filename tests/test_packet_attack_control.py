import asyncio
import struct
import time

import pytest

from nrobot.network_observer import Observer
from nrobot.network_targets import Entity
from nrobot.session_relay import SessionRelay


class Writer:
    def __init__(self):
        self.packets = []
    def write(self, packet):
        self.packets.append(packet)
    async def drain(self):
        pass


def prepared(tmp_path):
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    writer = Writer()
    relay.upstream = writer
    observer = relay.tracker.observer
    now = time.monotonic()
    observer.apply({'kind': 'own_identity', 'entity_id': 1}, now)
    observer.apply({'kind': 'player_position_init', 'position': [10, 10]}, now)
    observer.registry.update(Entity(777, 1051, 11, 10, now, 'monster'))
    return relay, writer


def test_attack_sends_one_packet_and_matches_server_source_and_target(tmp_path):
    async def scenario():
        relay, writer = prepared(tmp_path)
        await relay.send_attack(777, game_gate=lambda: True)
        assert len(writer.packets) == 1 and len(writer.packets[0]) == 19
        assert struct.unpack_from('<I', writer.packets[0], 5)[0] == 777
        packet = bytearray(29)
        struct.pack_into('<HII', packet, 0, 0x8a, 1, 777)
        struct.pack_into('<H', packet, 22, 42)
        relay.mirror_map(bytes(packet))
        assert relay.last_test['status'] == 'confirmed_response'
        assert relay.last_test['damage_raw'] == 42
        with pytest.raises(RuntimeError, match='já realizado'):
            await relay.send_attack(777, game_gate=lambda: True)
        assert len(writer.packets) == 1
    asyncio.run(scenario())


def test_focus_panic_and_expired_target_prevent_sending(tmp_path):
    async def scenario():
        relay, writer = prepared(tmp_path)
        with pytest.raises(ValueError, match='foco'):
            await relay.send_attack(777, game_gate=lambda: False)
        relay.commands_blocked = True
        with pytest.raises(RuntimeError, match='envios parados'):
            await relay.send_attack(777, game_gate=lambda: True)
        relay.commands_blocked = False
        relay.tracker.observer.registry.entities[777] = Entity(777, 1051, 11, 10, time.monotonic()-6, 'monster')
        with pytest.raises(ValueError):
            await relay.send_attack(777, game_gate=lambda: True)
        assert not writer.packets
    asyncio.run(scenario())


def test_unrelated_damage_does_not_confirm_packet_test(tmp_path):
    async def scenario():
        relay, writer = prepared(tmp_path)
        await relay.send_attack(777, game_gate=lambda: True)
        packet = struct.pack('<HII', 0x8a, 99, 777) + bytes(19)
        relay.mirror_map(packet)
        assert relay.last_test['status'] == 'sent_waiting_response'
    asyncio.run(scenario())


def test_reliable_player_position_is_retained_but_death_invalidates_it():
    reliable = Observer({1051}, player_ttl=None)
    passive = Observer({1051})
    for observer in (reliable, passive):
        observer.apply({'kind': 'player_position_init', 'position': [10, 10]}, 0)
        observer.registry.update(Entity(777, 1051, 11, 10, 10, 'monster'))
    assert reliable.choose(10).entity_id == 777
    assert passive.choose(10) is None
    reliable.apply({'kind': 'player_stat', 'stat_type': 5, 'value': 0}, 10)
    assert reliable.choose(10) is None


def test_home_is_global_toggle_and_background_gate_does_not_require_focus():
    from nrobot.packet_controls import GameControls
    controls = GameControls.__new__(GameControls)
    controls.down = lambda key: key == 0x24
    assert controls.hunt_pressed()
    calls = []
    controls._check_connection = lambda peer, local, require_focus: calls.append(require_focus) or not require_focus
    assert controls.connected(('127.0.0.1', 1), ('127.0.0.1', 2))
    assert not controls.focused(('127.0.0.1', 1), ('127.0.0.1', 2))
    assert calls == [False, True]


def test_quiet_relay_does_not_permanently_invalidate_connection(tmp_path):
    relay, writer = prepared(tmp_path)
    relay.tracker.last_received = time.monotonic()-10
    assert relay.status()['state'] == 'tracking'
    assert not relay.tracker.failed
    assert relay.status()['recent_entities']  # fresh monster is still valid
