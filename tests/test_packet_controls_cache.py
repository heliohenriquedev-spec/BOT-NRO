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


def test_native_automatic_walk_is_not_input_and_only_game_clicks_are_remembered(monkeypatch):
    from types import SimpleNamespace
    from nrobot import packet_controls
    clock, key, focused = [10.0], [0], [True]
    controls = packet_controls.GameControls()
    controls.ui = SimpleNamespace(GetAsyncKeyState=lambda code: key[0])
    controls.focused = lambda peer, local: focused[0]
    monkeypatch.setattr(packet_controls.time, 'monotonic', lambda: clock[0])
    assert not controls.movement_input(None, None)  # automatic native packet, no click
    key[0] = 1  # short real click, already released between polls
    assert controls.movement_input(None, None)
    key[0] = 0; clock[0] += .2
    assert controls.movement_input(None, None)  # fragmented packet after the click
    clock[0] += .4
    assert not controls.movement_input(None, None)
    focused[0] = False; key[0] = 0x8001
    assert not controls.movement_input(None, None)  # clicks in another app don't pause the hunt
    focused[0] = True; key[0] = 0
    assert not controls.movement_input(None, None)
