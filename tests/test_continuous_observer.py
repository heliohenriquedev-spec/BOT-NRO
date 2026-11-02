"""REDE-10/11: o seletor conserva IDs e descarta dados incompletos."""
import struct

import pytest

from nrobot.continuous_observer import ContinuousTracker, ipv4_from_ethernet, legacy_filter_captures, PktmonSession
from nrobot.etw_capture import packet_payload


def position(x, y):
    return bytes([x >> 2, (x & 3) << 6 | y >> 4, (y & 15) << 4])


def messages():
    actor = bytearray(55)
    struct.pack_into('<HBI', actor, 0, 0x78, 0, 123)
    struct.pack_into('<H', actor, 15, 1212)
    actor[47:50] = position(12, 10)
    move = bytes.fromhex('870000000000') + bytes([2, 128, 160, 40, 10, 136])
    return bytes(actor) + move


def test_continuous_candidate_requires_recent_player_and_preserves_id():
    tracker = ContinuousTracker({1212})
    raw = messages()
    tracker.feed(100, raw[:55], 1)
    assert tracker.snapshot(1)['candidate'] is None
    tracker.feed(155, raw[55:], 1.1)
    state = tracker.snapshot(1.1)
    assert state['candidate']['entity_id'] == 123
    assert state['candidate']['species_id'] == 1212
    assert state['player_position_recent']
    assert not state['actionable']
    assert tracker.feed(100, raw, 1.2) == []
    assert tracker.snapshot(1.2)['messages'] == 2


def test_gap_pauses_selection_then_discards_world():
    tracker = ContinuousTracker({1212})
    raw = messages()
    tracker.feed(100, raw, 1)
    tracker.feed(100+len(raw)+5, b'\x7f\x00\x00\x00\x00\x00', 1.1)
    assert tracker.snapshot(1.2)['candidate'] is None
    assert tracker.snapshot(1.2)['state'] == 'waiting_reorder'
    failed = tracker.snapshot(1.7)
    assert failed['state'] == 'invalid'
    assert failed['recent_entities'] == []


def test_unknown_or_idle_discards_targets():
    tracker = ContinuousTracker({1212})
    raw = messages()
    tracker.feed(100, raw, 1)
    events = tracker.feed(100+len(raw), b'\xff\xff', 1.1)
    assert events[0]['kind'] == 'stream_resync' and not tracker.failed  # reading continues
    assert tracker.snapshot(1.1)['recent_entities']
    tracker = ContinuousTracker({1212})
    tracker.feed(100, raw, 1)
    assert tracker.snapshot(4.1)['recent_entities'] == []


def test_etw_batch_age_does_not_immediately_expire_reorder_wait():
    tracker = ContinuousTracker({1212})
    raw = messages()
    tracker.feed(100, raw[:55], 2, event_time=1)
    tracker.feed(157, raw[57:], 2.01, event_time=1.01)
    assert tracker.snapshot(2.02)['state'] == 'waiting_reorder'
    tracker.feed(155, raw[55:57], 2.03, event_time=1.02)
    assert tracker.snapshot(2.04)['candidate']['entity_id'] == 123


def test_delayed_events_pause_selection_without_losing_tcp_continuity():
    tracker = ContinuousTracker({1212})
    raw = messages()
    tracker.feed(100, raw, 10, event_time=5, delivery_lag=5)
    state = tracker.snapshot(10)
    assert state['state'] == 'waiting_fresh_events'
    assert state['candidate'] is None
    assert not tracker.failed
    tracker.feed(100+len(raw), raw, 11, event_time=11, delivery_lag=0)
    assert tracker.snapshot(11)['candidate']['entity_id'] == 123


def test_pktmon_manifest_payload_and_truncation():
    frame = b'example frame'
    raw = struct.pack('<Q7H2I2H', 1, 1, 0, 4, 1, 45, 1, 1, 0, 0, len(frame), len(frame)) + frame
    packet = packet_payload(raw)
    assert packet['frame'] == frame
    assert packet['component'] == 45
    with pytest.raises(ValueError, match='incompleto'):
        packet_payload(raw[:-1])


def test_ethernet_vlan_frame():
    ip = b'ip example'
    assert ipv4_from_ethernet(bytes(12)+b'\x08\x00'+ip) == ip
    assert ipv4_from_ethernet(bytes(12)+b'\x81\x00'+bytes(2)+b'\x08\x00'+ip) == ip
    assert ipv4_from_ethernet(bytes(12)+b'\x08\x06'+ip) is None


def legacy_filter(tmp_path):
    folder = tmp_path/'logs/rede/20261101-165840'
    folder.mkdir(parents=True)
    (folder/'captura.etl').write_bytes(b'proof')
    (folder/'conexao.json').write_text('{}')
    return ('Filtros de Pacote:\n  # Nome Protocolo IP Porta\n'
            '  1 NRO-20261101-165840 TCP 187.77.36.200 56390\n     5121\n'), folder


def test_legacy_cleanup_requires_local_evidence_and_no_foreign_filters(tmp_path):
    text, folder = legacy_filter(tmp_path)
    assert legacy_filter_captures(text, tmp_path) == [(folder/'captura.etl').resolve()]
    with pytest.raises(ValueError, match='não pertence'):
        legacy_filter_captures(text+'  2 OutroFiltro TCP 10.0.0.1 80\n', tmp_path)
    (folder/'conexao.json').unlink()
    with pytest.raises(ValueError, match='registros locais'):
        legacy_filter_captures(text, tmp_path)


def test_legacy_cleanup_stops_only_the_proven_session(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from nrobot import continuous_observer as module
    text, folder = legacy_filter(tmp_path)
    monkeypatch.setattr(module, '__file__', str(tmp_path/'nrobot/continuous_observer.py'))
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=b''))
    monkeypatch.setattr(module, 'active_session_file', lambda: str(folder/'captura.etl'))
    session = PktmonSession(None, tmp_path)
    calls = []
    def command(*args):
        calls.append(args)
        return 'Filtros de Pacote:\n Nenhum\n' if args == ('filter', 'list') else ''
    monkeypatch.setattr(session, 'command', command)
    session.clean_legacy_capture(text)
    assert calls == [('stop',), ('filter', 'remove'), ('filter', 'list')]
    calls.clear()
    monkeypatch.setattr(module, 'active_session_file', lambda: str(tmp_path/'foreign.etl'))
    with pytest.raises(ValueError, match='preservada'):
        session.clean_legacy_capture(text)
    assert calls == []
