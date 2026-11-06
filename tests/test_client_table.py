import json
from pathlib import Path

import pytest

from nrobot import client_table
from nrobot.client_table import mask, reference, same_packet_table

ROOT = Path(__file__).resolve().parents[1]


def fake_client(region, before=b'\x90'*64):
    return before+region+b'\xcc'*64


def test_the_known_client_function_is_recognised_anywhere_in_the_file():
    signature, region = reference()
    assert same_packet_table(fake_client(region)) and same_packet_table(fake_client(region, b'\x00'*4096))
    assert not same_packet_table(b'\x90'*1000)


def test_a_rebuilt_client_with_moved_calls_and_addresses_is_accepted():
    signature, region = reference()
    rebuilt = bytearray(region)
    for index in mask(region):
        rebuilt[index] = (rebuilt[index]+13) % 256
    assert same_packet_table(fake_client(bytes(rebuilt)))


def test_every_changed_opcode_or_length_is_refused():
    signature, region = reference()
    entries = json.loads((ROOT/'data/rede/tamanhos_cliente.json').read_text(encoding='utf-8'))['entries']
    start = int(json.loads(client_table.REFERENCE.read_text(encoding='utf-8'))['file_offset'], 16)
    changed = 0
    for value in entries.values():
        for address in (value['key_address'], value['length_address']):
            index = int(address, 16)-0x400000-start
            head = region[index:index+2]
            target = index+3 if head in (b'\xc7\x45', b'\xc7\x40') else index+2 if head == b'\xc7\x00' else \
                index+1 if region[index] in (0xbb, 0xbe, 0xbf, 0xba) else None
            if target is None:
                continue
            other = bytearray(region)
            other[target] ^= 1
            assert not same_packet_table(fake_client(bytes(other))), (address, value)
            changed += 1
    assert changed > 1000


def test_connection_explains_a_missing_or_different_client(tmp_path, monkeypatch):
    from nrobot import packet_reader
    packet_reader.configure_client_game(tmp_path)
    try:
        with pytest.raises(ValueError, match='nao encontrado'):
            packet_reader.client_lengths()
        signature, region = reference()
        (tmp_path/'NRO.exe').write_bytes(fake_client(region))
        packet_reader.client_lengths.cache_clear()
        assert packet_reader.client_lengths()[0x11f] == 16  # another build, same table: accepted
        other = bytearray(region); other[region.find(bytes.fromhex('c7401003000000'))+3] = 9
        (tmp_path/'NRO.exe').write_bytes(fake_client(bytes(other)))
        packet_reader.client_lengths.cache_clear()
        with pytest.raises(ValueError, match='tabela de pacotes diferente'):
            packet_reader.client_lengths()
    finally:
        packet_reader.configure_client_game(None)
