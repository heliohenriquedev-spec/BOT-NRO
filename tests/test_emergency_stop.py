import asyncio
import struct
import time

from nrobot import watchlist
from nrobot.packet_hunt import PacketHunt
from nrobot.packet_reader import decode

OWN, GM, FRIEND, WATCHED = 2000001, 2000777, 2000888, 2000555


def relay_for(tmp_path, monkeypatch, watch=()):
    from nrobot.session_relay import SessionRelay
    monkeypatch.setattr(watchlist, 'FILE', tmp_path/'observacao.json')
    watchlist.save(list(watch))
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    relay.hunt = PacketHunt()
    relay.hunt.start()
    relay.tracker.observer.player_id, relay.tracker.observer.player = OWN, [10, 10]
    return relay


def see(relay, events, offset):
    # The relay reads its own clock (time.monotonic), so events use the same one.
    relay.presence.observe(events, OWN, time.monotonic()+offset-100, own_position=[10, 10])
    relay.track_players(events)
    relay.check_emergency()


def restart(relay):
    relay.commands_blocked = False
    relay.hunt.start()


def test_only_a_confirmed_hide_stops_everything_until_started_again(tmp_path, monkeypatch):
    async def scenario():
        relay = relay_for(tmp_path, monkeypatch)
        see(relay, [decode(struct.pack('<HIB', 0xc0, GM, 3))], 0)  # someone unseen acting: pause only, no stop
        assert not relay.commands_blocked and relay.emergency is None
        see(relay, [decode(struct.pack('<HIHHIB', 0x229, 2000999, 0, 0, 0x40, 0))], 6)  # @hide switched on
        assert relay.commands_blocked and not relay.hunt.enabled and relay.emergency['id'] == 1
        assert '@hide' in relay.emergency['reason']
        restart(relay)
        see(relay, [decode(struct.pack('<HIHHIB', 0x229, 2000999, 0, 0, 0x40, 0))], 7)  # same one: user already knows
        assert relay.hunt.enabled and relay.emergency['id'] == 1
        see(relay, [decode(struct.pack('<HIHHIB', 0x229, 2000998, 0, 0, 0x02, 0))], 8)  # common hide: no stop
        assert relay.hunt.enabled and relay.emergency['id'] == 1
    asyncio.run(scenario())


def test_watched_player_stops_the_bot_even_when_simply_visible(tmp_path, monkeypatch):
    async def scenario():
        relay = relay_for(tmp_path, monkeypatch, watch=[str(WATCHED)])
        appearance = {'kind': 'appearance', 'entity_id': WATCHED, 'species_id': 25, 'position': [12, 10], 'option': 0}
        see(relay, [{'kind': 'appearance', 'entity_id': FRIEND, 'species_id': 25, 'position': [13, 10], 'option': 0}], 0)
        assert relay.hunt.enabled and relay.emergency is None  # not on the list
        see(relay, [appearance], 1)
        assert not relay.hunt.enabled and 'observacao' in relay.emergency['reason']
        assert relay.emergency['detections'][0]['watched']
        restart(relay)
        see(relay, [{'kind': 'remove', 'entity_id': WATCHED, 'reason': 3}], 2)
        see(relay, [appearance], 3)  # left and came back: stops again
        assert not relay.hunt.enabled and relay.emergency['id'] == 2
    asyncio.run(scenario())


def test_whitelisted_friend_in_hide_does_not_stop(tmp_path, monkeypatch):
    async def scenario():
        relay = relay_for(tmp_path, monkeypatch)
        relay.presence.allowed.add(FRIEND)
        see(relay, [decode(struct.pack('<HIB', 0xc0, FRIEND, 3))], 0)
        assert relay.hunt.enabled and relay.emergency is None
    asyncio.run(scenario())


def test_a_gm_on_screen_by_name_really_stops_everything(tmp_path, monkeypatch):
    async def scenario():
        relay = relay_for(tmp_path, monkeypatch)
        relay.player_names[2000444] = '[GM] Hokage'
        see(relay, [{'kind': 'appearance', 'entity_id': 2000444, 'species_id': 25, 'position': [15, 10], 'option': 0},
                    {'kind': 'name', 'entity_id': 2000444, 'name': '[GM] Hokage'}], 0)
        assert relay.commands_blocked and not relay.hunt.enabled
        assert relay.emergency['detections'][0]['kind'] == 'gm' and 'GM' in relay.emergency['reason']
    asyncio.run(scenario())


def test_gm_signs_speed_guild_teleports_and_listed_visuals(tmp_path):
    from nrobot.gm_signs import GmSigns
    signs = GmSigns(); signs.config = {'visuais': {5038}, 'marcas': ['Hokage']}
    row = {'entity_id': 2000444, 'name': 'Fulano'}
    assert signs.reasons(row, {}, 150, 0) == []  # an ordinary character
    assert signs.reasons(row, {}, 20, 0) == ['velocidade anormal (20 ms/celula)']
    assert signs.reasons(row, {'guild': 'Equipe GM'}, 150, 0) == ['guilda de GM/staff']
    assert signs.reasons({**row, 'name': 'Hokage Sombra'}, {}, 150, 0) == ['nome de GM/staff']
    assert signs.reasons(row, {'look': {'head_top': 5038}}, 150, 0) == ['visual marcado como de GM (5038)']
    for t in (1, 10):
        signs.observe([{'kind': 'appearance', 'entity_id': 2000444, 'position': [12, 10], 'spawned': True}], [10, 10], t)
    assert signs.teleported_often(2000444, 11) and signs.reasons(row, {}, 150, 11) == []  # portals: a note, never a stop
