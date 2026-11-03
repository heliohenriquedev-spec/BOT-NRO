"""REDE-37: panel readers must not stop relay telemetry/control."""
import asyncio
import json
import os

import pytest

from nrobot.packet_hunt import PacketHunt
from nrobot.session_relay import SessionRelay


@pytest.mark.skipif(os.name != 'nt', reason='Windows file sharing semantics')
@pytest.mark.parametrize('filename', ['estado.json', 'entidades_mapa.json'])
def test_open_panel_reader_defers_telemetry_without_stopping_hunt(tmp_path, filename):
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.hunt = PacketHunt(patrol=True)
    relay.hunt.start()
    relay.status()
    with (tmp_path/filename).open('r', encoding='utf-8') as reader:
        relay.last_status_written = 0
        relay.stage = 'map'
        relay.inventory.map_name = 'test.gat'
        state = relay.status()
        assert relay.hunt.enabled and state['stage'] == 'map'
        assert reader.read()
    relay.last_status_written = 0
    relay.status()
    assert json.loads((tmp_path/'estado.json').read_text(encoding='utf-8'))['stage'] == 'map'
    assert json.loads((tmp_path/'entidades_mapa.json').read_text(encoding='utf-8'))['map'] == 'test.gat'


def test_shutdown_closes_live_bridge_before_waiting_for_listener(tmp_path):
    async def scenario():
        accepted = asyncio.Event()
        remote_writers = []
        async def remote(reader, writer):
            remote_writers.append(writer)
            accepted.set()
            await reader.read()
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(remote, '127.0.0.1', 0)
        relay = SessionRelay('127.0.0.1', folder=tmp_path)
        client_writer = None
        try:
            port = await relay.register('map', '127.0.0.1', server.sockets[0].getsockname()[1])
            reader, client_writer = await asyncio.open_connection('127.0.0.1', port)
            await asyncio.wait_for(accepted.wait(), 1)
            await asyncio.wait_for(relay.close(), 2)
            assert relay.stage == 'stopped' and relay.upstream is None
            assert await asyncio.wait_for(reader.read(), 1) == b''
        finally:
            if client_writer is not None:
                client_writer.close()
                await client_writer.wait_closed()
            for writer in remote_writers:
                writer.close()
            server.close()
            await server.wait_closed()
    asyncio.run(scenario())

def test_historical_inventory_is_not_rewritten_for_every_fast_status_tick(tmp_path,monkeypatch):
    import nrobot.session_relay as module
    clock=[100.0]
    monkeypatch.setattr(module.time,'monotonic',lambda:clock[0])
    relay=SessionRelay('127.0.0.1',folder=tmp_path)
    monkeypatch.setattr(relay,'write_minimap',lambda:None)
    monkeypatch.setattr(relay,'write_monsters',lambda:None)
    calls=[]
    original=relay.inventory.snapshot
    def snapshot(now):calls.append(now);return original(now)
    monkeypatch.setattr(relay.inventory,'snapshot',snapshot)
    relay.status()
    clock[0]=100.2;relay.status()
    assert calls==[100.0]
    clock[0]=101.1;relay.status()
    assert calls==[100.0,101.1]
    relay.inventory.map_name='new.gat'
    clock[0]=101.3;relay.status()
    assert calls[-1]==101.3  # new maps are still written immediately
