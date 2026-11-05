"""Own-process IPC controller for the isolated, version-pinned native D3D7 renderer."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import mmap
import os
from pathlib import Path
import subprocess
import time

from . import rcx_client

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT/'data/recursos/rcx'
CAPACITY = 4096


class Cell(C.Structure):
    _fields_ = [('x', C.c_int16), ('y', C.c_int16), ('fill', C.c_uint32), ('outline', C.c_uint32), ('symbol', C.c_uint32)]


class Preview(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in ('skill_id', 'radius', 'shape', 'fill', 'outline', 'symbol', 'unit_type')]


class Shared(C.Structure):
    _pack_ = 4
    _fields_ = [(name, C.c_uint32) for name in (
        'magic', 'version', 'pid', 'enabled', 'sequence', 'count', 'last_feed',
        'attached', 'status', 'drawn', 'frames', 'error', 'mode_manager', 'renderer_global')]
    _fields_ += [('map_name', C.c_char*40), ('fill', C.c_uint32), ('outline', C.c_uint32), ('cells', Cell*CAPACITY)]
    # IPC version 2 (rcx.c): per-cell colours/symbol and skill previews; previews stay off (count 0).
    _fields_ += [('preview_count', C.c_uint32), ('selection_preview', C.c_uint32), ('selected_id', C.c_uint32),
                 ('previews', Preview*256)]


def manifest():
    record = json.loads((ASSETS/'renderer.json').read_text(encoding='utf-8'))
    name = record['dll']
    if Path(name).name != name or not name.endswith('.dll') or record.get('architecture') != 'x86':
        raise ValueError('Manifesto RCX invalido')
    dll = ASSETS/name
    if hashlib.sha256(dll.read_bytes()).hexdigest() != record['sha256']:
        raise ValueError('DLL RCX diferente da versao compilada; restaure os recursos do bot.')
    return record, dll


class RcxRenderer:
    def __init__(self):
        self.memory = self.shared = self.mutex = self.process = None
        self.state = {}
        self.state_at = 0
        self.enabled = False
        self.info = None

    def update(self, state):
        self.state = state
        self.state_at = time.monotonic()

    def start(self, hwnd=None):
        if self.enabled:
            return
        if os.name != 'nt':
            raise ValueError('RCX requer Windows e cliente NRO de 32 bits.')
        if hwnd is None:
            from .radar_overlay import game_window
            hwnd = game_window()
        if not hwnd:
            raise ValueError('Abra o NRO e entre no mapa antes de ativar RCX.')
        user = C.WinDLL('user32', use_last_error=True)
        user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        pid = W.DWORD()
        if not user.GetWindowThreadProcessId(hwnd, C.byref(pid)):
            raise ValueError('Janela do NRO indisponivel')
        info = rcx_client.inspect(pid.value)
        record, dll = manifest()
        k = C.WinDLL('kernel32', use_last_error=True)
        k.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
        k.CreateMutexW.restype = W.HANDLE
        k.CloseHandle.argtypes = [W.HANDLE]
        self.k = k
        self.mutex = k.CreateMutexW(None, False, f'Local\\NroRcxOwner_{pid.value}')
        if not self.mutex:
            raise OSError('Nao foi possivel reservar o controle RCX.')
        if C.get_last_error() == 183:
            k.CloseHandle(self.mutex); self.mutex = None
            raise ValueError('Outro painel ja controla o RCX deste NRO.')
        try:
            self.memory = mmap.mmap(-1, C.sizeof(Shared), tagname=f'Local\\NroRcx1_{pid.value}_{record["build"]}', access=mmap.ACCESS_WRITE)
            self.shared = Shared.from_buffer(self.memory)
            C.memset(C.addressof(self.shared), 0, C.sizeof(Shared))
            self.shared.magic, self.shared.version, self.shared.pid = 0x31584352, 2, pid.value
            self.shared.mode_manager = info['mode_manager']
            self.shared.renderer_global = info['renderer_global']
            self.shared.fill, self.shared.outline = 0xff808080, 0xff303030
            self.enabled, self.info = True, info
            self.feed()
            system = Path(os.environ.get('WINDIR', r'C:\Windows'))/'SysWOW64/rundll32.exe'
            if not system.is_file():
                raise ValueError('Carregador Windows x86 nao encontrado.')
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            entry = record.get('entry', 'Run@16')
            if entry != 'Run@16':
                raise ValueError('Entrada do renderer RCX invalida')
            command = subprocess.list2cmdline([str(system)])+f' "{dll}",{entry} {int(hwnd)}'
            self.process = subprocess.Popen(command, executable=str(system),
                                            cwd=str(ASSETS), startupinfo=startup,
                                            creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            self.close()
            raise

    def feed(self):
        if self.shared is None:
            return
        s = self.shared
        ground = self.state.get('ground_cells') or {}
        recent = time.monotonic()-self.state_at < 2.5
        points = ground.get('cells', []) if recent else []
        valid = sorted({(p[0], p[1]) for p in points if isinstance(p, (list, tuple)) and len(p) == 2
                        and all(type(v) is int and 0 <= v < 1024 for v in p)})[:CAPACITY]
        name = rcx_client.map_key(ground.get('map')) if recent else ''
        encoded = name.encode('cp1252', 'replace')
        if len(encoded) >= 40:
            valid, encoded = [], b''
        s.sequence = (s.sequence+1) | 1
        s.map_name = encoded
        s.count = len(valid)
        for i, (x, y) in enumerate(valid):
            cell = s.cells[i]
            cell.x, cell.y, cell.fill, cell.outline, cell.symbol = x, y, s.fill, s.outline, 0
        s.last_feed = C.windll.kernel32.GetTickCount() & 0xffffffff
        s.enabled = int(self.enabled)
        s.sequence += 1

    def snapshot(self):
        if self.shared is None:
            return dict(enabled=False, attached=False, frames=0, drawn=0, error=0)
        self.feed()
        s = self.shared
        return dict(enabled=self.enabled, attached=bool(s.attached), frames=s.frames, drawn=s.drawn,
                    error=s.error, status=s.status, received=s.count,
                    helper_running=self.process is not None and self.process.poll() is None)

    def stop(self):
        self.enabled = False
        if self.shared is not None:
            self.shared.enabled = 0
            self.shared.count = 0
            self.shared.drawn = 0

    def close(self):
        self.stop()
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            self.process = None
        self.shared = None
        if self.memory is not None:
            self.memory.close(); self.memory = None
        if self.mutex is not None:
            self.k.CloseHandle(self.mutex); self.mutex = None
