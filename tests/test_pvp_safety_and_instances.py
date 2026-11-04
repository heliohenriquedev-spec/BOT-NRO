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
    for _ in range(relay.PLAYER_MISSES-1):
        relay.note_player_attack(2002329, now)
    assert relay.player_target_allowed(2002329)
    relay.player_misses[2002329] = 0  # damage confirmed meanwhile: counting starts over
    for _ in range(relay.PLAYER_MISSES):
        relay.note_player_attack(2002329, now)
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
