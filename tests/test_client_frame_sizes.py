"""The client's own length table decides how its commands are framed."""
from nrobot.client_frame_guard import ClientFrameGuard


def test_client_table_wins_over_the_classic_sizes():
    """0094 is 14 bytes in NRO.exe: read as 6 it left 8 bytes taken for a command (1600, 2026-11-04)."""
    guard = ClientFrameGuard(fallback={0x94: 14, 0x89: 8, 0x7e: 102})
    name_request = bytes([0x94, 0]) + bytes(range(1, 13))
    attack = bytes([0x89, 0]) + bytes(6)
    assert guard.feed(name_request+attack) == [0x94, 0x89]
    assert guard.error is None and guard.ready


def test_unknown_to_the_client_table_falls_back_to_the_classic_sizes():
    guard = ClientFrameGuard(fallback={})
    assert guard.feed(bytes([0x7d, 0])) == [0x7d] and guard.ready


def test_real_client_table_frames_the_commands_of_this_game():
    import pytest
    from nrobot.packet_reader import client_lengths
    try:
        table = client_lengths()
    except (OSError, ValueError):
        pytest.skip('NRO.exe deste PC nao disponivel')
    if not table:
        pytest.skip('tabela do cliente ausente')
    guard = ClientFrameGuard()
    for opcode, size in ((0x94, table.get(0x94)), (0x89, table.get(0x89))):
        if size and size > 0:
            assert guard.feed(opcode.to_bytes(2, 'little')+bytes(size-2)) == [opcode]
    assert guard.error is None
