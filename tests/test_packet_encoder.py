import pytest

from nrobot.packet_encoder import attack, skill, move, filler
from nrobot.packet_reader import position


@pytest.mark.parametrize('tick,target,expected', [
    (0xAAA1210, 110660284, '9001323500bc8a980639313734666161390000'),
    (0xAB59FC4, 110660280, '9001633300b88a980662303563306261620000'),
    (0xAB61ED0, 110660250, '90016130009a8a980666643534336261660000'),
])
def test_attack_matches_full_real_capture(tick, target, expected):
    assert attack(target, ticks=lambda: tick).hex() == expected


@pytest.mark.parametrize('tick,target,expected', [
    (0xAA8CFD6, 110660221, '7200623233000a0033000c023162623964616131007d8a9806'),
    (0xAAAB97A, 110660199, '7200646532000a0034000c02363263656661613600678a9806'),
    (0xDEE23F, 110776987, '7200633163000a0030000c026534643865646565009b529a06'),
])
def test_skill_matches_full_real_capture(tick, target, expected):
    assert skill(target, 524, 10, ticks=lambda: tick).hex() == expected


def test_movement_coordinates_and_filler_tick_rollover():
    assert position(move(106, 83, ticks=lambda: 42)[-3:]) == [106, 83]
    ticks = iter([0xffffffff, 0])
    assert filler(3, ticks=lambda: next(ticks)) == b'ff\0'
    for args in [(-1, 1), (1, 1024)]:
        with pytest.raises(ValueError):
            move(*args)
