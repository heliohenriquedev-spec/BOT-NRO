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


def test_hidden_gm_acting_stops_everything_until_started_again(tmp_path, monkeypatch):
    async def scenario():
        relay = relay_for(tmp_path, monkeypatch)
        see(relay, [decode(struct.pack('<HIB', 0xc0, GM, 3))], 0)  # emote from nobody visible
        assert relay.commands_blocked and not relay.hunt.enabled
        assert '@hide' in relay.emergency['reason'] and relay.emergency['detections'][0]['kind'] == 'invisible'
        restart(relay)
        see(relay, [decode(struct.pack('<HIB', 0xc0, GM, 3))], 5)  # the same one again: user already knows
        assert relay.hunt.enabled and relay.emergency['id'] == 1
        see(relay, [decode(struct.pack('<HIHHIB', 0x229, 2000999, 0, 0, 0x40, 0))], 6)  # @hide switched on
        assert not relay.hunt.enabled and relay.emergency['id'] == 2
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
