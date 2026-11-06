"""Sleep status is observed without suppressing attacks; manual movement never walks to targets."""
import struct
import time

from nrobot.map_navigation import CollisionMap
from nrobot.packet_hunt import PacketHunt
from nrobot.packet_reader import decode


def test_body_state_is_read_from_appearance_and_state_change():
    change = decode(struct.pack('<HIHHIB', 0x229, 110000001, 4, 0, 0, 0))
    assert change['kind'] == 'option_change' and change['body_state'] == 4
    stand = bytearray(58); struct.pack_into('<H', stand, 0, 0x22a); struct.pack_into('<I', stand, 2, 2003137)
    struct.pack_into('<H', stand, 8, 4)
    assert decode(bytes(stand))['body_state'] == 4


def relay_with_monster(tmp_path, body_state=0):
    from nrobot.packet_settings import DEFAULTS
    from nrobot.session_relay import SessionRelay
    relay = SessionRelay('127.0.0.1', folder=tmp_path, allow_commands=True)
    relay.hunt = PacketHunt()
    relay.apply_settings({**DEFAULTS, 'species': [1037], 'auto_map_targets': False})
    observer = relay.tracker.observer
    observer.player_id, observer.player, observer.player_at = 1, [10, 10], time.monotonic()
    event = {'kind': 'appearance', 'entity_id': 110000001, 'species_id': 1037, 'position': [12, 10],
             'object_type': 5, 'body_state': body_state}
    relay.inventory.observe([event], time.monotonic())
    relay.tracker.observer.registry.update(
        __import__('nrobot.network_targets', fromlist=['Entity']).Entity(110000001, 1037, 12, 10, time.monotonic(), 'monster'))
    return relay


def test_sleeping_target_remains_in_combat_candidates(tmp_path):
    relay = relay_with_monster(tmp_path)
    assert [e['entity_id'] for e in relay.status()['recent_entities']] == [110000001]
    relay.inventory.observe([{'kind': 'option_change', 'entity_id': 110000001, 'option': 0, 'body_state': 4}],
                            time.monotonic())  # someone (or you) put it to sleep
    assert [e['entity_id'] for e in relay.status()['recent_entities']] == [110000001]
    relay.inventory.observe([{'kind': 'option_change', 'entity_id': 110000001, 'option': 0, 'body_state': 0}],
                            time.monotonic())


def test_sleeping_target_can_be_sent_an_attack(tmp_path):
    import asyncio
    relay = relay_with_monster(tmp_path, body_state=4)
    relay.hunt.start()

    class Writer:
        def __init__(self): self.packets = []
        def write(self, data): self.packets.append(data)
        async def drain(self): pass
    relay.upstream = Writer()
    asyncio.run(relay.send_hunt_action({'kind': 'attack', 'target_id': 110000001}, game_gate=lambda: True))
    assert relay.upstream.packets


def state(*monsters):
    return dict(state='tracking', player_position_recent=True, player_position=[10, 10], player_sp=100,
                engagement_range=6, learned_skills=[],
                recent_entities=[dict(entity_id=i, position=p, position_age_seconds=.1) for i, p in monsters])


def test_manual_movement_never_walks_and_takes_the_nearest_target():
    collision = CollisionMap(30, 30, bytes([1])*900)
    hunt = PacketHunt(); hunt.start(); hunt.auto_movement = False
    assert hunt.plan(state((20, [20, 10])), 0, collision=collision) is None  # far: no walk at all
    assert hunt.target == 20
    near = hunt.plan(state((20, [20, 10]), (21, [11, 10])), 1, collision=collision)
    assert near == dict(kind='attack', target_id=21)  # the far one is not kept
    assert hunt.plan(state((22, [12, 10])), 2, collision=collision) is None  # 2 cells: the server would step


def test_manual_movement_keeps_skills_clearly_inside_their_range(tmp_path):
    from nrobot.packet_settings import DEFAULTS
    relay = relay_with_monster(tmp_path)
    relay.apply_settings({**DEFAULTS, 'species': [1037], 'manual_movement': True})
    assert relay.rotation is None or relay.rotation.range_margin == 1
    relay.apply_settings({**DEFAULTS, 'species': [1037], 'manual_movement': False, 'auto_movement': True})
    assert relay.rotation is None or relay.rotation.range_margin == 0
