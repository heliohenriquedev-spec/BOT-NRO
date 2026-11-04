"""REDE-31: collision geometry, map identity and route validation."""
import asyncio
import struct
import time

import pytest

from nrobot.map_navigation import CollisionMap, MapRepository
from nrobot.packet_hunt import PacketHunt
from nrobot.network_observer import Observer
from nrobot.network_targets import Entity
from nrobot.session_relay import SessionRelay


def grid(rows):
    return CollisionMap(len(rows[0]), len(rows), [c != '#' for row in rows for c in row])


def test_wall_detour_can_start_away_from_target_without_cutting_corners():
    collision = grid(['........', '..#.....', '..#.....', '..#.....', '........', '........'])
    path = collision.route([1, 2], [4, 2])
    assert path and path[1] in ((1, 1), (1, 3), (0, 1), (0, 3))
    assert all(collision.edge(a, b) for a, b in zip(path, path[1:]))
    assert (2, 2) not in path
    assert collision.route([1, 2], [4, 2], max_nodes=1) is None


def test_isolated_target_corner_and_out_of_bounds_are_not_routable():
    collision = grid(['.#...', '#....', '.....', '.....'])
    assert not collision.edge((0, 0), (1, 1))
    assert collision.route((0, 0), (2, 2)) is None
    assert not collision.walkable((-1, 0))
    assert not collision.walkable((4, 0))  # server reserves last row/column
    assert collision.segment((1, 1), (3, 2))  # REDE-51: free arbitrary slope


def test_gat_layout_unknown_types_and_truncated_input():
    data = b'GRAT\x01\x02'+struct.pack('<II', 3, 3)
    data += b''.join(struct.pack('<4fI', 0, 0, 0, 0, t) for t in (0, 1, 2, 3, 4, 5, 6, 7, 0))
    collision = CollisionMap.from_gat(data)
    assert collision.cells == bytes([1, 0, 1, 1, 1, 0, 1, 0, 1])
    with pytest.raises(ValueError):
        CollisionMap.from_gat(data[:-1])
    with pytest.raises(ValueError):
        CollisionMap.from_gat(b'GRAT\x02\x00'+data[6:])


def test_map_repository_preserves_resource_priority_and_caches_read_failures(tmp_path, monkeypatch):
    calls = []
    class FakeGrfs:
        def __init__(self, root): pass
        def read(self, name):
            calls.append(name)
            raise ValueError('unreadable highest priority resource')
    monkeypatch.setattr('nrobot.map_navigation.GrfSet', FakeGrfs)
    repository = MapRepository(tmp_path)
    assert repository.get('field.gat') is None
    assert repository.get('field.gat') is None
    assert calls == ['data\\field.gat']
    assert 'highest priority' in repository.errors['field.gat']
    assert repository.get('..\\field.gat') is None
    assert len(calls) == 1


def test_map_repository_reads_loose_gat_and_accepts_rsw_map_name(tmp_path, monkeypatch):
    class NoGrfs:
        def __init__(self, root): pass
        def read(self, name): raise AssertionError('loose file must take precedence')
    monkeypatch.setattr('nrobot.map_navigation.GrfSet', NoGrfs)
    (tmp_path/'data').mkdir()
    (tmp_path/'data/field.gat').write_bytes(b'GRAT\x01\x02'+struct.pack('<II', 3, 3)
                                         +struct.pack('<4fI', 0, 0, 0, 0, 0)*9)
    repository = MapRepository(tmp_path)
    assert repository.get('field.rsw').walkable((1, 1))


def test_map_resource_alias_resolves_nested_file_without_guessing(tmp_path, monkeypatch):
    gat = b'GRAT\x01\x02'+struct.pack('<II', 3, 3)+struct.pack('<4fI', 0, 0, 0, 0, 0)*9
    resources = {'data\\resnametable.txt': b'pvp_n_1-1.gat#custom\\arena.gat#\r\n',
                 'data\\custom\\arena.gat': gat}
    class Grfs:
        def __init__(self, root): pass
        def read(self, name): return resources[name]
    monkeypatch.setattr('nrobot.map_navigation.GrfSet', Grfs)
    repository = MapRepository(tmp_path)
    assert repository.get('pvp_n_1-1.gat').walkable((1, 1))
    assert repository.sources['pvp_n_1-1.gat'] == 'data\\custom\\arena.gat'
    resources['data\\resnametable.txt'] = b'bad.gat#..\\outside.gat#'
    repository = MapRepository(tmp_path)
    assert repository.get('bad.gat') is None
    assert 'inválido' in repository.errors['bad.gat']


def test_missing_map_reports_unreadable_alias_table(tmp_path, monkeypatch):
    class Grfs:
        def __init__(self, root): pass
        def read(self, name):
            if name.endswith('resnametable.txt'):
                raise ValueError('table unreadable')
            raise KeyError(name)
    monkeypatch.setattr('nrobot.map_navigation.GrfSet', Grfs)
    repository = MapRepository(tmp_path)
    assert repository.get('absent.gat') is None
    assert 'table unreadable' in repository.errors['absent.gat']


def test_hunt_routes_around_wall_and_replans_after_target_moves():
    collision = grid(['........', '..#.....', '..#.....', '..#.....', '........', '........'])
    hunt = PacketHunt()
    hunt.start()
    state = {'state': 'tracking', 'player_position_recent': True, 'player_position': [1, 2],
             'recent_entities': [{'entity_id': 20, 'position': [4, 2]}]}
    action = hunt.plan(state, 0, 100, collision)
    assert action['collision_route'] and collision.segment([1, 2], action['destination'])
    hunt.sent(action, 0)
    hunt.observe([{'kind': 'position', 'entity_id': 1, 'position': action['destination']}], 1, .01)
    state['player_position'] = action['destination']
    state['recent_entities'][0]['position'] = [5, 3]
    action = hunt.plan(state, 1, 100, collision)
    assert action['target_id'] == 20
    assert collision.segment(state['player_position'], action['destination'])


def test_map_identity_survives_position_init_and_clears_on_transfer():
    observer = Observer({1051})
    observer.map_name = 'field.gat'
    observer.apply({'kind': 'player_position_init', 'position': [1, 1]}, 0)
    assert observer.map_name == 'field.gat'
    observer.apply({'kind': 'map_change', 'map': 'other.gat', 'position': [2, 2]}, 1)
    assert observer.map_name == 'other.gat'
    observer.apply({'kind': 'map_transfer'}, 2)
    assert observer.map_name is None


def test_relay_rechecks_collision_and_accepts_detour_away_from_monster(tmp_path):
    async def scenario():
        relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
        collision = grid(['........', '..#.....', '..#.....', '..#.....', '........', '........'])
        relay.collision_map = lambda: collision
        class Writer:
            packets = []
            def write(self, data): self.packets.append(data)
            async def drain(self): pass
        relay.upstream = Writer()
        relay.hunt = PacketHunt()
        relay.hunt.start()
        observer = relay.tracker.observer
        observer.player_id, observer.player, observer.player_at = 1, [1, 2], time.monotonic()
        observer.registry.update(Entity(20, 1051, 4, 2, time.monotonic(), 'monster'))
        action = relay.hunt.plan(relay.status(), time.monotonic(), 100, collision)
        await relay.send_hunt_action(action, game_gate=lambda: True)
        assert len(relay.upstream.packets) == 1
        relay.hunt.pending = None
        bad = {**action, 'destination': [3, 2]}
        with pytest.raises(ValueError, match='obstáculo'):
            await relay.send_hunt_action(bad, game_gate=lambda: True)
        assert len(relay.upstream.packets) == 1
    asyncio.run(scenario())


def test_moving_target_adjacent_destination_with_distant_observed_position():
    """REDE-46: one-point route is valid, but has no next movement step."""
    collision = grid(['..........'] * 10)
    hunt = PacketHunt()
    hunt.start()
    state = {'state': 'tracking', 'player_position_recent': True, 'player_position': [2, 2],
             'recent_entities': [{'entity_id': 20, 'position': [7, 2], 'destination': [3, 2]}]}
    assert collision.route([2, 2], [3, 2]) == [(2, 2)]
    assert hunt.plan(state, 0, 100, collision) is None
    assert hunt.enabled and hunt.target == 20 and 20 not in hunt.excluded_until
    state['recent_entities'].append({'entity_id': 21, 'position': [2, 2]})
    action = hunt.plan(state, 1, 100, collision)
    assert action is None and hunt.target == 20
    state['recent_entities'] = state['recent_entities'][1:]
    action = hunt.plan(state, 2, 100, collision)
    assert action['kind'] == 'attack' and action['target_id'] == 21


def test_empty_route_is_unavailable_without_crashing():
    class EmptyRoute:
        def route(self, *args, **kwargs): return []
        def line_clear(self, *args): return False
    hunt = PacketHunt()
    hunt.start()
    state = {'state': 'tracking', 'player_position_recent': True, 'player_position': [2, 2],
             'recent_entities': [{'entity_id': 20, 'position': [7, 2]}]}
    assert hunt.plan(state, 0, 100, EmptyRoute()) is None
    assert hunt.enabled and hunt.target is None


def test_ranged_cooldown_wait_does_not_walk_into_melee_or_past_target():
    collision = grid(['...............'] * 8)
    hunt = PacketHunt()
    hunt.auto_attacks = False  # REDE-84: skills only, the bot keeps its distance
    hunt.melee_approach, hunt.kite = False, True  # skills only, keeping their distance
    hunt.start()
    snapshot = {'state': 'tracking', 'player_position_recent': True, 'player_position': [1, 2],
                'engagement_range': 6, 'recent_entities': [{'entity_id': 20, 'position': [9, 2]}]}
    action = hunt.plan(snapshot, 0, 100, collision)
    assert action['kind'] == 'move' and action['destination'] == [4, 2]
    snapshot['player_position'] = [4, 2]
    assert hunt.plan(snapshot, 1, 100, collision) is None
    snapshot['recent_entities'][0]['position'] = [10, 2]
    assert hunt.plan(snapshot, 2, 100, collision)['destination'] == [5, 2]


def test_pulled_slope_segment_does_not_cut_diagonal_corner():
    collision = grid(['.......', '..#....', '.......', '.......', '.......'])
    assert not collision.segment([1, 1], [4, 2])
    assert collision.segment([1, 3], [4, 2])
    assert not collision.segment([1, 3], [6, 2])  # over four cells


def test_open_diagonal_approach_uses_full_segment_instead_of_one_cell_turn():
    collision = grid(['................']*16)
    hunt = PacketHunt()
    hunt.start()
    snapshot = {'state': 'tracking', 'player_position_recent': True, 'player_position': [2, 2],
                'engagement_range': 6, 'recent_entities': [{'entity_id': 20, 'position': [13, 8]}]}
    action = hunt.plan(snapshot, 0, 100, collision)
    assert action['kind'] == 'move'
    assert max(abs(action['destination'][i]-2) for i in (0, 1)) == 4
    assert collision.segment([2, 2], action['destination'])


def test_approach_leads_moving_target_without_firing_at_its_future_position():
    collision=grid(['................................']*32)
    hunt=PacketHunt();hunt.start()
    state={'state':'tracking','player_position_recent':True,'player_position':[2,10],
           'engagement_range':6,'recent_entities':[{'entity_id':20,'position':[15,10],
           'effective_position':[15,10],'destination':[15,20],'walk_speed_ms':200,
           'attack_positions':[[15,10],[15,11]],'position_usable':True}]}
    action=hunt.plan(state,0,112,collision)
    assert action['kind']=='move' and action['destination'][1]>10
    assert collision.segment(state['player_position'],action['destination'])


def test_path_prefers_wall_clearance_and_shortcuts_cannot_cut_back_to_wall():
    collision=grid(['############','............','............','............','............','............','............'])
    assert collision.clearance([3,1])==1
    assert collision.clearance([3,3])>=2
    path=collision.route([2,1],[9,1],exact=True)
    assert any(point[1]>=2 for point in path[1:-1])
    assert not collision.segment([2,1],[6,1],wall_margin=2)
    assert collision.segment([2,3],[6,3],wall_margin=2)


def _cells(width, height):
    # Wall column at x=3, everything else walkable ground (type 0); wall = type 1.
    return bytes(1 if x == 3 else 0 for y in range(height) for x in range(width))


def test_rathena_map_cache_is_used_before_encrypted_client_grf(tmp_path):
    import struct, zlib
    from nrobot.map_navigation import MapRepository, read_map_caches
    entries = b''
    for name, (w, h) in (('hospital2', (8, 6)), ('areia', (5, 5))):
        packed = zlib.compress(_cells(w, h))
        entries += name.encode().ljust(12, b'\0')+struct.pack('<hhi', w, h, len(packed))+packed
    data = struct.pack('<IHH', 8+len(entries), 2, 0)+entries
    (tmp_path/'map_cache.dat').write_bytes(data)
    assert set(read_map_caches(tmp_path)) == {'hospital2', 'areia'}
    repository = MapRepository.__new__(MapRepository)
    repository.cache, repository.errors, repository.sources = {}, {}, {}
    repository.server_maps = read_map_caches(tmp_path)
    collision = repository.get('hospital2.gat')
    assert (collision.width, collision.height) == (8, 6)
    assert collision.walkable((2, 2)) and not collision.walkable((3, 2))
    assert repository.sources['hospital2.gat'] == 'map cache do servidor'


def test_hercules_mcache_files_are_read(tmp_path):
    import struct, zlib
    from nrobot.map_navigation import read_map_caches
    packed = zlib.compress(_cells(6, 4))
    (tmp_path/'cmd_fild09.mcache').write_bytes(struct.pack('<h16shhi', 1, bytes(16), 6, 4, len(packed))+packed)
    assert read_map_caches(tmp_path)['cmd_fild09'][:2] == (6, 4)


def test_corrupt_or_unrelated_cache_files_are_ignored(tmp_path):
    from nrobot.map_navigation import read_map_caches
    (tmp_path/'outro.dat').write_bytes(b'\x01\x02\x03\x04\x05\x00\x00\x00garbage')
    assert read_map_caches(tmp_path) == {}
