"""Is an unknown NRO.exe's packet table the same as the one the bot knows?

The bot reads and sends packets with the lengths of data/rede/tamanhos_cliente.json, taken from a
known NRO.exe (checked by SHA-256). A client rebuilt or patched by the server's updater has another
SHA-256 even when its packet table did not change. The client registers every packet in one
straight function (opcode, then its length); data/rede/registro_pacotes.json keeps that function
from the known client. Another NRO.exe is accepted when the same function is found in it with the
same bytes, except the 4 bytes after each call (e8) and each "mov ecx, address" (b9), which only
move when the executable is rebuilt. Any opcode or length that changed refuses the client, as before.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT/'data'/'rede'/'registro_pacotes.json'
RELOCATED = (0xe8, 0xb9)


def protected(region):
    """Bytes of the packet opcodes and lengths: always compared. They are the immediates of
    mov [ebp+x], imm32 (c7 45 ..), mov [eax+x], imm32 (c7 40 .. / c7 00) and mov reg, imm32.
    Read left to right, skipping each immediate, so bytes inside one (opcode 0x00BE, 0x00C7...)
    are never taken for the start of another instruction."""
    keep, index, size = set(), 0, len(region)
    while index < size-1:
        a, b = region[index], region[index+1]
        if a in (0x8d, 0x89, 0x8b) and 0x40 <= b <= 0x7f:
            index += 3  # lea/mov with an 8-bit displacement (8d 4d e8: lea ecx, [ebp-18], not a call)
        elif a == 0xc7 and b in (0x45, 0x40):
            keep.update(range(index+3, index+7)); index += 7
        elif a == 0xc7 and b == 0x00:
            keep.update(range(index+2, index+6)); index += 6
        elif a in (0xbb, 0xbe, 0xbf, 0xba):
            keep.update(range(index+1, index+5)); index += 5
        elif a in RELOCATED:
            index += 5  # call / mov ecx, address: its operand is not an instruction either
        else:
            index += 1
    return keep


def mask(region):
    """Positions whose bytes may differ between builds (relative calls, absolute addresses)."""
    keep = protected(region)
    skip = set()
    for index, value in enumerate(region):
        if value in RELOCATED and index not in keep:
            skip.update(i for i in range(index+1, index+5) if i not in keep)
    return skip


def reference(path=None):
    try:
        data = json.loads(Path(path or REFERENCE).read_text(encoding='utf-8'))
        return bytes.fromhex(data['signature']), bytes.fromhex(data['region'])
    except (OSError, ValueError, KeyError):
        return None


def same_packet_table(executable_bytes, ref=None):
    """True when the packet registration function of this executable matches the known one."""
    ref = ref or reference()
    if ref is None:
        return False
    signature, region = ref
    ignored = mask(region)
    fixed = [i for i in range(len(region)) if i not in ignored]
    matches = 0
    start = executable_bytes.find(signature)
    while start >= 0:
        other = executable_bytes[start:start+len(region)]
        if len(other) == len(region) and all(region[i] == other[i] for i in fixed):
            matches += 1
        start = executable_bytes.find(signature, start+1)
    return matches == 1  # exactly one registration function equal to the known one


@lru_cache(maxsize=8)
def check(path_text, size, mtime):
    """(sha256, same table) of an executable, cached by file name, size and time."""
    data = Path(path_text).read_bytes()
    return hashlib.sha256(data).hexdigest(), same_packet_table(data)


def build_reference(executable, start, end, signature_length=21, path=None):
    """Developer tool: store the registration function of a verified client."""
    data = Path(executable).read_bytes()
    region = data[start:end]
    Path(path or REFERENCE).write_text(json.dumps({
        'source_sha256': hashlib.sha256(data).hexdigest(), 'file_offset': hex(start),
        'signature': region[:signature_length].hex(), 'region': region.hex()}, indent=1)+'\n', encoding='utf-8')
