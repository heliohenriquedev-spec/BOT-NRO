import asyncio
import struct

import pytest

from nrobot import auto_login


def request():
    return struct.pack('<HI', 0x64, 12345)+b'placeholder'.ljust(24, b'\0')+b'placeholder'.ljust(24, b'\0')+b'\x02'


def adapter(**values):
    config = dict(auto_login.DEFAULTS, enabled=True, user='saved', password='DPAPI')
    config.update(values)
    return auto_login.LoginPacketAdapter(config, {0x64: 55}, decrypt=lambda _: 'secret')


@pytest.mark.parametrize('cut', [1, 2, 6, 30, 54])
def test_fragmented_native_login_is_rewritten_once_without_losing_extra_bytes(cut):
    packet = request()
    login = adapter()
    assert login.feed(packet[:cut]) == b''
    rewritten = login.feed(packet[cut:]+b'extra')
    assert rewritten[:6] == packet[:6] and rewritten[54:] == packet[54:]+b'extra'
    assert rewritten[6:30] == b'saved'.ljust(24, b'\0')
    assert rewritten[30:54] == b'secret'.ljust(24, b'\0')
    assert login.feed(b'next') == b'next'
    assert not login.buffer
    assert 'secret' not in login.reason and 'saved' not in login.reason


def test_unknown_auth_and_disabled_auto_login_are_never_rewritten():
    native = struct.pack('<H', 0x277)+bytes(82)
    assert adapter().feed(native) == native
    packet = request()
    assert adapter(enabled=False).feed(packet) == packet
    assert adapter(packet_login=False).feed(packet) == packet
    login = adapter(); login.sizes = {}
    assert login.feed(packet) == packet


def test_bad_saved_credentials_do_not_get_truncated_or_leak_to_diagnostics():
    packet = request()
    login = adapter(user='x'*24)
    assert login.feed(packet) == packet
    assert 'x'*24 not in login.reason


def test_login_controller_does_not_send_blind_keyboard_input():
    reports = []
    assert not auto_login.log_in(auto_login.DEFAULTS, reports.append)
    assert 'nenhuma tecla' in reports[-1]


def test_character_choice_is_cancelled_when_session_already_entered_map(tmp_path, monkeypatch):
    from nrobot.session_relay import SessionRelay
    from test_auto_login_and_routes import char_list
    class Writer:
        sent = []
        def is_closing(self): return False
        def write(self, data): self.sent.append(data)
        async def drain(self): pass
    async def scenario():
        monkeypatch.setattr(auto_login, 'load', lambda: dict(auto_login.DEFAULTS, enabled=True, character='Ninja'))
        relay = SessionRelay('127.0.0.1', folder=tmp_path)
        relay.stage = 'char'
        writer = Writer()
        relay.schedule_character_choice(char_list((123, 'Ninja', 1)), writer)
        relay.stage = 'map'
        await relay.character_choice_task
        assert not writer.sent
    asyncio.run(scenario())
