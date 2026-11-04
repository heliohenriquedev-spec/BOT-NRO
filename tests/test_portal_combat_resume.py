import asyncio
import socket
import struct

from nrobot.map_navigation import CollisionMap
from nrobot.packet_hunt import PacketHunt
from nrobot.session_relay import MapEndpointStream, SessionRelay


def test_portal_keeps_run_state_but_discards_old_target_and_waits_for_position():
    hunt = PacketHunt()
    hunt.start(); hunt.target = 123; hunt.pending = {'kind': 'attack'}
    hunt.map_transition()
    assert hunt.enabled and hunt.target is None and hunt.pending is None
    assert hunt.plan(dict(state='waiting', player_position_recent=False, player_position=None), 1) is None
    assert hunt.enabled
    action = hunt.plan(dict(state='tracking', player_position_recent=True, player_position=[5, 5],
                            recent_entities=[dict(entity_id=456, position=[6, 5])]), 2)
    assert action == dict(kind='attack', target_id=456)
    hunt.pause('manual')
    hunt.map_transition()
    assert not hunt.enabled


def test_transfer_gap_does_not_pause_and_manual_pause_is_not_overridden(tmp_path):
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.hunt = PacketHunt(); relay.hunt.start()
    relay.begin_hunt_transfer(now=10)
    assert relay.waiting_hunt_transfer(False, now=11) and relay.hunt.enabled
    relay.hunt.pause('manual')
    observer = relay.tracker.observer
    observer.player_id = 1; observer.player = [5, 5]; observer.player_at = 12
    assert not relay.waiting_hunt_transfer(True, now=12)
    assert not relay.hunt.enabled


def test_unconfirmed_transfer_stops_after_timeout_instead_of_sending_old_actions(tmp_path):
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.hunt = PacketHunt(); relay.hunt.start()
    relay.begin_hunt_transfer(now=10)
    assert relay.waiting_hunt_transfer(False, now=31)
    assert not relay.hunt.enabled


def test_fragmented_map_server_portal_keeps_client_connected_through_relay():
    packet = bytearray(28)
    struct.pack_into('<H', packet, 0, 0x92)
    packet[2:18] = b'next.gat'.ljust(16, b'\0')
    struct.pack_into('<HH', packet, 18, 10, 20)
    packet[22:26] = socket.inet_aton('192.0.2.1')
    struct.pack_into('<H', packet, 26, 5121)
    async def scenario():
        calls, transfers = [], []
        async def register(stage, host, port):
            calls.append((stage, host, port)); return 30001
        account = struct.pack('<I', 2003137)
        stream = MapEndpointStream(account, register, lambda: transfers.append(True))
        assert await stream.feed(account[:2]) == b''
        prefix = await stream.feed(account[2:]+packet[:12])
        assert prefix == account
        rewritten = await stream.feed(packet[12:])
        assert rewritten[:22] == packet[:22]
        assert rewritten[22:26] == socket.inet_aton('127.0.0.1')
        assert struct.unpack_from('<H', rewritten, 26)[0] == 30001
        assert calls == [('map', '192.0.2.1', 5121)] and transfers == [True]
    asyncio.run(scenario())


def test_monster_close_behind_wall_is_approached_instead_of_kited():
    width = height = 20
    cells = [int(x != 9 or y >= 8) for y in range(height) for x in range(width)]  # short way around
    collision = CollisionMap(width, height, cells)
    hunt = PacketHunt(); hunt.auto_attacks = False; hunt.start()
    state = dict(state='tracking', player_position_recent=True, player_position=[7, 5], engagement_range=6,
                 recent_entities=[dict(entity_id=20, position=[11, 5])])
    action = hunt.plan(state, 0, 100, collision)
    assert action['kind'] == 'move' and action.get('purpose') != 'keep_distance'
    assert action['destination'][1] > 5  # the opening is below, not behind the player
    assert collision.segment([7, 5], action['destination'], max_steps=4)


def test_approach_reuses_walkable_path_but_recalculates_after_new_obstacle():
    class CountingMap(CollisionMap):
        calls = 0
        def route(self, *args, **kwargs):
            self.calls += 1
            return super().route(*args, **kwargs)
    collision = CountingMap(30, 30, [1]*900)
    hunt = PacketHunt(); hunt.target = 20
    path = hunt.approach_path(collision, [3, 3], [20, 20], set(), 0)
    assert hunt.approach_path(collision, path[3], [20, 20], set(), 1) == path[3:]
    assert collision.calls == 1
    hunt.approach_path(collision, path[3], [20, 20], {tuple(path[4])}, 2)
    assert collision.calls == 2


def test_map_to_map_connection_handoff_preserves_hunt_and_receives_new_position(tmp_path):
    async def scenario():
        account = struct.pack('<I', 2003137)
        auth = struct.pack('<HI', 0x73, 0)+bytes([2, 128, 160, 0, 0])
        relay = SessionRelay('127.0.0.1', folder=tmp_path)
        relay.account = account; relay.next_map = 'start.gat'
        relay.hunt = PacketHunt(); relay.hunt.start()
        clients = []
        async def destination(reader, writer):
            try:
                writer.write(account+auth); await writer.drain()
                await reader.read()
            finally:
                writer.close()
                await writer.wait_closed()
        target = await asyncio.start_server(destination, '127.0.0.1', 0)
        target_port = target.sockets[0].getsockname()[1]
        packet = struct.pack('<H', 0x92)+b'next.gat'.ljust(16, b'\0')+struct.pack('<HH', 10, 10)
        packet += socket.inet_aton('127.0.0.1')+struct.pack('<H', target_port)
        async def origin(reader, writer):
            try:
                writer.write(account+auth+packet); await writer.drain()
                await reader.read()
            finally:
                writer.close()
                await writer.wait_closed()
        source = await asyncio.start_server(origin, '127.0.0.1', 0)
        try:
            port = await relay.register('map', '127.0.0.1', source.sockets[0].getsockname()[1])
            reader, writer = await asyncio.open_connection('127.0.0.1', port); clients.append(writer)
            data = await asyncio.wait_for(reader.readexactly(4+len(auth)+len(packet)), 2)
            forwarded_port = struct.unpack_from('<H', data, len(data)-2)[0]
            assert forwarded_port != target_port
            writer.close(); await writer.wait_closed()
            await asyncio.sleep(.02)
            assert relay.hunt.enabled
            reader2, writer2 = await asyncio.open_connection('127.0.0.1', forwarded_port); clients.append(writer2)
            await asyncio.wait_for(reader2.readexactly(4+len(auth)), 2)
            await asyncio.sleep(.02)
            assert relay.hunt.enabled and relay.tracker.observer.map_name == 'next.gat'
            assert not relay.waiting_hunt_transfer(True)
            assert relay.tracker.observer.player is not None
        finally:
            for writer in clients:
                writer.close(); await writer.wait_closed()
            await relay.close()
            source.close(); target.close()
            await source.wait_closed(); await target.wait_closed()
    asyncio.run(scenario())


def test_monster_close_behind_a_long_wall_is_neither_kited_nor_chased():
    width = height = 20
    cells = [int(x != 9 or y >= 15) for y in range(height) for x in range(width)]
    collision = CollisionMap(width, height, cells)
    hunt = PacketHunt(); hunt.auto_attacks = False; hunt.start()
    state = dict(state='tracking', player_position_recent=True, player_position=[7, 5], engagement_range=6,
                 recent_entities=[dict(entity_id=20, position=[11, 5])])
    assert hunt.plan(state, 0, 100, collision) is None and hunt.target is None
