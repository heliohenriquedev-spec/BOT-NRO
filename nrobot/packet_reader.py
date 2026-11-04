"""REDE-05/06/07: leitor passivo da variante observada do NRO.

Referência estrutural: rAthena/src/map/packets_struct.hpp, variante 20071106.
Offsets e comprimentos conferidos na captura local de 2026-11-01.
Sem conexão, envio, decriptação, leitura de memória ou integração ao combate.
"""
from __future__ import annotations

import argparse
import hashlib
from functools import lru_cache
from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import re
import socket
import struct


@dataclass(frozen=True)
class Segment:
    time: float
    source: tuple[str, int]
    destination: tuple[str, int]
    sequence: int
    payload: bytes


def read_pcapng(path: str | Path) -> list[Segment]:
    """Read complete EPBs; reject truncation instead of decoding partial bytes."""
    data = Path(path).read_bytes()
    if data[:4] != b'\x0a\x0d\x0d\x0a':
        raise ValueError('Esperado arquivo pcapng com cabeçalho de seção')
    pos, interfaces, result = 0, [], []
    endian = '<'
    while pos < len(data):
        if len(data) - pos < 12:
            raise ValueError('Cabeçalho pcapng truncado')
        if data[pos:pos+4] == b'\x0a\x0d\x0d\x0a':
            magic = data[pos+8:pos+12]
            if magic not in (b'\x4d\x3c\x2b\x1a', b'\x1a\x2b\x3c\x4d'):
                raise ValueError('Seção pcapng inválida')
            endian = '<' if magic == b'\x4d\x3c\x2b\x1a' else '>'
            interfaces = []
        kind, size = struct.unpack_from(endian + 'II', data, pos)
        if size < 12 or size % 4 or pos + size > len(data):
            raise ValueError('Bloco pcapng truncado ou inválido')
        block = data[pos:pos+size]
        if struct.unpack_from(endian + 'I', block, size-4)[0] != size:
            raise ValueError('Comprimentos pcapng divergentes')
        if kind == 1:
            if size < 20:
                raise ValueError('Interface pcapng truncada')
            link = struct.unpack_from(endian + 'H', block, 8)[0]
            resolution, offset, cursor = 1e-6, 0, 16
            while cursor + 4 <= size-4:
                option, n = struct.unpack_from(endian + 'HH', block, cursor)
                cursor += 4
                if option == 0:
                    break
                if cursor + n > size-4:
                    raise ValueError('Opção pcapng truncada')
                raw = block[cursor:cursor+n]
                if option == 9 and n == 1:
                    resolution = (2 if raw[0] & 128 else 10) ** -(raw[0] & 127)
                if option == 14 and n == 8:
                    offset = struct.unpack(endian + 'q', raw)[0]
                cursor += (n + 3) & ~3
            interfaces.append((link, resolution, offset))
        elif kind == 6:
            if size < 32:
                raise ValueError('Pacote pcapng truncado')
            iid, hi, lo, cap, original = struct.unpack_from(endian + 'IIIII', block, 8)
            if iid >= len(interfaces) or cap > size-32 or cap != original:
                raise ValueError('Pacote incompleto ou interface desconhecida')
            link, resolution, offset = interfaces[iid]
            if link != 1:
                raise ValueError(f'Interface não suportada: {link}; esperado Ethernet')
            raw = block[28:28+cap]
            if len(raw) < 14:
                raise ValueError('Ethernet truncado')
            protocol, start = struct.unpack_from('!H', raw, 12)[0], 14
            while protocol in (0x8100, 0x88a8):
                if start + 4 > len(raw):
                    raise ValueError('VLAN truncada')
                protocol = struct.unpack_from('!H', raw, start+2)[0]
                start += 4
            if protocol == 0x800:
                ip = raw[start:]
                if len(ip) < 20 or ip[0] >> 4 != 4:
                    raise ValueError('IPv4 inválido')
                ih, total = (ip[0] & 15) * 4, struct.unpack_from('!H', ip, 2)[0]
                if ih < 20 or total < ih or total > len(ip):
                    raise ValueError('Comprimento IPv4 inválido')
                if ip[9] == 6:
                    if struct.unpack_from('!H', ip, 6)[0] & 0x3fff:
                        raise ValueError('IPv4 fragmentado exige remontagem adicional')
                    tcp = ip[ih:total]
                    if len(tcp) < 20:
                        raise ValueError('TCP truncado')
                    th = (tcp[12] >> 4) * 4
                    if th < 20 or th > len(tcp):
                        raise ValueError('Cabeçalho TCP inválido')
                    sp, dp, seq = struct.unpack_from('!HHI', tcp)
                    if tcp[13] & 2:
                        seq = (seq + 1) & 0xffffffff
                    if tcp[th:]:
                        result.append(Segment(offset + ((hi << 32) | lo) * resolution,
                                              (socket.inet_ntoa(ip[12:16]), sp),
                                              (socket.inet_ntoa(ip[16:20]), dp), seq, tcp[th:]))
        pos += size
    return result


def reassemble(segments: list[Segment]):
    """Return contiguous runs and quality, without inventing missing bytes."""
    if not segments:
        return [], {'segments': 0, 'duplicate_segments': 0, 'gaps': 0, 'missing_bytes': 0}
    if len({(s.source, s.destination) for s in segments}) != 1:
        raise ValueError('Selecione uma única conexão e direção')
    anchor = segments[0].sequence
    def relative(s):
        return ((s.sequence - anchor + 2**31) % 2**32) - 2**31
    ordered = sorted(segments, key=lambda s: (relative(s), s.time))
    runs, duplicates, gaps, missing = [], 0, 0, 0
    start = end = None
    payload, spans = bytearray(), []
    for s in ordered:
        seq, body = relative(s), s.payload
        if end is not None and seq > end:
            runs.append((bytes(payload), spans))
            gaps += 1
            missing += seq - end
            start = end = None
            payload, spans = bytearray(), []
        if start is None:
            start = end = seq
        overlap = min(max(end - seq, 0), len(body))
        if overlap and payload[seq-start:seq-start+overlap] != body[:overlap]:
            raise ValueError('Retransmissão TCP com bytes conflitantes')
        if overlap == len(body):
            duplicates += 1
            continue
        spans.append((len(payload), s.time))
        payload.extend(body[overlap:])
        end += len(body) - overlap
    runs.append((bytes(payload), spans))
    return runs, {'segments': len(segments), 'duplicate_segments': duplicates,
                  'gaps': gaps, 'missing_bytes': missing}


# Fixed lengths observed here, not a packet database for arbitrary RO servers.
LENGTHS = {0x78: 55, 0x7c: 42, 0x22a: 58, 0x22b: 57, 0xc3: 8, 0x1d7: 11, 0x7f: 6, 0x80: 7, 0x86: 16, 0x87: 12,
           0x88: 10, 0x8a: 29, 0x91: 22, 0x95: 30, 0xb0: 8, 0xb1: 8,
           0x195: 102, 0x1f3: 10, 0x22c: 65, 0x2d4: 29, 0x229: 15, 0xd8: 6,
           0x13e: 24, 0x1b9: 6, 0x114: 31, 0x117: 18, 0x11a: 15,
           0x196: 9, 0x119: 13, 0x19b: 10, 0x199: 4, 0x1d6: 4,
           0xc0: 7, 0x9c: 9, 0x13d: 6, 0x13a: 4, 0xbe: 5, 0x141: 14,
           0x11f: 16, 0x120: 6, 0x1de: 33,
           0xaf: 6, 0xa8: 7, 0xac: 7, 0x1c8: 13, 0x9d: 17, 0x9e: 17, 0xa1: 6,
           0x73: 11, 0x2eb: 13, 0x43d: 8}

# Chat-room information is unrelated to targeting but must be framed correctly.
# 00D7 was observed with length 28 and title [Instrutor] in the local capture.
VARIABLE_MINIMUMS = {0x17f: 4, 0xd7: 17, 0xdf: 17,
                     0x9a: 4, 0x8d: 8, 0x8e: 4, 0x97: 28,
                     0xa3: 4, 0xa4: 4, 0xa5: 4, 0xa6: 4}


CLIENT_LENGTHS_FILE = Path(__file__).resolve().parents[1]/'data/rede/tamanhos_cliente.json'
CLIENT_GAME_DIR = None


def configure_client_game(game_dir):
    global CLIENT_GAME_DIR
    CLIENT_GAME_DIR = Path(game_dir) if game_dir is not None else None
    client_lengths.cache_clear()


@lru_cache(maxsize=1)
def client_lengths():
    path = CLIENT_LENGTHS_FILE
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    from .game_folder import saved
    game_dir = CLIENT_GAME_DIR or saved()
    executable = Path(game_dir)/'NRO.exe' if game_dir is not None else Path(data['source_executable'])
    if not executable.exists() or hashlib.sha256(executable.read_bytes()).hexdigest() != data['sha256']:
        raise ValueError(f'Tabela de pacotes incompativel ou NRO.exe ausente em {executable}. Confira a pasta do jogo; nao e possivel validar os dados iniciais.')
    return {int(key, 16): value['length'] for key, value in data['entries'].items()
            if value['length'] == -1 or 2 <= value['length'] <= 32768}


def message_length(data: bytes | bytearray, offset: int = 0) -> int | None:
    if len(data)-offset < 2:
        return None
    op = struct.unpack_from('<H', data, offset)[0]
    fallback = client_lengths().get(op) if op not in VARIABLE_MINIMUMS and op not in LENGTHS else None
    if op in VARIABLE_MINIMUMS or fallback == -1:
        if len(data)-offset < 4:
            return None
        size = struct.unpack_from('<H', data, offset+2)[0]
        if size < VARIABLE_MINIMUMS.get(op, 4) or size > 32768:
            raise ValueError('Comprimento variável inválido')
        return size
    if op not in LENGTHS:
        if fallback is not None:
            return fallback
        raise ValueError(f'Opcode não suportado: {op:04X}')
    return LENGTHS[op]


def position(raw: bytes):
    return [raw[0] << 2 | raw[1] >> 6, (raw[1] & 63) << 4 | raw[2] >> 4]


def movement(raw: bytes):
    return position(raw), [((raw[2] & 15) << 6) | raw[3] >> 2,
                           ((raw[3] & 3) << 8) | raw[4]]


def character_look_fields(message, *, hair, weapon, bottom, top, mid, hair_color, clothes, guild, sex, level):
    """What a character's appearance packet says about them (players only are kept by the registry)."""
    u16 = lambda offset: struct.unpack_from('<H', message, offset)[0]
    look = dict(hair=u16(hair), weapon=u16(weapon), shield=u16(weapon+2), head_bottom=u16(bottom), head_top=u16(top),
                head_mid=u16(mid), hair_color=u16(hair_color), clothes_color=u16(clothes),
                guild_id=struct.unpack_from('<I', message, guild)[0], sex='F' if message[sex] == 0 else 'M')
    if 1 <= u16(level) <= 9999:
        look['level'] = u16(level)
    return look


def combat_notice(text):
    """The game's own combat messages ("entrou em combate", "saiu de combate", refusals)."""
    if not re.search(r'combate', text, re.I):
        # Other @voltar/teleport answers are kept for the trace, never ordinary chat.
        if re.search(r'@?voltar|teleport|conjura|aguarde', text, re.I) and not text.startswith('[Cooldown]'):
            return dict(kind='server_notice', text=text[:200])
        return None
    out = re.search(r'sa(iu|indo)|fora de combate|n[aã]o est[aá] mais|terminou|livre', text, re.I)
    seconds = re.search(r'(\d{1,3})\s*seg', text, re.I)
    return dict(kind='combat_notice', text=text[:200], state='out' if out else 'in',
                seconds=int(seconds.group(1)) if seconds else None)


SERVER_TEXT_UNTIL = 0.0  # time.monotonic() deadline set right after the bot sends its own @ command


def server_text(op, text):
    """Lines the server writes to this character only, kept just after the bot's own @mi.

    Outside that short window, anything said by someone ("Name : text") and global broadcasts,
    nothing is kept."""
    import time
    if time.monotonic() >= SERVER_TEXT_UNTIL or op == 0x9a or ' : ' in text or not text.strip():
        return {'kind': 'other'}
    return {'kind': 'server_text', 'text': text[:300]}


def decode(message: bytes) -> dict:
    if message_length(message) != len(message):
        raise ValueError('Mensagem incompleta ou comprimento inesperado')
    op = struct.unpack_from('<H', message)[0]
    event = {'opcode': f'{op:04X}'}
    u32 = lambda offset: struct.unpack_from('<I', message, offset)[0]
    u16 = lambda offset: struct.unpack_from('<H', message, offset)[0]
    if op in (0x73, 0x2eb):
        event.update(kind='player_position_init', position=position(message[6:9]))
    elif op in (0x78, 0x7c, 0x22c):
        event.update(kind='appearance', entity_id=u32(3), object_type=message[2],
                     species_id=u16(21 if op == 0x7c else 17 if op == 0x22c else 15))
        event['option'] = u32(13) if op == 0x22c else u16(13)
        event['speed_raw'] = u16(7)  # unfiltered: a GM's @speed goes below the normal range
        if 50 <= u16(7) <= 2000:
            event['walk_speed_ms'] = u16(7)
        if op == 0x22c:
            event['position'], event['destination'] = movement(message[55:61])
            if len(message) >= 65:
                event['look'] = character_look_fields(message, hair=19, weapon=21, bottom=25, top=31, mid=33,
                                                      hair_color=35, clothes=37, guild=41, sex=54, level=63)
        else:
            event['position'] = position(message[37:40] if op == 0x7c else message[47:50])
    elif op in (0x22a, 0x22b):
        # Characters standing still (022A) or spawning/warping in (022B): unlike 022C these
        # carry no object-type byte, so a player is known on sight, before it walks.
        event.update(kind='appearance', entity_id=u32(2), species_id=u16(16), option=u32(12),
                     position=position(message[50:53]), speed_raw=u16(6))
        if op == 0x22b:
            event['spawned'] = True  # warped/teleported in (or logged in) right there
        if 50 <= u16(6) <= 2000:
            event['walk_speed_ms'] = u16(6)
        event['look'] = character_look_fields(message, hair=18, weapon=20, bottom=24, top=26, mid=28, hair_color=30,
                                              clothes=32, guild=36, sex=49, level=56 if op == 0x22a else 55)
    elif op in (0x86, 0x87):
        event['kind'] = 'player_move' if op == 0x87 else 'move'
        if op == 0x86:
            event['entity_id'] = u32(2)
        event['position'], event['destination'] = movement(message[6:12])
        event['server_tick'] = u32(12) if op == 0x86 else u32(2)  # REDE-69: walk start
    elif op in (0xc3, 0x1d7):
        # Look change (class = 0, hair = 1, ...), sent to the own character too.
        event.update(kind='look_change', entity_id=u32(2), look_type=message[6],
                     value=message[7] if op == 0xc3 else u16(7))
    elif op == 0x7f:
        event.update(kind='server_time', server_tick=u32(2))
    elif op == 0x88:
        event.update(kind='position', entity_id=u32(2), position=[u16(6), u16(8)])
    elif op == 0x283:
        event.update(kind='own_identity', entity_id=u32(2))
    elif op == 0x2b9 and len(message) == 191:
        event.update(kind='hotkeys_info', hotkeys=[
            {'slot': index, 'type_raw': message[2+index*7],
             'id': u32(3+index*7), 'level': u16(7+index*7)} for index in range(27)])
    elif op in (0x10f, 0x111, 0x10e):
        entries = []
        if op == 0x10f and (len(message)-4) % 37 == 0:
            for offset in range(4, len(message), 37):
                entries.append({'skill_id': u16(offset), 'level': u16(offset+6),
                                'sp_cost': u16(offset+8), 'range': u16(offset+10),
                                'target_flags': u32(offset+2),
                                'name': message[offset+12:offset+36].split(b'\0')[0].decode('cp1252', 'replace')})
        elif op == 0x111 and len(message) == 39:
            entries.append({'skill_id': u16(2), 'level': u16(8), 'sp_cost': u16(10), 'range': u16(12),
                            'target_flags': u32(4), 'name': message[14:38].split(b'\0')[0].decode('cp1252', 'replace')})
        elif op == 0x10e and len(message) == 11:
            entries.append({'skill_id': u16(2), 'level': u16(4), 'sp_cost': u16(6), 'range': u16(8)})
        event.update(kind='skills_info' if entries or (op == 0x10f and len(message) == 4) else 'other',
                     skills=entries, replace=op == 0x10f)
    elif op == 0x8d:
        # Public chat from an actor: only the speaker is kept ("Name : text"), never the text.
        text = message[8:].split(b'\0')[0].decode('cp1252', 'replace')
        event.update(kind='actor_signal', signal='chat', entity_id=u32(4))
        if ' : ' in text:
            event['name'] = text.split(' : ', 1)[0].strip()
    elif op == 0xc0:
        event.update(kind='actor_signal', signal='emote', entity_id=u32(2))
    elif op == 0x9c:
        event.update(kind='actor_signal', signal='direction', entity_id=u32(2))
    elif op in (0x9a, 0x8e):
        # REDE-51: retain only the exact cooldown notice, never arbitrary chat text.
        text = message[4:].split(b'\0')[0].decode('cp1252', 'replace')
        notice = re.fullmatch(r'\[Cooldown\]: Por favor aguarde mais (\d{1,3}) segundos para este jutsu recarregar\.', text)
        if notice:
            event.update(kind='skill_retry_notice', seconds=int(notice.group(1)))
        else:
            event.update(combat_notice(text) or server_text(op, text))
    elif op in (0x1c3, 0x2c1, 0x17f) and len(message) > 4:
        # Colored server/NPC messages and NRO's 017F notices: only combat/@voltar notices are kept.
        text = message[{0x1c3: 16, 0x2c1: 12, 0x17f: 4}[op]:].split(b'\0')[0].decode('cp1252', 'replace')
        event.update(combat_notice(text) or server_text(op, text))
    elif op in (0xa3, 0x1ee, 0x2e8, 0xa4, 0x2d0):
        # NRO's client sends stackables (ammo included) as 02E8; 02D0 grew per packet version.
        stackable = op in (0xa3, 0x1ee, 0x2e8)
        strides = {0xa3: (18,), 0x1ee: (18,), 0x2e8: (22,), 0xa4: (20,), 0x2d0: (28, 26, 24)}[op]
        event.update(kind='inventory_layout_unknown', length=len(message))
        for stride in strides:
            if (len(message)-4) % stride:
                continue
            items = [{'index':u16(offset), 'item_id':u16(offset+2), 'type':message[offset+4],
                      'amount':u16(offset+6) if stackable else 1,
                      'equipped':u16(offset+8), 'location':0x8000 if message[offset+4] == 10 else 0,
                      'equip_location':0 if stackable else u16(offset+6)}
                     for offset in range(4, len(message), stride)]
            if (len({item['index'] for item in items}) == len(items)
                and not any(item['index'] == 0 or item['item_id'] == 0 or not 0 <= item['type'] <= 12 or item['amount'] <= 0 for item in items)):
                event.update(kind='inventory_list', stackable=stackable, items=items)
                del event['length']
                break
    elif op in (0xa0, 0x29a, 0x2d4) and len(message) in (23, 27, 29):
        # 00A0/029A/02D4: ... cards 11-18, equip location 19 (where it is worn), type 21, result 22.
        event.update(kind='inventory_added', index=u16(2), amount=u16(4), item_id=u16(6),
                     type=message[21], success=message[22] == 0, equip_location=u16(19))
    elif op in (0xaa, 0xac) and len(message) == 7:
        event.update(kind='equipment_ack', index=u16(2), position=u16(4), success=message[6] == 1, equipped=op == 0xaa)
    elif op == 0x13c and len(message) == 4:
        event.update(kind='ammo_equipped', index=u16(2))
    elif op == 0x110 and len(message) == 10:
        event.update(kind='skill_failed', skill_id=u16(2), cause_raw=message[9], flag_raw=message[8])
    elif op == 0x11a and len(message) == 15:
        event.update(kind='skill_no_damage', skill_id=u16(2), amount=u16(4), target_id=u32(6),
                     source_id=u32(10), success=bool(message[14]))
    elif op == 0x43d and len(message) == 8:
        event.update(kind='skill_cooldown', skill_id=u16(2), duration_ms=u32(4))
    elif op == 0x13e and len(message) == 24:
        event.update(kind='skill_cast', source_id=u32(2), target_id=u32(6), skill_id=u16(14), duration_ms=u32(20))
    elif op == 0x8a:
        event.update(kind='normal_attack', source_id=u32(2), target_id=u32(6),
                     damage_raw=u16(22), action_type=message[26], source_motion_ms=u32(14))
    elif op in (0x114, 0x1de):
        event.update(kind='skill_damage', skill_id=u16(2), source_id=u32(4), target_id=u32(8),
                       damage_raw=u16(24) if op == 0x114 else u32(24),
                       level=u16(26) if op == 0x114 else u16(28), source_motion_ms=u32(16))
    elif op in (0x119, 0x229):
        # Body/health state then option bits (hide, cloak, GM invisibility, ...).
        event.update(kind='option_change', entity_id=u32(2), option=u16(10) if op == 0x119 else u32(10))
    elif op == 0x196:
        event.update(kind='status_effect', effect_id=u16(2), entity_id=u32(4), active=bool(message[8]))
    elif op == 0x11f:
        event.update(kind='ground_effect', effect_id=u32(2), source_id=u32(6),
                     position=[u16(10), u16(12)], effect_type=message[14], visible=bool(message[15]))
    elif op == 0x120:
        event.update(kind='ground_effect_removed', effect_id=u32(2))
    elif op == 0xaf:
        event.update(kind='inventory_removed', inventory_index=u16(2), amount=u16(4))
    elif op in (0xb0, 0xb1):
        event.update(kind='player_stat', stat_type=u16(2), value=u32(4))
    elif op in (0x95, 0x195):
        event.update(kind='name', entity_id=u32(2),
                     name=message[6:30].split(b'\0')[0].decode('cp1252', 'replace'))
        if op == 0x195:
            guild = message[54:78].split(b'\0')[0].decode('cp1252', 'replace').strip()
            if guild:
                event['guild'] = guild
            title = message[78:102].split(b'\0')[0].decode('cp1252', 'replace').strip()
            if title:
                event['guild_title'] = title
            party = message[30:54].split(b'\0')[0].decode('cp1252', 'replace').strip()
            if party and not re.match(r'HP:', party):
                event['party'] = party
            # NRO customizes the party/guild display with textual HP.
            match = re.search(rb'HP:\s*(\d+)/(\d+)', message[30:54])
            if match:
                hp, maximum = map(int, match.groups())
                # The 24-byte field truncates long values, e.g. training dummies send
                # "HP: 4294967295/429496729": the cut maximum is then below the current HP.
                if match.end() == len(message[30:54].split(b'\0')[0]) and hp > maximum:
                    maximum = hp
                if maximum > 0 and 0 <= hp <= maximum:
                    event.update(hp=hp, max_hp=maximum)
    elif op == 0x81:
        event.update(kind='server_disconnect', reason_raw=message[2])
    elif op in (0xb4, 0xb7) and len(message)>=8:
        contents=message[8:].split(b'\0')[0].decode('cp1252','replace')
        event.update(kind='npc_dialog',entity_id=u32(4),action='menu' if op==0xb7 else 'text')
        if op==0xb7:event['options']=contents.split(':')
        else:event['text']=contents
    elif op in (0xb5, 0xb6) and len(message)==6:
        event.update(kind='npc_dialog',entity_id=u32(2),action='next' if op==0xb5 else 'close')
    elif op in (0x9d, 0x9e) and len(message) == 17:
        event.update(kind='floor_item', object_id=u32(2), item_id=u16(6), identified=bool(message[8]),
                     position=[u16(9), u16(11)], amount=u16(15 if op == 0x9e else 13),
                     newly_dropped=op == 0x9e)
    elif op == 0xa1 and len(message) == 6:
        event.update(kind='floor_item_removed', object_id=u32(2))
    elif op == 0x80:
        event.update(kind='remove', entity_id=u32(2), reason=message[6])
    elif op == 0x91:
        event.update(kind='map_change', map=message[2:18].split(b'\0')[0].decode('cp1252', 'replace'),
                     position=[u16(18), u16(20)])
    elif op == 0x92:
        event.update(kind='map_transfer', map=message[2:18].split(b'\0')[0].decode('cp1252','replace'),
                     position=[u16(18),u16(20)])
    else:
        event['kind'] = 'other'
    return event


def character_look(char_list: bytes, character_id: int):
    """Class, hair and name of one character from the char server's list (006B).

    Entries start with the character id and keep the classic offsets for the first 106
    bytes (class 52, hair 54, name 74) whatever extra fields the server appends, so the
    entry is found by its id instead of trusting a fixed entry size."""
    key = struct.pack('<I', character_id)
    start = char_list.find(key, 4)
    while start != -1:
        if start+98 <= len(char_list):
            name = char_list[start+74:start+98].split(b'\0')[0]
            job, hair = struct.unpack_from('<HH', char_list, start+52)
            if name and all(c >= 32 for c in name) and (job < 1000 or 4001 <= job < 5000):
                return {'job': job, 'hair': hair, 'name': name.decode('cp1252', 'replace')}
        start = char_list.find(key, start+1)
    return None


def analyze(path: Path, connection: dict):
    server = (connection['RemoteAddress'], int(connection['RemotePort']))
    client = (connection['LocalAddress'], int(connection['LocalPort']))
    segments = [s for s in read_pcapng(path) if s.source == server and s.destination == client]
    runs, quality = reassemble(segments)
    events, issues, opcodes = [], [], Counter()
    for index, (data, spans) in enumerate(runs):
        pos = 0
        while pos + 2 <= len(data):
            op = struct.unpack_from('<H', data, pos)[0]
            try:
                length = message_length(data, pos)
            except ValueError:
                length = None
            if length is None or pos + length > len(data):
                issues.append({'run': index, 'offset': pos, 'opcode': f'{op:04X}',
                               'unparsed_bytes': len(data)-pos,
                               'reason': 'unknown_opcode' if length is None else 'incomplete_message'})
                break
            timestamp = next(t for start, t in reversed(spans) if start <= pos)
            event = decode(data[pos:pos+length])
            event.update(time=timestamp, run=index, recovered_boundary=True)
            # Capture starts mid-session. A run boundary is only a diagnostic hypothesis.
            events.append(event)
            opcodes[f'{op:04X}'] += 1
            pos += length
        if len(data)-pos == 1:
            issues.append({'run': index, 'offset': pos, 'unparsed_bytes': 1, 'reason': 'trailing_byte'})
    entities = {}
    epoch = 0
    for e in events:
        if e['kind'] == 'map_change':
            epoch += 1
        if 'entity_id' not in e:
            continue
        key = (epoch, e['entity_id'])
        item = entities.setdefault(key, {'entity_id': e['entity_id'], 'map_epoch': epoch,
                                         'first_seen': e['time'], 'last_seen': e['time'], 'events': 0})
        item['events'] += 1
        item['last_seen'] = e['time']
        for field in ('name', 'species_id', 'object_type', 'hp', 'max_hp', 'position', 'destination'):
            if field in e:
                item[field] = e[field]
        if e['kind'] == 'remove':
            item['last_removal_reason'] = e['reason']
        if e['kind'] in ('appearance', 'position', 'move'):
            item['position_time'] = e['time']
    # History is deliberately not a current world-state nor an attack decision.
    return {'mode': 'offline_diagnostic', 'actionable': False, 'quality': quality,
            'opcodes': dict(opcodes), 'issues': issues, 'events': events,
            'entities': list(entities.values()),
            'limitations': ['Captura iniciada com sessão em andamento; limites recuperados são hipóteses.',
                            'Lacunas invalidam estado ao vivo; este relatório agrega apenas histórico.',
                            'Nome/HP não comprovam categoria de entidade nem autorização de ataque.',
                            'Posições são células de mapa em instantes passados; não coordenadas da tela.']}


def write_report(result: dict, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    (output / 'analise_rede.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    named = defaultdict(list)
    for entity in result['entities']:
        if entity.get('name'):
            named[entity['name']].append(entity)
    q = result['quality']
    lines = ['# Leitura da captura NRO', '',
             'Relatório histórico: não representa os monstros presentes agora e não envia comandos.', '',
             f"Segmentos recebidos: {q['segments']}; duplicatas removidas: {q['duplicate_segments']}; "
             f"lacunas: {q['gaps']}; bytes ausentes: {q['missing_bytes']}.", '',
             '| Nome recebido do servidor | Entidades distintas | Aparências observadas | HP máximo observado |',
             '| --- | ---: | --- | --- |']
    for name, items in sorted(named.items()):
        species = ', '.join(map(str, sorted({e['species_id'] for e in items if 'species_id' in e}))) or 'não capturada'
        hp = ', '.join(map(str, sorted({e['max_hp'] for e in items if 'max_hp' in e}))) or 'não informado'
        lines.append(f"| {name.replace('|', '/')} | {len(items)} | {species} | {hp} |")
    lines += ['', f"Mensagens interpretadas: {len(result['events'])}. Trechos não interpretados: {len(result['issues'])}.", '',
              *['- ' + text for text in result['limitations']], '',
              'Referência estrutural: [rAthena — estruturas de pacotes](https://github.com/rathena/rathena/blob/master/src/map/packets_struct.hpp).',
              'A variante do NRO foi conferida contra a captura local; a referência não substitui a validação do servidor.']
    (output / 'monstros_rede.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='Analisa captura NRO sem enviar comandos')
    parser.add_argument('capture', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    connection = json.loads((args.capture.parent / 'conexao.json').read_text(encoding='utf-8-sig'))
    result = analyze(args.capture, connection)
    output = args.output or args.capture.parent
    write_report(result, output)
    print(f"{len(result['events'])} mensagens; {len(result['entities'])} entidades históricas; "
          f"{result['quality']['gaps']} lacunas. Relatório: {output / 'monstros_rede.md'}")


if __name__ == '__main__':
    main()
