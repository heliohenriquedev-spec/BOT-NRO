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
import threading
from . import rcx_settings

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
    # IPC version 2 (rcx.c): per-cell colours/symbol and skill previews.
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
        self.config = rcx_settings.load()
        self.lock = threading.RLock()
        self.worker_stop = threading.Event()
        self.worker = None
        self.stream = None
        self.stream_path = None
        self.stream_value = None
        self.stream_retry_at = 0
        self.prepared_key = None
        self.config_revision = 0
        self.prepared_ground = None

    def update(self, state):
        with self.lock:
            self.state = state
            self.state_at = time.monotonic()

    def configure(self, value):
        with self.lock:
            self.config=rcx_settings.validate(value)
            self.config_revision+=1
            self.prepared_key=None
        self.feed()

    def pump(self):
        while not self.worker_stop.wait(.008):
            try:self.feed()
            except (OSError,ValueError,BufferError):pass

    def read_ground(self):
        ground=self.state.get('ground_cells') or {}
        path=ground.get('feed_ipc')
        if path!=self.stream_path:
            if self.stream is not None:self.stream.close()
            self.stream=None;self.stream_path=path;self.stream_value=None;self.stream_retry_at=0
        if path:
            try:
                if self.stream is None:
                    if time.monotonic()<self.stream_retry_at:return self.stream_value or ground
                    self.stream_retry_at=time.monotonic()+.25
                    from .rcx_stream import Reader
                    self.stream=Reader(path)
                value=self.stream.read()
                if value is not None:self.stream_value=value
            except (OSError,ValueError):pass
            if self.stream_value is not None:return self.stream_value
        return ground

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
        self.game_pid, self.alive_checked_until = pid.value, 0
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
            self.worker_stop.clear()
            self.worker=threading.Thread(target=self.pump,name='RCX-feed',daemon=True)
            self.worker.start()
        except Exception:
            self.close()
            raise

    def feed(self):
        with self.lock:
            if self.shared is None:return
            s=self.shared
            ground=self.read_ground()
            recent=self.stream.fresh() if self.stream is not None else time.monotonic()-self.state_at<2.5
            now=time.monotonic()
            casts=[c for c in ground.get('casts',[]) if c.get('expires',0)>now] if recent else []
            learned=self.state.get('learned_skills') or []
            key=(id(ground),recent,self.config_revision,tuple((c['skill_id'],c['expires']) for c in casts),
                 tuple((x.get('skill_id'),x.get('level'),x.get('target_flags')) for x in learned))
            if key!=self.prepared_key:
                definitions=rcx_settings.preview_definitions(self.config,learned)
                by_id={d['skill_id']:d for d in definitions}
                external_definitions=rcx_settings.external_preview_definitions(self.config,casts)
                points={}
                effects=ground.get('effects')
                unique={r['unit_type']:r['skills'][0]['skill_id'] for r in rcx_settings.catalog() if len(r['skills'])==1}
                activation={r['unit_type']:skill for r in rcx_settings.catalog() for skill in r['skills'] if skill.get('activation_area')}
                if effects is None:effects=[dict(position=p,effect_type=157) for p in ground.get('cells',[])]
                if recent:
                    for e in effects:
                        p=e.get('position');kind=e.get('effect_type')
                        if not isinstance(p,(list,tuple)) or len(p)!=2 or any(type(v) is not int or not 0<=v<1024 for v in p):continue
                        style=rcx_settings.style_for(self.config,kind,e.get('skill_id') or (activation.get(kind) or {}).get('skill_id') or unique.get(kind))
                        if style['enabled'] and rcx_settings.visible_source(style,e.get('source_id'),ground):
                            area=e.get('area')
                            covered=rcx_settings.footprint(*area,'square') if isinstance(area,list) and len(area)==3 else [p]
                            if kind in activation:
                                model=activation[kind]
                                radius=style['radius'] if style['area_override'] else model['radius']
                                shape=style['shape'] if style['area_override'] else model['shape']
                                covered=rcx_settings.footprint(*p,radius,shape)
                            for cell in covered:
                                points[tuple(cell)]=(rcx_settings.argb(style['fill'],style['opacity']),rcx_settings.argb(style['outline'],style['opacity']),list(rcx_settings.SYMBOLS).index(style['symbol']))
                    for cast in casts:
                        definition=(external_definitions.get((cast['skill_id'],max(1,cast.get('level') or 1))) if cast.get('external') else by_id.get(cast['skill_id']))
                        if definition is None or not definition.get('cast_preview',True):continue
                        if cast.get('external') and not rcx_settings.visible_source(definition,cast.get('source_id'),ground):continue
                        if not cast.get('external') and not definition.get('show_allies',True):continue
                        for p in rcx_settings.footprint(*cast['position'],definition['radius'],definition['shape']):
                            points.setdefault(tuple(p),rcx_settings.preview_visual(self.config,definition))
                name=rcx_client.map_key(ground.get('map')) if recent else ''
                encoded=name.encode('cp1252','replace')
                if len(encoded)>=40:points,encoded={},b''
                s.sequence=(s.sequence+1)|1
                s.map_name=encoded
                s.count=min(CAPACITY,len(points))
                for i,((x,y),(fill,outline,symbol)) in enumerate(sorted(points.items())[:CAPACITY]):
                    s.cells[i]=Cell(x,y,fill,outline,symbol)
                s.selection_preview=int(recent)
                aim_definitions=[d for d in definitions if not d.get("self_centered") and d.get("selection_preview",True) and d.get('show_allies',True)]
                s.preview_count=len(aim_definitions) if recent else 0
                for i,d in enumerate(aim_definitions):
                    fill,outline,symbol=rcx_settings.preview_visual(self.config,d)
                    s.previews[i]=Preview(d['skill_id'],d['radius'],list(rcx_settings.SHAPES).index(d['shape']),
                        fill,outline,symbol,d['unit_type'])
                s.sequence+=1
                self.prepared_ground=ground
                self.prepared_key=key
            s.last_feed=C.windll.kernel32.GetTickCount()&0xffffffff
            s.enabled=int(self.enabled)
            self.heartbeat(bool(self.enabled and s.attached and self.game_alive()))

    STILL_ACTIVE = 259

    def game_alive(self):
        """The game this RCX was attached to is still running. A reopened game is another process:
        the old drawing stays attached to the closed one (2026-11-07), so it must be started again."""
        pid=getattr(self,'game_pid',None)
        if not pid or os.name!='nt':return bool(pid)
        now=time.monotonic()
        if now<getattr(self,'alive_checked_until',0):return self.alive
        k=C.WinDLL('kernel32',use_last_error=True)
        k.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];k.OpenProcess.restype=W.HANDLE
        k.GetExitCodeProcess.argtypes=[W.HANDLE,C.POINTER(W.DWORD)];k.CloseHandle.argtypes=[W.HANDLE]
        handle=k.OpenProcess(0x1000,False,pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        code=W.DWORD()
        alive=bool(handle) and bool(k.GetExitCodeProcess(handle,C.byref(code))) and code.value==self.STILL_ACTIVE
        if handle:k.CloseHandle(handle)
        self.alive,self.alive_checked_until=alive,now+1
        return alive

    def heartbeat_path(self):
        return Path(self.stream_path).parent/'rcx_ativo' if self.stream_path else None

    def heartbeat(self, drawing):
        """Tells the relay RCX is drawing in the game: only then it may hide the game's own
        effect of a skill (hide_native). A stale or missing file means RCX is off."""
        path=self.heartbeat_path()
        if path is None:return
        now=time.monotonic()
        if drawing and now-getattr(self,'heartbeat_at',0)>=1:
            try:path.touch();self.heartbeat_at=now
            except OSError:pass
        elif not drawing and getattr(self,'heartbeat_at',0):
            try:path.unlink(missing_ok=True)
            except OSError:pass
            self.heartbeat_at=0

    def snapshot(self):
        if self.shared is None:
            return dict(enabled=False, attached=False, frames=0, drawn=0, error=0)
        self.feed()
        s = self.shared
        return dict(enabled=self.enabled, attached=bool(s.attached), frames=s.frames, drawn=s.drawn,
                    error=s.error, status=s.status, received=s.count, selected_skill=s.selected_id, direct_stream=self.stream is not None,
                    helper_running=self.process is not None and self.process.poll() is None)

    def stop(self):
        self.enabled = False
        if self.shared is not None:
            self.shared.enabled = 0
            self.shared.count = 0
            self.shared.drawn = 0

    def close(self):
        self.worker_stop.set()
        if self.worker is not None:
            self.worker.join(timeout=1)
            self.worker=None
        self.stop()
        if getattr(self,'heartbeat_at',0) and self.heartbeat_path() is not None:
            try:self.heartbeat_path().unlink(missing_ok=True)
            except OSError:pass
            self.heartbeat_at=0
        if self.stream is not None:
            self.stream.close();self.stream=None
        self.stream_path=self.stream_value=None
        self.prepared_key=None
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            self.process = None
        self.shared = None
        if self.memory is not None:
            self.memory.close(); self.memory = None
        if self.mutex is not None:
            self.k.CloseHandle(self.mutex); self.mutex = None
