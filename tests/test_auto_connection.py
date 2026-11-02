"""Servidor lido do jogo e porta local trocada sozinha quando outro programa a usa."""
import asyncio
import hashlib
import json
import socket

from nrobot import relay_profile
from nrobot import session_relay
from nrobot.session_relay import SessionRelay, port_busy

ORIGINAL = (b'<clientinfo><connection><display>NRO</display><address>jogo.exemplo.com</address>'
            b'<port>6901</port></connection></clientinfo>')


def install(tmp_path, monkeypatch):
    game = tmp_path/'game'/'data'
    game.mkdir(parents=True)
    backup = tmp_path/'backup.xml'
    backup.write_bytes(ORIGINAL)
    installed = relay_profile.make_profile(ORIGINAL, 16900)
    (game/'clientinfo.xml').write_bytes(installed)
    manifest = tmp_path/'instalacao.json'
    manifest.write_text(json.dumps({'restored': False, 'local_port': 16900, 'files': [
        {'target': str(game/'clientinfo.xml'), 'backup': str(backup), 'original_existed': True,
         'installed_hash': hashlib.sha256(installed).hexdigest()}]}))
    monkeypatch.setattr(relay_profile, 'MANIFEST', manifest)
    return game/'clientinfo.xml'


def test_the_error_reported_by_windows_is_recognised():
    assert port_busy(OSError(10048, 'error while attempting to bind'))  # asyncio's own OSError
    assert not port_busy(OSError(10061, 'refused'))


def test_server_and_local_port_come_from_the_game_files(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    assert relay_profile.original_server() == ('jogo.exemplo.com', 6901)
    assert relay_profile.installed_port() == 16900


def test_local_port_can_move_and_the_game_entry_follows(tmp_path, monkeypatch):
    target = install(tmp_path, monkeypatch)
    relay_profile.change_local_port(16905)
    entries = relay_profile.connections(target.read_bytes())
    assert entries[-1][1:] == ('127.0.0.1', '16905') and entries[0][1] == 'jogo.exemplo.com'
    assert relay_profile.installed_port() == 16905


def test_port_taken_by_another_program_moves_the_bot_to_a_free_one(tmp_path, monkeypatch):
    moved = []
    monkeypatch.setattr(relay_profile, 'change_local_port', moved.append)
    blocker = socket.socket()
    blocker.bind(('127.0.0.1', 0))
    blocker.listen()
    taken = blocker.getsockname()[1]
    import nrobot.port_guard as port_guard
    monkeypatch.setattr(port_guard, 'listening_pids', lambda port: {__import__('os').getpid()})

    async def scenario():
        relay = SessionRelay('127.0.0.1', 6900, taken, folder=tmp_path)
        try:
            local = await relay.register('login', '127.0.0.1', 6900)
            assert local != taken and moved == [local] and relay.local_port == local
        finally:
            await relay.close()
    try:
        asyncio.run(scenario())
    finally:
        blocker.close()
