import asyncio
import json
import socket
import struct
import time

from nrobot import auto_login
from nrobot.session_relay import SessionRelay


def test_native_login_replaces_dummy_credentials_and_selects_world_on_local_transport(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_login, 'unprotect', lambda _: 'test-secret')
    auto_login.save(dict(auto_login.DEFAULTS, enabled=True, user='real-account', password='DPAPI', server_index=2))
    async def scenario():
        received = []
        async def server(reader, writer):
            try:
                request = await reader.readexactly(55)
                received.append(request)
                packet = bytearray(111)
                struct.pack_into('<HH', packet, 0, 0x69, 111)
                packet[8:12] = struct.pack('<I', 2003137)
                for offset, label in ((47, b'First'), (79, b'Second')):
                    packet[offset:offset+4] = socket.inet_aton('127.0.0.1')
                    struct.pack_into('<H', packet, offset+4, 5121)
                    packet[offset+6:offset+6+len(label)] = label
                writer.write(packet); await writer.drain()
                await reader.read()
            finally:
                writer.close(); await writer.wait_closed()
        remote = await asyncio.start_server(server, '127.0.0.1', 0)
        folder = tmp_path/'session'; folder.mkdir()
        (folder/'login_bootstrap.json').write_text(json.dumps(dict(until=time.monotonic()+60)))
        relay = SessionRelay('127.0.0.1', folder=folder)
        writer = None
        try:
            port = await relay.register('login', '127.0.0.1', remote.sockets[0].getsockname()[1])
            reader, writer = await asyncio.open_connection('127.0.0.1', port)
            request = struct.pack('<HI', 0x64, 123)+auto_login.BOOTSTRAP_USER.encode().ljust(24, b'\0')*2+b'\x01'
            writer.write(request[:7]); await writer.drain()
            await asyncio.sleep(.01)
            writer.write(request[7:]); await writer.drain()
            response = await asyncio.wait_for(reader.readexactly(79), 2)
            assert received[0][6:30].split(b'\0')[0] == b'real-account'
            assert received[0][30:54].split(b'\0')[0] == b'test-secret'
            assert auto_login.BOOTSTRAP_USER.encode() not in received[0]
            assert response[53:73].split(b'\0')[0] == b'Second'
            assert relay.login_phase == 'world' and relay.login_world_selected
            assert relay.login_world_count == 1
        finally:
            if writer:
                writer.close(); await writer.wait_closed()
            await relay.close()
            remote.close(); await remote.wait_closed()
        for path in folder.glob('*.json*'):
            assert b'test-secret' not in path.read_bytes()
    asyncio.run(scenario())
