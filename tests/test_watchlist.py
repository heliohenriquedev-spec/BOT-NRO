import os
import struct

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from nrobot import watchlist
from nrobot.packet_reader import decode
from nrobot.presence_guard import PresenceGuard

OWN, GM, OTHER = 2000001, 2000777, 2000555
REGISTRY = {str(GM): {'entity_id': GM, 'name': 'GM Sombra'}}


def state(guard, now, nearby=()):
    return {'presence': guard.snapshot([10, 10], now), 'players_nearby': list(nearby)}


def appearance(identity, option=0, species=25):
    return {'kind': 'appearance', 'entity_id': identity, 'species_id': species, 'position': [12, 10], 'option': option}


def kinds(entries, st):
    return [(d['entity_id'], d['kind']) for d in watchlist.detections(entries, st, REGISTRY)]


def test_every_way_of_being_around_is_matched_by_id_or_registered_name():
    for entries in (['2000777'], ['gm  sombra']):  # by id, or by name known from the registry
        cases = [
            ([appearance(GM)], 'visible'),
            ([appearance(GM, species=1002)], 'disguised'),
            ([appearance(GM), {'kind': 'option_change', 'entity_id': GM, 'option': 0x2}], 'hide'),
            ([appearance(GM), {'kind': 'option_change', 'entity_id': GM, 'option': 0x40}], 'gm_hide'),
            ([appearance(GM, option=0x40)], 'gm_hide'),
            # Already in @hide before we arrived: only its actions reveal it.
            ([decode(struct.pack('<HIB', 0xc0, GM, 3))], 'invisible'),
            ([appearance(GM), {'kind': 'remove', 'entity_id': GM, 'reason': 0}], 'vanished'),
        ]
        for events, expected in cases:
            guard = PresenceGuard()
            guard.observe(events, OWN, 0, own_position=[10, 10])
            assert kinds(entries, state(guard, 0)) == [(GM, expected)], (entries, expected)


def test_people_outside_the_list_are_ignored():
    guard = PresenceGuard()
    guard.observe([appearance(OTHER), appearance(GM)], OWN, 0)
    assert kinds(['2000777'], state(guard, 0)) == [(GM, 'visible')]
    assert kinds(['nobody'], state(guard, 0)) == []
    assert kinds([], state(guard, 0)) == []


def test_alert_fires_on_discovery_on_a_stronger_finding_and_again_after_leaving(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from nrobot import player_registry
    from nrobot.player_panel import PlayerPanel
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(watchlist, 'FILE', tmp_path/'observacao.json')
    monkeypatch.setattr(player_registry, 'FILE', tmp_path/'registro.json')
    panel = PlayerPanel()
    panel.set_watch(['2000777'])
    guard = PresenceGuard()
    guard.observe([appearance(GM)], OWN, 0)
    assert [d['kind'] for d in panel.check_watch(state(guard, 0))] == ['visible']
    assert panel.check_watch(state(guard, 1)) == []  # no repeated alert while it stays
    guard.observe([{'kind': 'option_change', 'entity_id': GM, 'option': 0x40}], OWN, 2)
    assert [d['kind'] for d in panel.check_watch(state(guard, 2))] == ['gm_hide']
    guard = PresenceGuard()  # map change: gone
    assert panel.check_watch(state(guard, 3)) == []
    guard.observe([appearance(GM)], OWN, 4)
    assert [d['kind'] for d in panel.check_watch(state(guard, 4))] == ['visible']
    assert watchlist.load(tmp_path/'observacao.json') == ['2000777']
