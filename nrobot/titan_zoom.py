"""Titan size: the game client's own zoom of each unit, set from the panel.

The NRO client keeps, for every unit it draws, a zoom factor and a shadow zoom (CRenderObject
m_zoom/m_shadowZoom, 1.0 = normal). The client never rewrites them on its own (checked on the
pinned build), so a value written here stays until the unit leaves the view; a unit that comes
back is a new object at 1.0 and is set again on the next pass. Only those two floats are written,
only on the SHA-pinned client the RCX layout was validated for; nothing reaches the server.

Layout (pinned NRO.exe): mode manager 0x7743F0 -> current mode (+4) -> world (+0xB4);
world +0x18 = list of units (VC6 std::list: node next +0, unit +8), world +0x3C = own unit;
unit +0x210 = game ID, +0x3C/+0x40 = zoom/shadow zoom.
"""
import ctypes as C
import hashlib
import struct
from ctypes import wintypes as W

from .npc_labels import plain
from .rcx_client import CLIENT_HASHES, MODE_MANAGER

WORLD, ACTORS, OWN, GID, ZOOM = 0xb4, 0x18, 0x3c, 0x210, 0x3c
MAX_ACTORS = 600


def desired_scales(config, rows, own_id=None):
    """{game ID: zoom} wanted by the enabled rules (ID > name > species, like the colour)."""
    if not config.get('enabled'):
        return {}
    rules = [r for r in config['rules'] if r['enabled'] and r['scale'] != 1.0]
    result = {}
    for rule in rules:
        if rule['kind'] == 'entity':
            result[int(rule['value'])] = rule['scale']
    for row in rows:
        if row['id'] in result:
            continue
        name = plain(row.get('name') or '')
        rank = None
        for rule in rules:
            if rule['kind'] == 'name' and name and plain(rule['value']) == name:
                rank = (2, rule['scale']) if rank is None or rank[0] < 2 else rank
            elif rule['kind'] == 'species' and rule['value'] == str(row['species']) and rank is None:
                rank = (1, rule['scale'])
        if rank:
            result[row['id']] = rank[1]
    return result


class Memory:
    """Read/write of the game process (the two zoom floats only)."""

    def __init__(self, pid):
        self.k = C.WinDLL('kernel32', use_last_error=True)
        self.k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.k.OpenProcess.restype = W.HANDLE
        self.k.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
        self.k.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
        self.k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
        # VM_READ | VM_WRITE | VM_OPERATION | QUERY_LIMITED_INFORMATION
        self.handle = self.k.OpenProcess(0x10 | 0x20 | 0x08 | 0x1000, False, pid)
        if not self.handle:
            raise OSError('Sem acesso ao jogo: abra o painel e o jogo com o mesmo nível de permissão.')

    def executable(self):
        buffer = C.create_unicode_buffer(32768)
        size = W.DWORD(len(buffer))
        if not self.k.QueryFullProcessImageNameW(self.handle, 0, buffer, C.byref(size)):
            raise OSError('Caminho do jogo indisponível')
        return buffer.value

    def read(self, address, size):
        buffer = C.create_string_buffer(size)
        got = C.c_size_t()
        if not self.k.ReadProcessMemory(self.handle, C.c_void_p(address), buffer, size, C.byref(got)) or got.value != size:
            raise OSError('Memória do jogo indisponível')
        return buffer.raw

    def write(self, address, data):
        done = C.c_size_t()
        if not self.k.WriteProcessMemory(self.handle, C.c_void_p(address), data, len(data), C.byref(done)):
            raise OSError('Não foi possível ajustar o tamanho no jogo')

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None


def game_pid():
    import os
    if os.name != 'nt':
        return None
    from .radar_overlay import find_game_window
    hwnd = find_game_window()
    if not hwnd:
        return None
    pid = W.DWORD()
    C.windll.user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
    return pid.value or None


class ZoomWriter:
    def __init__(self, memory_for=Memory, pid_finder=game_pid, verify=True):
        self.memory_for = memory_for
        self.pid_finder = pid_finder
        self.verify = verify
        self.memory = None
        self.pid = None
        self.touched = {}  # game ID -> zoom written (not 1.0)
        self.error = None

    def attach(self):
        if self.memory is not None:
            return
        pid = self.pid_finder()
        if pid is None:
            raise OSError('Jogo não encontrado.')
        memory = self.memory_for(pid)
        if self.verify:
            with open(memory.executable(), 'rb') as handle:
                if hashlib.sha256(handle.read()).hexdigest() not in CLIENT_HASHES:
                    memory.close()
                    raise OSError('Esta versão do NRO.exe não tem o tamanho validado; só cor e esconder funcionam.')
        self.memory, self.pid = memory, pid
        self.touched.clear()

    def detach(self):
        if self.memory is not None:
            self.memory.close()
        self.memory, self.pid = None, None

    def u32(self, address):
        return struct.unpack('<I', self.memory.read(address, 4))[0]

    def actors(self):
        mode = self.u32(MODE_MANAGER+4)
        if not mode or self.u32(MODE_MANAGER+88) != 1:
            return []  # loading or not in a map
        world = self.u32(mode+WORLD)
        if not world:
            return []
        found = []
        own = self.u32(world+OWN)
        if own:
            found.append(own)
        head = self.u32(world+ACTORS)
        node = self.u32(head)
        while node and node != head and len(found) < MAX_ACTORS:
            unit = self.u32(node+8)
            if unit and unit not in found:
                found.append(unit)
            node = self.u32(node)
        return found

    def step(self, wanted):
        """Sets each unit on screen to its wanted zoom; units no longer wanted go back to 1.0."""
        if not wanted and not self.touched:
            return 0
        try:
            self.attach()
            changed = 0
            for unit in self.actors():
                gid = self.u32(unit+GID)
                target = wanted.get(gid, 1.0 if gid in self.touched else None)
                if target is None:
                    continue
                current = struct.unpack('<f', self.memory.read(unit+ZOOM, 4))[0]
                if not .05 < current < 20:
                    continue  # not the expected layout: leave it alone
                if abs(current-target) > 1e-3:
                    self.memory.write(unit+ZOOM, struct.pack('<ff', target, target))
                    changed += 1
                if target == 1.0:
                    self.touched.pop(gid, None)
                else:
                    self.touched[gid] = target
            for gid in [g for g in self.touched if g not in wanted]:
                self.touched.pop(gid)  # out of view: it comes back as a new unit at 1.0
            self.error = None
            return changed
        except OSError as exc:
            self.error = str(exc)
            self.detach()  # the game closed or restarted: found again on the next pass
            return 0
