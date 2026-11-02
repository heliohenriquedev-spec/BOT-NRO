import struct
from nrobot.packet_reader import decode
from nrobot.network_observer import Observer
from nrobot.continuous_observer import ContinuousTracker


def test_f2_is_second_slot_and_survives_initial_position_message():
    packet = bytearray(191)
    struct.pack_into('<H', packet, 0, 0x2b9)
    struct.pack_into('<BIH', packet, 2, 0, 501, 1)
    struct.pack_into('<BIH', packet, 9, 1, 524, 10)
    struct.pack_into('<BIH', packet, 16, 1, 525, 5)
    event = decode(bytes(packet))
    assert event['hotkeys'][1] == {'slot': 1, 'type_raw': 1, 'id': 524, 'level': 10}
    tracker = ContinuousTracker({1037})
    tracker.observer.apply(event, 0)
    tracker.observer.apply({'kind': 'player_position_init', 'position': [1, 1]}, 0)
    assert tracker.snapshot(0)['f2_binding']['id'] == 524
    tracker.observer.clear()
    assert tracker.snapshot(0)['f2_binding'] is None
