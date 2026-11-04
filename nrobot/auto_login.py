"""Automatic login: open the game if needed, type account and password, pick the character.

The password is kept encrypted by Windows (DPAPI, current user only): it is never written in
plain text. The bot types only into a game it opened itself, at the login screen; the character
is chosen by the relay from the server's own list, by name.
"""
import base64
import ctypes
import json
import os
import struct
import subprocess
import time
import uuid
from ctypes import wintypes
from pathlib import Path

FILE = Path(__file__).resolve().parents[1]/'data/rede/login_automatico.json'
DEFAULTS = dict(enabled=False, user='', password='', character='', server_index=1, login_wait=8, type_when_open=False)


class _Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_char))]


def _blob(data):
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def protect(text):
    """Windows DPAPI: only this Windows user on this PC can read it back."""
    if not text:
        return ''
    if os.name != 'nt':
        raise OSError('Senha protegida exige Windows')
    source, keep = _blob(text.encode('utf-8'))
    out = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source), 'NRO BOT', None, None, None, 0, ctypes.byref(out)):
        raise OSError('Windows nao protegeu a senha')
    try:
        return base64.b64encode(ctypes.string_at(out.data, out.size)).decode('ascii')
    finally:
        ctypes.windll.kernel32.LocalFree(out.data)


def unprotect(token):
    if not token:
        return ''
    if os.name != 'nt':
        raise OSError('Senha protegida exige Windows')
    source, keep = _blob(base64.b64decode(token))
    out = _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError('Senha salva nao pode ser lida (outro usuario do Windows?); informe-a de novo')
    try:
        return ctypes.string_at(out.data, out.size).decode('utf-8')
    finally:
        ctypes.windll.kernel32.LocalFree(out.data)


def load(path=None):
    try:
        data = json.loads(Path(path or FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    result = dict(DEFAULTS)
    result.update({k: v for k, v in data.items() if k in DEFAULTS})
    return result


def save(config, path=None):
    path = Path(path or FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {k: config.get(k, v) for k, v in DEFAULTS.items()}
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    temporary.replace(path)


# -- the character, chosen by the relay ------------------------------------------------
def character_slot(char_list, name):
    """Slot of the character called name in the char server's list (006B), or None.

    Entries keep the classic layout for their first 106 bytes: name at 74, slot at 104."""
    wanted = (name or '').strip().encode('cp1252', 'replace')
    if not wanted:
        return None
    start = char_list.find(wanted+b'\0', 4)
    while start != -1:
        entry = start-74
        if entry >= 4 and entry+106 <= len(char_list):
            job = struct.unpack_from('<H', char_list, entry+52)[0]
            if job < 1000 or 4001 <= job < 5000:
                return char_list[entry+104]
        start = char_list.find(wanted+b'\0', start+1)
    return None


def select_packet(slot):
    return struct.pack('<HB', 0x66, slot)


# -- the game and the keyboard ------------------------------------------------------------
def launch_game(folder):
    """Opens NRO if it is not open yet. True when the bot opened it (so it may type the login)."""
    from .radar_overlay import find_game_window
    if find_game_window() is not None:
        return False
    folder = Path(folder)
    executable = next((folder/name for name in ('NRO.exe', 'nro.exe', 'Naruto.exe') if (folder/name).exists()), None)
    if executable is None:
        raise OSError('NRO.exe nao encontrado em '+str(folder))
    subprocess.Popen([str(executable)], cwd=str(folder))
    return True


def wait_game_window(seconds=90):
    from .radar_overlay import find_game_window
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        hwnd = find_game_window()
        if hwnd is not None:
            return hwnd
        time.sleep(1)
    return None


class _KeyInput(ctypes.Structure):
    _fields_ = [('vk', wintypes.WORD), ('scan', wintypes.WORD), ('flags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]


class _Input(ctypes.Structure):
    class _Union(ctypes.Union):
        _fields_ = [('ki', _KeyInput), ('padding', ctypes.c_byte*32)]
    _anonymous_ = ('u',)
    _fields_ = [('type', wintypes.DWORD), ('u', _Union)]


def _send(vk=0, scan=0, flags=0):
    item = _Input(type=1)
    item.ki = _KeyInput(vk, scan, flags, 0, 0)
    ctypes.windll.user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(_Input))


def press(vk, shift=False):
    """A real key (virtual key + scan code): old RO clients ignore Unicode "packet" keys."""
    user32 = ctypes.windll.user32
    if shift:
        _send(vk=0x10, scan=user32.MapVirtualKeyW(0x10, 0)); time.sleep(.02)
    scan = user32.MapVirtualKeyW(vk, 0)
    _send(vk=vk, scan=scan); time.sleep(.04); _send(vk=vk, scan=scan, flags=2)
    if shift:
        time.sleep(.02); _send(vk=0x10, scan=user32.MapVirtualKeyW(0x10, 0), flags=2)
    time.sleep(.06)


def type_text(text):
    user32 = ctypes.windll.user32
    for char in text:
        code = user32.VkKeyScanW(ord(char))
        if code == -1 or code & 0xff == 0xff:
            _send(scan=ord(char), flags=4); _send(scan=ord(char), flags=4 | 2)  # no key for it: Unicode
            time.sleep(.05)
        else:
            press(code & 0xff, shift=bool(code & 0x100))


def focus_game():
    """Bring the game forward even from a background thread: Windows allows it only when the input
    of the current foreground window is attached first."""
    from .radar_overlay import find_game_window
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    hwnd = find_game_window()
    if hwnd is None:
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    theirs = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    mine = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(mine, theirs, True)
    try:
        user32.keybd_event(0x12, 0, 0, 0); user32.keybd_event(0x12, 0, 2, 0)  # Alt unlocks SetForegroundWindow
        user32.SetForegroundWindow(hwnd); user32.BringWindowToTop(hwnd)
    finally:
        user32.AttachThreadInput(mine, theirs, False)
    time.sleep(.4)
    return user32.GetForegroundWindow() == hwnd


def log_in(config, report=print):
    """Types account and password at the login screen, then chooses the server by its place."""
    password = unprotect(config['password'])
    if not focus_game():
        report('Login automatico: o Windows nao deixou trazer o jogo para frente; clique no jogo e abra a conexao de novo.')
        return False
    report('Login automatico: digitando a conta...')
    type_text(config['user']); press(0x09)  # Tab
    type_text(password); press(0x0d)  # Enter
    time.sleep(3)
    if not focus_game():
        report('Login automatico: o jogo perdeu o foco antes de escolher o servidor.')
        return False
    for _ in range(max(0, int(config.get('server_index', 1))-1)):
        press(0x28)  # Down
    press(0x0d)
    report('Login automatico: servidor escolhido; o personagem e escolhido pelo bot quando a lista chegar.')
    return True
