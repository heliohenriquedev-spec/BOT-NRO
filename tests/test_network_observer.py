"""REDE-08: seleções somente com dados recentes; perda interrompe o fluxo."""
import pytest

from nrobot.network_observer import LiveStream, Observer, snapshot_summary


def test_stream_fragmentation_duplicates_and_reordering():
    s = LiveStream()
    raw = bytes.fromhex('8000288b980601')
    assert s.feed(100, raw[:3], 0) == []
    assert s.feed(105, raw[5:], 0.1) == []
    events = s.feed(103, raw[3:5], 0.2)
    assert events[0]['kind'] == 'remove'
    assert events[0]['entity_id'] == 110660392
    assert s.feed(100, raw, 0.3) == []


def test_stream_gap_conflict_and_unknown_stop():
    s = LiveStream()
    raw = bytes.fromhex('8000288b980601')
    s.feed(100, raw, 0)
    s.feed(110, raw, 0.1)
    with pytest.raises(ValueError, match='Lacuna'):
        s.check_gap(0.7)
    with pytest.raises(ValueError, match='divergentes'):
        s.feed(100, b'XX', 0.2)


def test_unknown_custom_message_resyncs_without_inventing_events():
    """REDE-65: e.g. NRO global chat added by the client DLLs."""
    s = LiveStream()
    removal = bytes.fromhex('8000288b980601')
    events = s.feed(1, b'\xff\xff\x09\x00global' + removal, 0)
    assert [e['kind'] for e in events] == ['stream_resync'] and events[0]['opcode'] == 'FFFF'
    # A chunk starting mid-message is dropped, not decoded as a fake removal.
    assert s.feed(1+17, removal[3:]+removal[:3], .1) == []
    assert s.feed(1+24, removal[3:], .2) == []  # still misaligned: nothing invented
    assert [e['kind'] for e in s.feed(1+28, removal+removal, .3)] == ['remove', 'remove']
    assert s.resyncs == 1 and not s.resyncing


def test_observer_position_hp_removal_expiry_and_map():
    o = Observer({1212})
    o.apply({'kind': 'appearance', 'entity_id': 8, 'species_id': 1212, 'position': [10, 12]}, 1)
    assert o.choose(1) is None  # no player position
    o.apply({'kind': 'player_move', 'destination': [10, 10]}, 1)
    assert o.choose(1).entity_id == 8
    assert o.choose(7) is None  # stale position
    o.apply({'kind': 'appearance', 'entity_id': 8, 'species_id': 1212, 'position': [10, 12]}, 8)
    o.apply({'kind': 'player_move', 'destination': [10, 10]}, 8)
    o.apply({'kind': 'name', 'entity_id': 8, 'hp': 0}, 8)
    assert o.choose(8) is None
    o.apply({'kind': 'appearance', 'entity_id': 8, 'species_id': 1212, 'position': [10, 12]}, 9)
    o.apply({'kind': 'map_change', 'position': [0, 0]}, 9)
    assert o.choose(9) is None


def test_pktmon_snapshot_keeps_filter_and_does_not_claim_current_target():
    report = {'events': [{'time': 10}], 'quality': {'gaps': 3}, 'issues': [],
              'entities': [{'entity_id': 1, 'species_id': 1212, 'position': [10, 20],
                            'position_time': 8, 'hp': 0, 'last_removal_reason': 1},
                           {'entity_id': 2, 'species_id': 1051, 'position': [1, 2]}]}
    mapping = {'1212': {'name': 'Akino'}, '1051': {'name': 'Bikouchuu'}}
    summary = snapshot_summary(report, mapping, {1212})
    assert summary['actionable'] is False
    assert summary['gaps'] == 3
    assert len(summary['observed']) == 1
    assert summary['observed'][0]['name'] == 'Akino'
    assert summary['observed'][0]['removal_observed'] is True
    assert summary['observed'][0]['seconds_before_end'] == 2


def test_default_backend_never_opens_raw_socket(monkeypatch):
    import sys
    from nrobot import network_observer as module
    called = []
    monkeypatch.setattr(sys, 'argv', ['observer', '--server', '10.0.0.1', '--server-port', '5121',
                                     '--local', '10.0.0.2', '--local-port', '50000'])
    monkeypatch.setattr('builtins.input', lambda prompt: '1')
    monkeypatch.setattr(module, 'observe_pktmon', lambda species, mapping: called.append(species) or 0)
    def forbidden_socket(*args, **kwargs):
        raise AssertionError('O backend padrão não deve abrir socket bruto')
    monkeypatch.setattr(module.socket, 'socket', forbidden_socket)
    assert module.main() == 0
    assert called == [{1212}]
