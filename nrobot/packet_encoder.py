"""REDE-25: variante do NRO.exe analisado; nenhuma operação de rede.

Preenchimento: função 0x575DF0; montadores 0x58D543/0x58D57D/0x58C374.
Endereços são evidência estática, não endereços para execução no processo.
"""
from __future__ import annotations

import ctypes
import struct


def windows_tick():
    api = ctypes.WinDLL('winmm')
    api.timeGetTime.restype = ctypes.c_uint32
    return int(api.timeGetTime())


def filler(size: int, ticks=windows_tick) -> bytes:
    if not 1 <= size <= 19:
        raise ValueError('Comprimento de preenchimento inválido')
    first, second = ticks() & 0xffffffff, ticks() & 0xffffffff
    text = format((first >> (size & 31)) ^ second, 'x')[::-1]
    return (text + text[0]*size)[:size-1].encode('ascii') + b'\0'


def uint(value, bits, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value < 2**bits:
        raise ValueError(f'Valor inválido para inteiro de {bits} bits')
    return value


def attack(target_id: int, *, repeat=False, ticks=windows_tick) -> bytes:
    uint(target_id, 32, positive=True)
    return (struct.pack('<H', 0x190) + filler(3, ticks) + struct.pack('<I', target_id)
            + filler(9, ticks) + bytes([7 if repeat else 0]))


SIT, STAND = 2, 3


def body_action(action: int, *, ticks=windows_tick) -> bytes:
    """REDE-82: sit (2) or stand up (3); same action request as an attack, without a target."""
    if action not in (SIT, STAND):
        raise ValueError('Ação de corpo inválida')
    return (struct.pack('<H', 0x190) + filler(3, ticks) + struct.pack('<I', 0)
            + filler(9, ticks) + bytes([action]))


def skill(target_id: int, skill_id: int, level: int, *, ticks=windows_tick) -> bytes:
    uint(target_id, 32, positive=True)
    uint(skill_id, 16, positive=True)
    uint(level, 16, positive=True)
    return (struct.pack('<H', 0x72) + filler(4, ticks) + struct.pack('<H', level)
            + filler(2, ticks) + struct.pack('<H', skill_id) + filler(9, ticks)
            + struct.pack('<I', target_id))


def move(x: int, y: int, *, ticks=windows_tick) -> bytes:
    uint(x, 10)
    uint(y, 10)
    coords = bytes([x >> 2, ((x & 3) << 6) | (y >> 4), (y & 15) << 4])
    return struct.pack('<H', 0xa7) + filler(3, ticks) + coords


def equip_ammo(index: int):
    """REDE-57: native 0x5886DF/0x588B78, <opcode,index,position>, six bytes."""
    uint(index,16,positive=True)
    return struct.pack('<HHH',0xa9,index,0x8000)


def ground_skill(x: int, y: int, skill_id: int, level: int, *, ticks=windows_tick) -> bytes:
    """Native NRO 0x58C3BA..0x58C435: 0113, 22 bytes; level@5, id@9, x@12, y@20.
    The six opaque bytes between coordinates carry no semantic field in the builder.
    """
    uint(x, 10)
    uint(y, 10)
    uint(skill_id, 16, positive=True)
    uint(level, 16, positive=True)
    return (struct.pack('<H', 0x113)+filler(3, ticks)+struct.pack('<H', level)
            +filler(2, ticks)+struct.pack('<H', skill_id)+filler(1, ticks)
            +struct.pack('<H', x)+bytes(6)+struct.pack('<H', y))
