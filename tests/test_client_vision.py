import struct

from nrobot.client_vision import ClientVision


def status(effect=184, entity=123, active=False):
    return struct.pack('<HHIB', 0x196, effect, entity, active)


def test_local_status_preserves_original_and_other_entities():
    raw = status()
    vision = ClientVision(None, 123, lambda: True)
    assert vision.feed(raw) == status(active=True)
    assert raw == status()
    other = status(entity=456)
    assert vision.feed(other) == other
    assert vision.feed(status(effect=160)) == status(effect=160)


def test_toggle_restores_real_status_without_repeating_packets():
    enabled = [True]
    vision = ClientVision(None, 123, lambda: enabled[0])
    assert vision.feed(status()) == status(active=True)
    enabled[0] = False
    tick = status(effect=160)
    assert vision.feed(tick) == tick + status()
    assert vision.feed(tick) == tick
    enabled[0] = True
    assert vision.feed(status(active=True)) == status(active=True)
    enabled[0] = False
    assert vision.feed(tick) == tick


def test_fragmented_account_and_messages_match_whole_stream():
    account = struct.pack('<I', 500)
    raw = account + status() + status(entity=456)
    expected = account + status(active=True) + status(entity=456)
    for split in range(len(raw)+1):
        vision = ClientVision(account, 123, lambda: True)
        assert vision.feed(raw[:split]) + vision.feed(raw[split:]) + vision.flush() == expected


def test_unknown_or_incomplete_packets_are_forwarded_unchanged():
    vision = ClientVision(None, None, lambda: True)
    unknown = b'\xff\xff\x01\x02\x03'
    assert vision.feed(unknown) == unknown
    assert vision.feed(b'next') == b'next'
    vision = ClientVision(None, 123, lambda: True)
    assert vision.feed(status()[:5]) == b''
    assert vision.flush() == status()[:5]


def test_missing_character_id_never_injects():
    vision = ClientVision(None, None, lambda: True)
    assert vision.feed(status()) == status()


def test_live_factory_uses_account_actor_not_character_selection_id():
    account = struct.pack('<I', 2002323)
    vision = ClientVision.for_account(account, lambda: True)
    ready = struct.pack('<H', 0x73) + bytes(9)
    assert vision.feed(account + ready) == account + ready + status(entity=2002323, active=True)
    assert vision.diagnostic()['player_id'] == 2002323
    assert vision.diagnostic()['local_updates'] == 1
    # A real server disable must target the same map actor.
    assert vision.feed(status(entity=2002323)) == status(entity=2002323, active=True)


def test_unknown_frame_is_reported_and_keeps_stream_intact():
    vision = ClientVision.for_account(None, lambda: True)
    data = b'\xff\xff\x01\x02'
    assert vision.feed(data) == data
    assert vision.diagnostic()['framing_error'] is not None
