"""REDE-22: o vigia libera apenas o filtro associado ao dono."""
from types import SimpleNamespace

import pytest

from nrobot import capture_guard as module


def test_guard_releases_own_capture_and_filter(monkeypatch, tmp_path):
    calls = []
    def command(args, **kwargs):
        calls.append(args[1:])
        output = b'Filtros de Pacote:\n 1 NRO-Continuo-123 TCP 10.0.0.1 5121\n' if args[1:] == ['filter', 'list'] else b'ok'
        return SimpleNamespace(returncode=0, stdout=output)
    monkeypatch.setattr(module.subprocess, 'run', command)
    monkeypatch.setattr(module, 'active_session_file', lambda: '')
    assert module.cleanup('NRO-Continuo-123', tmp_path) == 'released'
    assert calls == [['filter', 'list'], ['stop'], ['filter', 'remove']]


def test_guard_preserves_mixed_filters(monkeypatch, tmp_path):
    calls = []
    def command(args, **kwargs):
        calls.append(args[1:])
        return SimpleNamespace(returncode=0, stdout=b'1 NRO-Continuo-123 TCP 5121\n2 Outro TCP 443\n')
    monkeypatch.setattr(module.subprocess, 'run', command)
    with pytest.raises(ValueError, match='preservados'):
        module.cleanup('NRO-Continuo-123', tmp_path)
    assert calls == [['filter', 'list']]
