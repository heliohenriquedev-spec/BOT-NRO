"""Optional client-side rendering adjustments for combat packets."""
import struct

from .packet_reader import message_length


class ImmediateMonsterRemoval:
    MULTI_HIT = 8  # rAthena DMG_MULTI_HIT: the client draws one hit per div
    def __init__(self, account, is_monster, drop=None, rewrite=True):
        self.account = account
        self.is_monster = is_monster
        self.drop = drop  # packet -> True: not forwarded to the client (the bot already read it)
        self.rewrite = rewrite
        self.pending = bytearray()
        self.started = False
        self.passthrough = False

    def flush(self):
        data = bytes(self.pending)
        self.pending.clear()
        return data

    def feed(self, data):
        if self.passthrough:
            return data
        self.pending.extend(data)
        output = bytearray()
        offset = 0
        if not self.started:
            if len(self.pending) < 4:
                return b''
            self.started = True
            if self.account and self.pending[:4] == self.account:
                output.extend(self.pending[:4])
                offset = 4
        while offset < len(self.pending):
            try:
                size = message_length(self.pending, offset)
            except (ValueError, OSError):
                self.passthrough = True
                output.extend(self.pending[offset:])
                offset = len(self.pending)
                break
            if size is None or offset+size > len(self.pending):
                break
            packet = self.pending[offset:offset+size]
            if self.drop is not None and self.drop(packet):
                offset += size
                continue
            if not self.rewrite:
                pass
            elif size == 7 and packet[:2] == b'\x80\x00' and packet[6] == 1:
                entity_id = struct.unpack_from('<I', packet, 2)[0]
                if self.is_monster(entity_id):
                    packet[6] = 0  # Client despawn, without the death animation.
            elif (size, bytes(packet[:2])) in ((31, b'\x14\x01'), (33, b'\xde\x01')):
                count_offset = size-3
                hit_count = struct.unpack_from('<h', packet, count_offset)[0]
                damage = struct.unpack_from('<h' if size == 31 else '<i', packet, 24)[0]
                if hit_count > 1 and damage > 0:
                    # Keep the damage value and limit only the client's visual reaction.
                    struct.pack_into('<h', packet, count_offset, 1)
                    motion = struct.unpack_from('<i', packet, 20)[0]
                    if motion > 60:
                        struct.pack_into('<i', packet, 20, 60)
            elif size == 29 and packet[:2] == b'\x8a\x00' and packet[26] == self.MULTI_HIT:
                # Basic attack hitting twice (Jyuuken Ryuu / Double Attack): drawn as one hit with
                # the same damage, like the multi-hit skills above. The server is not affected.
                if struct.unpack_from('<h', packet, 24)[0] > 1:
                    struct.pack_into('<h', packet, 24, 1)
                    packet[26] = 0
                    if struct.unpack_from('<i', packet, 18)[0] > 60:
                        struct.pack_into('<i', packet, 18, 60)
            output.extend(packet)
            offset += size
        del self.pending[:offset]
        return bytes(output)
