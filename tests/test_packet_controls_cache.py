import sys
import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows API')


def test_connection_owner_is_looked_up_once_per_second(monkeypatch):
    from nrobot import packet_controls
    calls = []
    monkeypatch.setattr(packet_controls, 'connection_pid', lambda peer, local: calls.append(1) or 4242)
    controls = packet_controls.GameControls()
    monkeypatch.setattr(controls, 'panic', lambda: False)
    monkeypatch.setattr(controls, 'is_game', lambda pid: calls.append('exe') or True)
    for _ in range(50):
        assert controls.connected(('1.2.3.4', 5), ('127.0.0.1', 6))
    assert calls == [1, 'exe']
