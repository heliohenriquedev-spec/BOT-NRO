"""PvP never hits friends or keeps hitting a player who takes no damage; instance maps get collision."""
import time

from nrobot.map_navigation import CollisionMap
from nrobot.packet_settings import DEFAULTS


def relay_with_players(tmp_path, players, **settings):
    from nrobot.packet_hunt import PacketHunt
    from nrobot.session_relay import SessionRelay
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    relay.hunt = PacketHunt()
    relay.apply_settings({**DEFAULTS, 'species': [], 'pvp_enabled': True, **settings})
    observer = relay.tracker.observer
    observer.player_id, observer.player, observer.player_at = 1, [10, 10], time.monotonic()
    events = [{'kind': 'appearance', 'entity_id': identity, 'species_id': 26, 'position': [12, 10], 'object_type': 0}
              for identity, _ in players]
    events += [{'kind': 'name', 'entity_id': identity, 'name': name} for identity, name in players if name]
    relay.inventory.observe(events, time.monotonic())
    relay.presence.observe(events, 1, time.monotonic())
    relay.track_players(events)
    relay.player_names.update({identity: name for identity, name in players if name})
    relay.sync_pvp_targets()
    return relay


def test_attack_everyone_leaves_out_friends_and_players_not_yet_named(tmp_path):
    relay = relay_with_players(tmp_path, [(2003155, 'Pipokinha'), (2002329, 'Inimigo'), (2002610, None)],
                               pvp_all=True, allowed_players=['Pipokinha'])
    assert relay.pvp_registered == {2002329}
    assert not relay.player_target_allowed(2003155) and not relay.player_target_allowed(2002610)


def test_explicitly_checked_players_stay_targets(tmp_path):
    relay = relay_with_players(tmp_path, [(2003155, 'Pipokinha')], pvp_targets=[2003155], allowed_players=['Pipokinha'])
    assert relay.pvp_registered == {2003155}


def test_player_who_takes_no_damage_is_left_alone_for_a_minute(tmp_path):
    relay = relay_with_players(tmp_path, [(2002329, 'Inimigo')], pvp_all=True)
    now = time.monotonic()
    for step in range(20):  # a fast burst: many sends before any damage can come back
        relay.note_player_attack(2002329, now+step*.07)
    assert relay.player_target_allowed(2002329)  # sends alone never drop a player being fought
    relay.player_misses.pop(2002329)  # damage confirmed meanwhile: counting starts over
    for step in range(relay.PLAYER_MISSES+2):
        relay.note_player_attack(2002329, now+step)  # 7 s of attacks with no damage at all
    assert not relay.player_target_allowed(2002329) and 2002329 not in relay.pvp_registered
    assert relay.hunt.excluded_until[2002329] >= now+59


def test_instance_copy_uses_the_floor_where_everyone_stands(tmp_path):
    from nrobot.session_relay import SessionRelay
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    floor_a = CollisionMap(100, 100, [int(x > 50) for y in range(100) for x in range(100)])
    floor_b = CollisionMap(100, 100, [1]*10000)
    maps = {'1@tower.gat': floor_a, '5@tower.gat': floor_b}

    class Repository:
        sources, errors = {}, {}
        def get(self, name):
            return maps.get(name.lower())
    relay.map_repository = Repository()
    relay.tracker.observer.map_name = '0045@tower.gat'
    relay.tracker.observer.player = [20, 20]  # walkable only on floor b
    assert relay.collision_map() is floor_b
    assert relay.instance_maps['0045@tower.gat'] == '5@tower.gat'


def test_dead_state_and_resurrection_are_read():
    import struct
    from nrobot.packet_reader import decode
    standing = bytearray(58); struct.pack_into('<H', standing, 0, 0x22a); struct.pack_into('<I', standing, 2, 2002329)
    standing[55] = 1
    assert decode(bytes(standing))['dead'] is True
    standing[55] = 2  # sitting
    assert decode(bytes(standing))['dead'] is False
    assert decode(struct.pack('<HIH', 0x148, 2002329, 0)) == {'opcode': '0148', 'kind': 'resurrection', 'entity_id': 2002329}


def test_dead_players_get_no_skill_or_attack_until_resurrected(tmp_path):
    import asyncio
    import pytest
    from nrobot.session_relay import HuntTargetChanged
    relay = relay_with_players(tmp_path, [(2002329, 'Inimigo')], pvp_targets=[2002329])
    assert [e['entity_id'] for e in relay.status()['recent_entities']] == [2002329]
    relay.inventory.observe([{'kind': 'remove', 'entity_id': 2002329, 'reason': 1}], time.monotonic())  # killed
    relay.inventory.observe([{'kind': 'appearance', 'entity_id': 2002329, 'species_id': 26, 'position': [12, 10],
                              'object_type': 0, 'dead': True}], time.monotonic())  # body seen again
    relay.sync_pvp_targets()
    assert relay.dead(2002329) and relay.status()['recent_entities'] == []
    relay.hunt.start()

    class Writer:
        def __init__(self): self.packets = []
        def write(self, data): self.packets.append(data)
        async def drain(self): pass
    relay.upstream = Writer()
    with pytest.raises(HuntTargetChanged):  # refused (gone from the targets, or dead)
        asyncio.run(relay.send_hunt_action({'kind': 'attack', 'target_id': 2002329}, game_gate=lambda: True))
    assert relay.upstream.packets == []
    relay.inventory.observe([{'kind': 'resurrection', 'entity_id': 2002329}], time.monotonic())
    relay.sync_pvp_targets()
    assert not relay.dead(2002329) and [e['entity_id'] for e in relay.status()['recent_entities']] == [2002329]


def test_prioritize_players_keeps_hunting_when_no_player_is_reachable(tmp_path):
    import math
    from nrobot.network_targets import ACCOUNT_IDS
    relay = relay_with_players(tmp_path, [(2002329, 'Inimigo')], pvp_all=True, pvp_first=True)
    o = relay.tracker.observer
    o.player, o.player_at = [10, 10], time.monotonic()
    monster = {'entity_id': 111700300, 'species_id': 1002, 'kind': 'monster', 'position': [12, 10]}
    far_player = {'entity_id': 2002329, 'species_id': 0, 'kind': 'player', 'position': [90, 90]}  # out of range
    state = {'player_position': [10, 10], 'recent_entities': [monster, far_player]}
    relay.collision_map = lambda: None
    kept = relay.prioritize_pvp(state)
    assert any(e['entity_id'] == 111700300 for e in kept['recent_entities'])  # monster still huntable
    near_player = {'entity_id': 2002329, 'species_id': 0, 'kind': 'player', 'position': [13, 10]}
    state = {'player_position': [10, 10], 'recent_entities': [monster, near_player]}
    kept = relay.prioritize_pvp(state)
    assert [e['entity_id'] for e in kept['recent_entities']] == [2002329]  # player in reach: players only
