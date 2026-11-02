"""Porta do bot ocupada por um relay antigo."""
from nrobot import port_guard

NETSTAT = """
Conexões ativas

  Proto  Endereço local         Endereço externo       Estado          PID
  TCP    0.0.0.0:135            0.0.0.0:0              ESCUTANDO       1200
  TCP    127.0.0.1:16900        0.0.0.0:0              ESCUTANDO       4321
  TCP    127.0.0.1:16900        127.0.0.1:50321        ESTABELECIDA    4321
  TCP    127.0.0.1:169001       0.0.0.0:0              ESCUTANDO       77
"""


def test_listening_process_is_found_on_a_portuguese_windows():
    assert port_guard.listening_pids(16900, NETSTAT) == {4321}
    assert port_guard.listening_pids(5000, NETSTAT) == set()


def test_only_bot_relays_are_ended(monkeypatch):
    monkeypatch.setattr(port_guard.os, 'name', 'nt')
    monkeypatch.setattr(port_guard, 'listening_pids', lambda port: {10, 20})
    lines = {10: 'python.exe -u -m nrobot.session_relay --hunt', 20: 'C:\Programas\outro.exe'}
    monkeypatch.setattr(port_guard, 'command_line', lambda pid: lines[pid])
    killed = []
    monkeypatch.setattr(port_guard, 'run', lambda command: killed.append(command) or '')
    freed, message = port_guard.free(16900)
    assert not freed and 'outro.exe' in message
    assert killed == [['taskkill', '/PID', '10', '/T', '/F']]
