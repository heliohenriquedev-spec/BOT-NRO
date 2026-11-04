"""Inject only between complete recognized native map-client frames."""
import struct


class ClientFrameGuard:
    SIZES = {0x8c: 11, 0xa7: 8, 0x89: 8, 0x190: 19, 0x72: 25, 0x118: 2,
             0x7d: 2, 0x7e: 6, 0x2ba: 11, 0x94: 6,
             # REDE-43: CZ_LESSEFFECT, OpenKore tables/aRO/recvpackets.txt.
             0x21d: 6,
             # REDE-44: rAthena clif_packetdb.hpp, GuildCheckMaster.
             0x14d: 2, 0x14f: 6, 0xa9: 6, 0xab: 4}

    def __init__(self, fallback=None):
        self.buffer = bytearray()
        self.error = None
        self.sizes = {}
        self.frames = []  # (opcode, bytes) completed by the last feed
        self._fallback = fallback

    def fallback(self):
        """Lengths extracted from the hash-checked client executable (-1 = variable)."""
        if self._fallback is None:
            try:
                from .packet_reader import client_lengths
                self._fallback = client_lengths()
            except (OSError, ValueError):
                self._fallback = {}
        return self._fallback

    @property
    def ready(self):
        return not self.buffer and self.error is None

    def feed(self, data):
        completed = []
        self.frames = []
        if self.error is not None:
            return completed
        self.buffer.extend(data)
        while len(self.buffer) >= 2:
            opcode = struct.unpack_from('<H', self.buffer)[0]
            size = self.SIZES.get(opcode, self.fallback().get(opcode))
            if size == -1:
                # Variable frames (e.g. 00F3 public chat) carry their length after the opcode.
                if len(self.buffer) < 4:
                    return completed
                size = struct.unpack_from('<H', self.buffer, 2)[0]
                if not 4 <= size <= 32768:
                    self.error = f'Comando nativo {opcode:04X} com comprimento invalido; envios do bot pausados para preservar a conexão'
                    self.buffer.clear()
                    return completed
            if size is None:
                self.error = f'Comando nativo {opcode:04X} sem enquadramento validado; envios do bot pausados para preservar a conexão'
                self.buffer.clear()
                return completed
            if len(self.buffer) < size:
                return completed
            self.frames.append((opcode, bytes(self.buffer[:size])))
            del self.buffer[:size]
            self.sizes[opcode] = size
            completed.append(opcode)
        return completed
