import struct

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from nrobot import auto_login
from nrobot.login_screens import ASSETS, ScreenMatcher, LoginFlow, Match, pixels


@pytest.fixture(scope='module')
def matcher():
    return ScreenMatcher()


@pytest.mark.parametrize('name,kind', [('win_login', 'login'), ('win_service', 'service'),
                                     ('win_select', 'characters'), ('win_msgbox', 'message')])
@pytest.mark.parametrize('scale', [.75, 1., 1.5])
def test_recognizes_shipped_skin_at_different_positions_and_scales(matcher, name, kind, scale):
    source = QImage(str(ASSETS/(name+'.png')))
    source = source.scaled(round(source.width()*scale), round(source.height()*scale), Qt.IgnoreAspectRatio, Qt.FastTransformation)
    patch = pixels(source)
    frame = np.full((720, 1100, 3), [27, 49, 61], dtype=np.uint8)
    x, y = 133, 177
    frame[y:y+patch.shape[0], x:x+patch.shape[1]] = patch
    found = matcher.dialog(frame)
    assert found is not None and found.kind == kind
    assert (found.x, found.y, found.scale) == (x, y, scale)


def test_unknown_screen_produces_no_match(matcher):
    assert matcher.dialog(np.zeros((600, 800, 3), dtype=np.uint8)) is None


def stable(flow, match, state, config):
    flow.plan(match, state, config, 0, 1)
    return flow.plan(match, state, config, .5, 1)


def test_protocol_context_distinguishes_connection_and_world_and_prevents_message_clicks():
    config = dict(auto_login.DEFAULTS, enabled=True, user='saved', password='protected')
    service = Match('service', 100, 100, 1, 0)
    flow = LoginFlow()
    action = stable(flow, service, {'stage': 'waiting_login', 'login_phase': 'waiting'}, config)
    assert action['kind'] == 'connection' and action['row'] == 1
    flow.sent(action, .5)
    login = stable(flow, Match('login', 200, 100, 1, 0), {'stage': 'waiting_login', 'login_phase': 'waiting'}, config)
    assert login['kind'] == 'authenticate'
    world = stable(LoginFlow(), service, {'stage': 'login', 'login_phase': 'world',
                   'login_world_count': 1, 'login_world_selected': True}, dict(config, server_index=3))
    assert world['kind'] == 'world' and world['row'] == 0
    assert stable(LoginFlow(), Match('message', 1, 2, 1, 0), {'stage': 'map', 'login_phase': 'map'}, config) is None
    assert stable(LoginFlow(), Match('characters', 1, 2, 1, 0), {'stage': 'char', 'login_phase': 'characters'}, config) is None


def test_pause_failure_and_unconfirmed_local_connection_never_type():
    config = dict(auto_login.DEFAULTS, enabled=True, user='saved', password='protected')
    match = Match('login', 1, 2, 1, 0)
    assert stable(LoginFlow(), match, {'stage': 'login'}, dict(config, paused=True)) is None
    with pytest.raises(ValueError, match='BOT LOCAL'):
        stable(LoginFlow(), match, {'stage': 'waiting_login'}, config)
    with pytest.raises(ValueError, match='recusou'):
        LoginFlow().plan(match, {'login_phase': 'failed'}, config, 0, 1)


def test_known_disconnect_is_confirmed_only_once():
    config = dict(auto_login.DEFAULTS, enabled=True)
    match = Match('message', 1, 2, 1, 0)
    state = {'stage': 'map_disconnected', 'login_phase': 'disconnected'}
    flow = LoginFlow()
    action = stable(flow, match, state, config)
    assert action['kind'] == 'confirm_disconnect'
    flow.sent(action, .5)
    assert flow.plan(match, state, config, 1, 1) is None


def test_world_selection_preserves_tokens_and_native_order():
    packet = bytearray(47+64)
    struct.pack_into('<HH', packet, 0, 0x69, len(packet))
    packet[4:47] = bytes(range(43))
    packet[47:79] = bytes([1])*32
    packet[79:] = bytes([2])*32
    selected, changed = auto_login.select_world(bytes(packet), dict(auto_login.DEFAULTS, enabled=True, server_index=2))
    assert changed and selected[4:47] == packet[4:47]
    assert selected[47:] == bytes([2])*32 and len(selected) == 79
    assert auto_login.select_world(bytes(packet), dict(auto_login.DEFAULTS, enabled=True, paused=True)) == (bytes(packet), False)


def test_bootstrap_never_forwards_unknown_or_unprotected_dummy_credentials():
    config = dict(auto_login.DEFAULTS, enabled=True, user='real', password='protected', _bootstrap=True)
    native = struct.pack('<HI', 0x64, 123)+auto_login.BOOTSTRAP_USER.encode().ljust(24, b'\0')*2+b'\x01'
    adapter = auto_login.LoginPacketAdapter(config, {0x64: 55}, decrypt=lambda _: 'secret')
    result = adapter.feed(native)
    assert auto_login.BOOTSTRAP_USER.encode() not in result
    assert result[6:30] == b'real'.ljust(24, b'\0')
    for options, packet in ((dict(paused=True), native), ({}, b'\x77\x02'+bytes(82)), (dict(password=''), native)):
        guard = auto_login.LoginPacketAdapter(dict(config, **options), {0x64: 55}, decrypt=lambda _: 'secret')
        with pytest.raises(ValueError):
            guard.feed(packet)


def test_client_hash_before_fragmented_login_does_not_disable_adapter():
    from test_login_packets import request
    config = dict(auto_login.DEFAULTS, enabled=True, user='real', password='protected')
    guard = auto_login.LoginPacketAdapter(config, {0x64: 55, 0x204: 18}, decrypt=lambda _: 'secret')
    metadata = b'\x04\x02'+bytes(16)
    assert guard.feed(metadata+request()[:6]) == metadata
    result = guard.feed(request()[6:])
    assert result[6:30] == b'real'.ljust(24, b'\0')


def test_pausing_bootstrap_allows_real_manual_credentials_without_rewriting():
    from test_login_packets import request
    config = dict(auto_login.DEFAULTS, enabled=True, paused=True, _bootstrap=True)
    guard = auto_login.LoginPacketAdapter(config, {0x64: 55})
    packet = request()
    assert guard.feed(packet[:20]) == b''
    assert guard.feed(packet[20:]) == packet
