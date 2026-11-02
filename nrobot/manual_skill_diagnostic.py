"""Passive recognition of the previously captured 25-byte skill layout.

Candidates are diagnostics only. Never forward, replay or modify captured bytes.
"""
import struct


class ManualSkillDiagnostic:
    def __init__(self):
        self.tail = b''

    def feed(self, data, learned):
        combined = self.tail+data
        result = []
        digits = set(b'0123456789abcdef')
        for offset in range(max(0, len(combined)-24)):
            packet = combined[offset:offset+25]
            if packet[:2] != b'\x72\x00':
                continue
            if any(packet[i] != 0 for i in (5, 9, 20)):
                continue
            if any(byte not in digits for byte in packet[2:5]+packet[8:9]+packet[12:20]):
                continue
            level, skill_id, target = struct.unpack_from('<H', packet, 6)[0], struct.unpack_from('<H', packet, 10)[0], struct.unpack_from('<I', packet, 21)[0]
            if skill_id not in learned or not 1 <= level <= learned[skill_id]['level'] or target == 0:
                continue
            result.append({'skill_id': skill_id, 'level': level, 'target_id': target,
                           'packet_hex': packet.hex(), 'classification': 'candidate_25_byte_layout'})
        self.tail = combined[-24:]
        return result
