import time
import asyncio
import struct
import socket

import pytest

from nrobot.session_relay import SessionRelay, HandshakeFrames, rewrite_endpoints


def test_login_framing_and_endpoint_rewrite_preserve_session_fields():
    packet = bytearray(79)
    struct.pack_into('<HH', packet, 0, 0x69, 79)
    packet[4:47] = bytes(range(43))
    packet[47:51] = socket.inet_aton('187.77.36.200')
    struct.pack_into('<H', packet, 51, 6121)
    framer = HandshakeFrames('login')
    framer.feed(packet[:3])
    assert framer.pop() is None
    framer.feed(packet[3:])
    assert framer.pop() == (0x69, bytes(packet))
    async def register(stage, host, port):
        assert (stage, host, port) == ('char', '187.77.36.200', 6121)
        return 30001
    result = asyncio.run(rewrite_endpoints(0x69, bytes(packet), register))
    assert result[:47] == packet[:47]
    assert result[47:51] == socket.inet_aton('127.0.0.1')
    assert struct.unpack_from('<H', result, 51)[0] == 30001
    assert result[53:] == packet[53:]


def test_full_local_relay_login_character_map_without_credential_logs(tmp_path):
    async def scenario():
        account = struct.pack('<I', 2003137)
        credential = b'fake-credential-never-log'
        servers = []
        actor = bytearray(55)
        struct.pack_into('<HBI', actor, 0, 0x78, 0, 777)
        struct.pack_into('<H', actor, 15, 1051)
        actor[47:50] = bytes([3, 0, 160])  # (12,10)
        auth = struct.pack('<HI', 0x73, 0) + bytes([2, 128, 160, 0, 0])  # (10,10)

        async def world(reader, writer):
            assert await reader.readexactly(5) == b'world'
            writer.write(account+auth+actor)
            await writer.drain()
            await reader.read()
            writer.close()

        world_server = await asyncio.start_server(world, '127.0.0.1', 0)
        servers.append(world_server)
        world_port = world_server.sockets[0].getsockname()[1]

        async def character(reader, writer):
            assert await reader.readexactly(4) == b'char'
            packet = bytearray(28)
            struct.pack_into('<H', packet, 0, 0x71)
            packet[6:15] = b'field.gat'
            packet[22:26] = socket.inet_aton('127.0.0.1')
            struct.pack_into('<H', packet, 26, world_port)
            writer.write(account+packet)
            await writer.drain()
            await reader.read()
            writer.close()

        char_server = await asyncio.start_server(character, '127.0.0.1', 0)
        servers.append(char_server)
        char_port = char_server.sockets[0].getsockname()[1]

        async def login(reader, writer):
            assert await reader.readexactly(len(credential)) == credential
            packet = bytearray(79)
            struct.pack_into('<HH', packet, 0, 0x69, 79)
            packet[8:12] = account
            packet[47:51] = socket.inet_aton('127.0.0.1')
            struct.pack_into('<H', packet, 51, char_port)
            writer.write(packet)
            await writer.drain()
            await reader.read()
            writer.close()

        login_server = await asyncio.start_server(login, '127.0.0.1', 0)
        servers.append(login_server)
        relay = SessionRelay('127.0.0.1', local_port=0, folder=tmp_path)
        writers = []
        try:
            local_login = await relay.register('login', '127.0.0.1', login_server.sockets[0].getsockname()[1])
            r, w = await asyncio.open_connection('127.0.0.1', local_login)
            writers.append(w)
            w.write(credential)
            await w.drain()
            packet = await r.readexactly(79)
            local_char = struct.unpack_from('<H', packet, 51)[0]
            w.close()
            await w.wait_closed()
            r, w = await asyncio.open_connection('127.0.0.1', local_char)
            writers.append(w)
            w.write(b'char')
            await w.drain()
            packet = await r.readexactly(32)
            local_world = struct.unpack_from('<H', packet, 30)[0]
            w.close()
            await w.wait_closed()
            r, w = await asyncio.open_connection('127.0.0.1', local_world)
            writers.append(w)
            w.write(b'world')
            await w.drain()
            assert await r.readexactly(len(account+auth+actor)) == account+auth+actor
            await asyncio.sleep(.01)
            state = relay.status()
            assert state['candidate']['entity_id'] == 777
            assert state['player_position_recent']
            assert state['map_name'] == 'field.gat'
            with pytest.raises(RuntimeError, match='somente'):
                await relay.send_attack(777, game_gate=lambda: True)
            for path in tmp_path.iterdir():
                assert credential not in path.read_bytes()
        finally:
            for writer in writers:
                writer.close()
            await relay.close()
            for server in servers:
                server.close()
            await asyncio.gather(*(s.wait_closed() for s in servers))
    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


@pytest.mark.parametrize('physical_click', [False, True])
def test_client_walk_is_forwarded_and_yields_only_for_physical_input(tmp_path, physical_click):
    from nrobot.packet_hunt import PacketHunt
    from nrobot.packet_encoder import move
    async def scenario():
        auth=struct.pack('<HI',0x73,0)+bytes([2,128,160,0,0])
        packet=move(11,10,ticks=lambda:42)
        echo=struct.pack('<HI',0x95,777)+b'still-connected'.ljust(24,b'\0')
        async def world(reader,writer):
            writer.write(auth);await writer.drain()
            received=await reader.readexactly(len(packet))
            assert received==packet
            writer.write(echo);await writer.drain()
            await reader.read()
            writer.close()
        server=await asyncio.start_server(world,'127.0.0.1',0)
        relay=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
        relay.hunt=PacketHunt();relay.hunt.start()
        relay.manual_walk_input=lambda: physical_click
        writer=None
        try:
            port=await relay.register('map','127.0.0.1',server.sockets[0].getsockname()[1])
            reader,writer=await asyncio.open_connection('127.0.0.1',port)
            assert await reader.readexactly(len(auth))==auth
            await asyncio.sleep(.01)
            original_reason = relay.hunt.reason
            writer.write(packet[:3]);await writer.drain()
            await asyncio.sleep(.01)
            writer.write(packet[3:]);await writer.drain()
            assert await asyncio.wait_for(reader.readexactly(len(echo)),1)==echo
            # REDE-76: the bot yields to the player and resumes by itself afterwards.
            now=time.monotonic()
            assert not relay.commands_blocked and relay.hunt.enabled
            assert relay.manual_control(now) is physical_click
            if physical_click:
                assert 'controle manual' in relay.hunt.reason
            assert not relay.manual_control(now+relay.MANUAL_YIELD+.1)
            assert relay.hunt.reason == ('' if physical_click else original_reason)
            assert not writer.is_closing() and relay.upstream is not None
            assert relay.native_frames.ready
        finally:
            if writer is not None:writer.close();await writer.wait_closed()
            await relay.close();server.close();await server.wait_closed()
    asyncio.run(scenario())


def test_automatic_client_walk_after_attack_preserves_the_active_fight(tmp_path):
    from nrobot.packet_hunt import PacketHunt
    from nrobot.packet_encoder import move
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    relay.hunt = PacketHunt(); relay.hunt.start()
    relay.hunt.target = 110000001
    pending = relay.hunt.pending = dict(kind='attack', target_id=110000001)
    relay.manual_walk_input = lambda: False
    relay.inspect_native_frames(move(11, 10, ticks=lambda: 42))
    assert not relay.manual_active and relay.hunt.target == 110000001 and relay.hunt.pending is pending
    relay.manual_walk_input = lambda: True
    relay.inspect_native_frames(move(12, 10, ticks=lambda: 43))
    assert relay.manual_active and relay.hunt.target is None and relay.hunt.pending is None
