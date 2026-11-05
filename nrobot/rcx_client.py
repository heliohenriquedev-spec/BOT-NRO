"""Read-only compatibility checks for the NRO VC6 camera/terrain layout.

The native DLL touches only the local D3D device vtable; this reader never writes game memory.
Unknown executables do not receive a renderer hook.
"""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import math
from pathlib import Path
import struct

CLIENT_HASHES = {'8a77adb20ce94fded406e4d132d969830cd7d6e3cf7359e684bf651871e3b538',
                 '7af66a0d78c23f19ac95e096ca05e40e680d7207b75e2ff3e826016cf05b6b1f'}
MODE_MANAGER = 0x7743f0
RENDERER_GLOBAL = 0x7171d8


def map_key(name):
    value = (name or '').strip().lower().replace('\\', '/').rsplit('/', 1)[-1]
    for suffix in ('.gat', '.rsw'):
        if value.endswith(suffix):
            value = value[:-4]
    return value


class Reader:
    def __init__(self, pid):
        self.k = C.WinDLL('kernel32', use_last_error=True)
        self.k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.k.OpenProcess.restype = W.HANDLE
        self.k.CloseHandle.argtypes = [W.HANDLE]
        self.k.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
        self.k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
        self.handle = self.k.OpenProcess(0x410, False, pid)
        if not self.handle:
            raise OSError('Nao foi possivel ler a camera do NRO; execute painel e jogo no mesmo nivel de permissao.')

    def read(self, address, size):
        buffer = C.create_string_buffer(size)
        got = C.c_size_t()
        if not self.k.ReadProcessMemory(self.handle, address, buffer, size, C.byref(got)) or got.value != size:
            raise OSError('Estrutura grafica do NRO indisponivel; aguarde o carregamento do mapa.')
        return buffer.raw

    def u32(self, address):
        return struct.unpack('<I', self.read(address, 4))[0]

    def executable(self):
        buffer = C.create_unicode_buffer(32768)
        count = W.DWORD(len(buffer))
        if not self.k.QueryFullProcessImageNameW(self.handle, 0, buffer, C.byref(count)):
            raise OSError('Caminho do cliente NRO indisponivel')
        return Path(buffer.value)

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None


def inspect(pid):
    reader = Reader(pid)
    try:
        exe = reader.executable()
        if exe.name.lower() != 'nro.exe' or hashlib.sha256(exe.read_bytes()).hexdigest() not in CLIENT_HASHES:
            raise ValueError('Este NRO.exe ainda nao tem camera/terreno validados para o RCX.')
        mode = reader.u32(MODE_MANAGER+4)
        if not mode or reader.u32(MODE_MANAGER+88) != 1:
            raise ValueError('Entre no personagem e aguarde o mapa antes de ativar RCX.')
        world, view = reader.u32(mode+0xb4), reader.u32(mode+0xb8)
        renderer = reader.u32(RENDERER_GLOBAL)
        attr = reader.u32(world+0x40)
        width, height, zoom = struct.unpack('<III', reader.read(attr+0x110, 12))
        begin, end = reader.u32(attr+0x120), reader.u32(attr+0x124)
        if not (0 < width <= 1024 and 0 < height <= 1024 and zoom == 5 and end-begin == width*height*20):
            raise ValueError('Layout do terreno nao confirmado; RCX nao ativado.')
        matrix = struct.unpack('<12f', reader.read(view+0x98, 48))
        if not all(math.isfinite(v) for v in matrix) or any(not .8 <= sum(matrix[c+j*3]**2 for j in range(3)) <= 1.2 for c in range(3)):
            raise ValueError('Matriz da camera invalida; RCX nao ativado.')
        hpc, vpc = struct.unpack('<2f', reader.read(renderer, 8))
        sw, sh = struct.unpack('<2I', reader.read(renderer+0x24, 8))
        if not all(math.isfinite(v) and 10 < v < 50000 for v in (hpc, vpc)) or not (100 <= sw <= 16000 and 100 <= sh <= 16000):
            raise ValueError('Projecao do cliente invalida; RCX nao ativado.')
        device = reader.u32(renderer+0x7c)
        table = reader.u32(device)
        if not table or not reader.u32(table+20*4):
            raise ValueError('Dispositivo Direct3D7 indisponivel.')
        name = reader.read(MODE_MANAGER+8, 40).split(b'\0')[0].decode('cp1252', 'replace')
        return dict(map=map_key(name), width=width, height=height, mode_manager=MODE_MANAGER,
                    renderer_global=RENDERER_GLOBAL, executable=str(exe), screen=[sw, sh])
    finally:
        reader.close()
