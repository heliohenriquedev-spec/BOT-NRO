import random
import time

from nrobot.map_navigation import CollisionMap
from nrobot.packet_patrol import PacketPatrol
from nrobot.portals import PortalGuard
from nrobot.recall_guard import unexpected_teleport


def test_partial_route_to_the_same_dead_end_twice_puts_the_waypoint_aside():
    collision = CollisionMap(40, 40, [1]*1600)
    patrol = PacketPatrol(8, random.Random(1), spacing=14)
    patrol.plan((5, 5), 0, 150, collision)  # builds the circuit
    block = next(iter(patrol.remaining))
    patrol.goal_block, patrol.goal, patrol.goal_at = block, patrol.tour.points[block], 1
    patrol.tour.stepping_stone = lambda *a, **k: None
    dead_end = (10, 10)

    def route(start, target, blocked=frozenset(), *, partial=False, **kwargs):
        # The full search never finds the way; the partial one always ends in the same dead end.
        return [tuple(start), dead_end] if partial and tuple(start) != dead_end else None
    collision.route = route
    first = patrol.plan((5, 5), 1, 150, collision)
    assert first['destination'] == list(dead_end)
    patrol.plan((12, 12), 2, 150, collision)  # walked back out: heading for the dead end again
    assert block in patrol.deferred and patrol.goal_block != block


def test_bigger_search_is_tried_before_a_partial_route(monkeypatch):
    collision = CollisionMap(40, 40, [1]*1600)
    patrol = PacketPatrol(8, random.Random(1), spacing=14)
    patrol.plan((5, 5), 0, 150, collision)
    calls = []
    real = collision.route

    def route(start, target, blocked=frozenset(), **kwargs):
        calls.append((kwargs.get('max_nodes'), kwargs.get('partial', False)))
        if kwargs.get('max_nodes', 0) <= PacketPatrol.ROUTE_NODES and not kwargs.get('partial'):
            return None
        return real(start, target, blocked, **kwargs)
    collision.route = route
    patrol.goal = None
    action = patrol.plan((20, 20), 1, 150, collision)
    assert action is not None and (PacketPatrol.ROUTE_NODES*5, False) in calls
    assert not any(partial for _, partial in calls)


def portals(tmp_path):
    guard = PortalGuard(tmp_path/'portais.json')
    guard.known = {'tur_dun01': {'50,50': 2}}
    return guard


def test_map_change_far_from_portals_is_a_teleport(tmp_path):
    guard = portals(tmp_path)
    recall = [{'kind': 'map_change', 'map': 'prontera.gat', 'position': [150, 180]}]
    info = unexpected_teleport(recall, 'tur_dun01.gat', (100, 100), guard)
    assert info == {'from_map': 'tur_dun01.gat', 'origin': [100, 100], 'to_map': 'prontera.gat', 'position': [150, 180]}
    assert unexpected_teleport(recall, 'tur_dun01.gat', (51, 52), guard) is None  # walked into a portal
    slip = [{'kind': 'map_change', 'map': 'tur_dun01.gat', 'position': [102, 101]}]
    assert unexpected_teleport(slip, 'tur_dun01.gat', (100, 100), guard) is None
    same_map = [{'kind': 'map_change', 'map': 'tur_dun01.gat', 'position': [20, 20]}]
    assert unexpected_teleport(same_map, 'tur_dun01.gat', (100, 100), guard)  # GM on the same map


def test_relay_stops_everything_when_recalled_while_hunting(tmp_path):
    from nrobot.packet_hunt import PacketHunt
    from nrobot.session_relay import SessionRelay
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    relay.hunt = PacketHunt(); relay.hunt.start()
    relay.portals = portals(tmp_path)
    relay.portals.map_name, relay.portals.last_own = 'tur_dun01.gat', (100, 100)
    relay.tracker.observer.map_name = 'prontera.gat'
    recall = [{'kind': 'map_change', 'map': 'prontera.gat', 'position': [150, 180]}]
    relay.manual_until = 0
    started = time.monotonic()
    assert not relay.check_recall(recall, started)  # allow death/respawn packets to arrive first
    assert not relay.check_recall([], started+1.9)
    assert relay.check_recall([], started+2.1)
    assert not relay.hunt.enabled and relay.commands_blocked and 'recall' in relay.hunt.reason


def test_death_transfer_is_not_misclassified_as_recall(tmp_path):
    from nrobot.packet_hunt import PacketHunt
    from nrobot.session_relay import SessionRelay
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    relay.hunt = PacketHunt(); relay.hunt.start()
    relay.portals = portals(tmp_path)
    relay.portals.map_name, relay.portals.last_own = 'tur_dun01.gat', (100, 100)
    recall = [{'kind': 'map_change', 'map': 'hospital2.gat', 'position': [25, 92]}]
    relay.tracker.observer.player_alive = False
    assert not relay.check_recall(recall, time.monotonic())
    assert relay.hunt.enabled and not relay.commands_blocked


def test_relay_ignores_map_changes_it_expects(tmp_path):
    from nrobot.packet_hunt import PacketHunt
    from nrobot.session_relay import SessionRelay
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    relay.portals = portals(tmp_path)
    relay.portals.map_name, relay.portals.last_own = 'tur_dun01.gat', (100, 100)
    recall = [{'kind': 'map_change', 'map': 'prontera.gat', 'position': [150, 180]}]
    relay.hunt = PacketHunt()
    assert not relay.check_recall(recall, time.monotonic())  # bot idle: the player is playing
    relay.hunt.start()
    relay.manual_active = True
    assert not relay.check_recall(recall, time.monotonic())  # the player is walking by hand
    relay.manual_active = False
    relay.quests.phase = 'travel'
    assert not relay.check_recall(recall, time.monotonic())  # quest route travelling between maps
    assert relay.hunt.enabled and not relay.commands_blocked
