from nrobot.client_frame_guard import ClientFrameGuard
from nrobot.packet_encoder import skill, move


def test_injection_waits_for_complete_native_frames_across_tcp_chunks():
    guard = ClientFrameGuard()
    packet = skill(20, 524, 10, ticks=lambda: 42)
    guard.feed(packet[:3])
    assert not guard.ready and guard.error is None
    guard.feed(packet[3:]+move(10, 10, ticks=lambda: 42)[:1])
    assert not guard.ready
    guard.feed(move(10, 10, ticks=lambda: 42)[1:])
    assert guard.ready


def test_unknown_native_frame_prevents_injection_without_logging_payload():
    guard = ClientFrameGuard()
    guard.feed(b'\xff\xffprivate-body')
    assert not guard.ready and 'FFFF' in guard.error and 'private' not in guard.error
    assert not guard.buffer


def test_less_effect_fragmented_and_followed_by_native_actions():
    """REDE-43: toggling visual effects must not suspend combat."""
    packet = b'\x1d\x02\x01\x00\x00\x00'
    following = move(10, 10, ticks=lambda: 42) + skill(20, 524, 10, ticks=lambda: 42)
    for split in range(1, len(packet)):
        guard = ClientFrameGuard()
        guard.feed(packet[:split])
        assert not guard.ready and guard.error is None
        guard.feed(packet[split:] + following)
        assert guard.ready and guard.error is None


def test_guild_master_query_does_not_block_injection():
    """REDE-44: routine guild query received in the user's session."""
    guard = ClientFrameGuard()
    guard.feed(b'\x4d')
    assert not guard.ready and guard.error is None
    guard.feed(b'\x01' + skill(1, 29, 5, ticks=lambda: 42))
    assert guard.ready and guard.error is None


def test_guild_info_query_following_master_query():
    guard = ClientFrameGuard()
    guard.feed(b'\x4d\x01\x4f\x01\x00')
    assert guard.error is None and not guard.ready
    guard.feed(b'\x00\x00\x00' + move(10, 10, ticks=lambda: 42))
    assert guard.ready


def test_manual_move_detection_waits_for_complete_frame():
    guard=ClientFrameGuard()
    packet=move(10,10,ticks=lambda:42)
    assert guard.feed(packet[:3])==[]
    assert guard.feed(packet[3:])==[0xa7]


def test_manual_frame_telemetry_contains_metadata_only(tmp_path):
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_hunt import PacketHunt
    relay=SessionRelay('127.0.0.1',folder=tmp_path)
    relay.hunt=PacketHunt()
    packet=move(10,10,ticks=lambda:42)
    relay.inspect_native_frames(packet)
    entry=relay.recent_map_sends[-1]
    assert set(entry)=={'time','source','opcode','size'}
    assert entry['source']=='client' and entry['opcode']=='00A7' and entry['size']==8


def test_variable_length_public_chat_from_client_table_does_not_block_injection():
    guard = ClientFrameGuard(fallback={0xf3: -1})
    chat = b'\xf3\x00\x0c\x00Oi: ola\x00'
    guard.feed(chat[:3])
    assert guard.error is None and not guard.ready
    assert guard.feed(chat[3:]+move(10, 10, ticks=lambda: 42)) == [0xf3, 0xa7]
    assert guard.ready and guard.sizes[0xf3] == 12


def test_opcode_absent_from_client_table_still_blocks():
    guard = ClientFrameGuard(fallback={})
    guard.feed(b'\xf3\x00\x0b\x00')
    assert guard.error and '00F3' in guard.error
