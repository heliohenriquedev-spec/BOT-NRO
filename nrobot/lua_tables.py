"""Constant tables from the client's compiled Lua 5.0/5.1 files (.lub), without running them.

The client's data tables are long runs of `Table[Ids.JT_X] = "text"` (or nested tables).
A tiny symbolic pass over the bytecode recovers them: registers hold constants, globals,
`global.KEY` lookups or new tables, and every SETTABLE/SETLIST is recorded. Anything else
(calls, arithmetic, loops) is ignored, so the reader never executes code from the files.
"""
from __future__ import annotations

import struct

# Opcode numbers per version: (MOVE, LOADK, GETGLOBAL, GETTABLE, SETGLOBAL, SETTABLE, NEWTABLE, SETLIST)
OPCODES = {0x50: (0, 1, 5, 6, 7, 9, 10, 31), 0x51: (0, 1, 5, 6, 7, 9, 10, 34)}


class _Reader:
    def __init__(self, data):
        if data[:4] != b'\x1bLua' or data[4] not in OPCODES:
            raise ValueError('Esperado bytecode Lua 5.0 ou 5.1')
        self.data, self.version = data, data[4]
        if self.version == 0x50:
            endian, self.int_size, self.size_t, instruction = data[5:9]
            self.number_size = data[13]
            self.pos = 14+self.number_size  # sizes of op/A/B/C, number size, test number
        else:
            endian, self.int_size, self.size_t, instruction, self.number_size = data[6:11]
            self.pos = 12
        if endian != 1 or instruction != 4:
            raise ValueError('Bytecode Lua com formato nao suportado')

    def take(self, n):
        chunk = self.data[self.pos:self.pos+n]
        if len(chunk) < n:
            raise ValueError('Bytecode Lua truncado')
        self.pos += n
        return chunk

    def int(self):
        return int.from_bytes(self.take(self.int_size), 'little', signed=True)

    def string(self):
        size = int.from_bytes(self.take(self.size_t), 'little')
        if not size:
            return None
        raw = self.take(size)[:-1]
        for encoding in ('ascii', 'cp949'):  # Korean file names, else Portuguese text
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                pass
        return raw.decode('cp1252', 'replace')

    def constants(self):
        values = []
        for _ in range(self.int()):
            kind = self.take(1)[0]
            if kind == 0:
                values.append(None)
            elif kind == 1:
                values.append(bool(self.take(1)[0]))
            elif kind == 3:
                value = struct.unpack('<d' if self.number_size == 8 else '<f', self.take(self.number_size))[0]
                values.append(int(value) if value == int(value) else value)
            elif kind == 4:
                values.append(self.string())
            else:
                raise ValueError(f'Constante Lua desconhecida: {kind}')
        return values

    def skip_debug(self):
        self.take(self.int_size*self.int())  # line info
        for _ in range(self.int()):  # local variables
            self.string(), self.int(), self.int()
        for _ in range(self.int()):  # upvalue names
            self.string()

    def code(self):
        count = self.int()
        return struct.unpack(f'<{count}I', self.take(4*count))

    def function(self):
        self.string()  # source
        if self.version == 0x50:
            self.int()  # line defined
            self.take(4)  # upvalues, parameters, vararg, max stack
            self.skip_debug()
            constants = self.constants()
            for _ in range(self.int()):
                self.function()
            return self.code(), constants
        self.int(), self.int()
        self.take(4)
        code, constants = self.code(), self.constants()
        for _ in range(self.int()):
            self.function()
        self.skip_debug()
        return code, constants


def decode_instruction(version, word):
    """(op, A, B, C, Bx, constant flag of RK operands)."""
    if version == 0x50:  # op 6 | C 9 | B 9 | A 8; RK constants start at 250
        return word & 0x3f, word >> 24, (word >> 15) & 0x1ff, (word >> 6) & 0x1ff, (word >> 6) & 0x3ffff, 250
    return word & 0x3f, (word >> 6) & 0xff, (word >> 23) & 0x1ff, (word >> 14) & 0x1ff, word >> 14, 256


def tables(data: bytes) -> dict:
    """{global name: {key: value}}; keys like `Ids.JT_X` become the string 'JT_X'."""
    reader = _Reader(data)
    code, constants = reader.function()
    MOVE, LOADK, GETGLOBAL, GETTABLE, SETGLOBAL, SETTABLE, NEWTABLE, SETLIST = OPCODES[reader.version]
    registers, built, names = {}, {}, {}

    def is_table(value):
        return isinstance(value, tuple) and len(value) == 2 and value[0] == 'table'

    def plain(value):
        if isinstance(value, tuple) and len(value) == 3 and value[0] == 'field':
            return value[2]
        return built[value[1]] if is_table(value) else value

    for word in code:
        op, a, b, c, bx, k = decode_instruction(reader.version, word)
        rk = lambda index: constants[index-k] if index >= k else registers.get(index)
        if op == MOVE:
            registers[a] = registers.get(b)
        elif op == LOADK:
            registers[a] = constants[bx]
        elif op == GETGLOBAL:
            name = constants[bx]
            registers[a] = ('table', names[name]) if name in names else ('global', name)
        elif op == GETTABLE:
            base, key = registers.get(b), rk(c)
            registers[a] = ('field', base, key)
            if is_table(base):
                value = built[base[1]].get(plain(key))
                registers[a] = ('table', id(value)) if isinstance(value, dict) else value
        elif op == SETGLOBAL:
            if is_table(registers.get(a)):
                names[constants[bx]] = registers[a][1]
        elif op == SETTABLE:
            if is_table(registers.get(a)):
                built[registers[a][1]][plain(rk(b))] = plain(rk(c))
        elif op == NEWTABLE:
            table = {}
            built[id(table)] = table
            registers[a] = ('table', id(table))
        elif op == SETLIST and is_table(registers.get(a)):
            if reader.version == 0x50:
                first, count = bx-bx % 32, bx % 32+1
            else:
                first, count = (c-1)*50, b
            for i in range(1, count+1):
                built[registers[a][1]][first+i] = plain(registers.get(a+i))
        elif op not in (SETGLOBAL, SETTABLE, SETLIST):
            registers[a] = None  # calls and other operations: result unknown
    return {name: built[key] for name, key in names.items()}
