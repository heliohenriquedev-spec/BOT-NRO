"""Automatic login: native packet credentials and server-confirmed character selection.

The password is kept encrypted by Windows (DPAPI, current user only): it is never written in
plain text. The bot never types credentials into game/chat fields; the character
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
DEFAULTS = dict(enabled=False, user='', password='', character='', server_index=1, login_wait=8, type_when_open=False,
                packet_login=True, paused=False, screen_login=True)
BOOTSTRAP_USER = 'nrobotinit'


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


def select_world(packet, config):
    """Present only the chosen world to the native client, preserving authentication tokens."""
    if not config['enabled'] or config.get('paused') or not config.get('screen_login', True):
        return packet, False
    if len(packet) < 79 or (len(packet)-47) % 32 or packet[:2] != b'\x69\x00':
        raise ValueError('Lista de servidores nao validada para selecao automatica')
    index = int(config.get('server_index', 1))-1
    if not 0 <= index < (len(packet)-47)//32:
        raise ValueError('Servidor configurado nao existe na lista recebida')
    result = bytearray(packet[:47]+packet[47+32*index:79+32*index])
    struct.pack_into('<H', result, 2, len(result))
    return bytes(result), True


class LoginPacketAdapter:
    """Replace credentials only inside a recognized native 0064 request, never UI input.

    Version and client type come from the actual client. Unknown/encrypted variants pass
    unchanged. Authentication bytes are kept in memory only, not sent to diagnostics.
    """
    def __init__(self, config, sizes, decrypt=None):
        self.config, self.sizes, self.decrypt = config, sizes, decrypt or unprotect
        self.buffer = bytearray()
        self.finished = False
        self.reason = 'aguardando pedido nativo de autenticacao'
        self.strict = bool(config.get('_bootstrap'))
        self.rewritten = self.unsupported = False

    @staticmethod
    def field(value):
        try:
            raw = value.encode('cp1252')
        except UnicodeEncodeError:
            raise ValueError('Credencial nao representavel no formato do cliente') from None
        if not raw or b'\0' in raw or len(raw) > 23:
            raise ValueError('Credencial fora do limite do pacote 0064; dados nao foram truncados')
        return raw.ljust(24, b'\0')

    def feed(self, data):
        if self.finished:
            return data
        self.strict = self.strict or bool(self.config.get('_bootstrap'))
        if self.config.get('paused') or not self.config.get('enabled') or not self.config.get('packet_login', True):
            if self.strict:
                self.buffer.extend(data)
                if len(self.buffer) < 2:
                    return b''
                if self.buffer[:2] != b'\x64\x00':
                    self.buffer.clear()
                    raise ValueError('Login automatico interrompido; volte a selecao de conexao para controle manual')
                if len(self.buffer) < 55:
                    return b''
                if self.buffer[6:30].split(b'\0')[0].lower() == BOOTSTRAP_USER.encode():
                    self.buffer.clear()
                    raise ValueError('Login automatico interrompido antes da autenticacao; nenhum dado ficticio foi encaminhado')
                self.finished = True
                result = bytes(self.buffer); self.buffer.clear()
                self.reason = 'Login pausado; autenticacao manual encaminhada sem alterar'
                return result
            self.finished = True
            result = bytes(self.buffer)+data
            self.buffer.clear()
            self.reason = 'Login automatico pausado/desativado; controle manual do cliente'
            return result
        self.buffer.extend(data)
        if len(self.buffer) < 2:
            return b''
        prefix = bytearray()
        # Client hash and login keepalive may precede the authentication request.
        while len(self.buffer) >= 2:
            opcode = struct.unpack_from('<H', self.buffer)[0]
            size = {0x200: 26, 0x204: 18}.get(opcode)
            if size is None or self.sizes.get(opcode) != size:
                break
            if len(self.buffer) < size:
                return bytes(prefix)
            prefix.extend(self.buffer[:size]); del self.buffer[:size]
        if len(self.buffer) < 2:
            return bytes(prefix)
        opcode = struct.unpack_from('<H', self.buffer)[0]
        if opcode != 0x64 or self.sizes.get(0x64) != 55:
            self.unsupported = True
            if self.strict:
                self.buffer.clear()
                raise ValueError('Formato de autenticacao nao validado; inicializacao automatica cancelada')
            self.reason = 'Autenticacao nativa nao validada para substituicao; encaminhada sem alterar'
            self.finished = True
            result = bytes(self.buffer); self.buffer.clear()
            return bytes(prefix)+result
        if len(self.buffer) < 55:
            return bytes(prefix)
        original = bytes(self.buffer); self.buffer.clear(); self.finished = True
        if not self.config.get('user') or not self.config.get('password'):
            if self.strict:
                raise ValueError('Salve conta e senha antes do login automatico')
            self.reason = 'Credenciais nao configuradas; pedido nativo encaminhado sem alterar'
            return bytes(prefix)+original
        if self.strict and original[6:30].split(b'\0')[0].lower() != BOOTSTRAP_USER.encode():
            raise ValueError('Inicializacao de login alterada; tentativa automatica cancelada')
        try:
            user = self.field(self.config['user'])
            password = self.field(self.decrypt(self.config['password']))
        except (OSError, ValueError):
            if self.strict:
                raise ValueError('Credenciais salvas invalidas; autenticacao automatica cancelada') from None
            self.reason = 'Credenciais salvas incompativeis; pedido nativo encaminhado sem alterar'
            return bytes(prefix)+original
        self.reason = 'Credenciais aplicadas ao pacote nativo 0064; aguardando resultado do servidor'
        self.rewritten = True
        return bytes(prefix)+original[:6]+user+password+original[54:]


def relay_login_config(folder):
    config = load()
    try:
        marker = json.loads((Path(folder)/'login_bootstrap.json').read_text(encoding='utf-8'))
        config['_bootstrap'] = time.monotonic() < marker.get('until', 0)
    except (OSError, ValueError, TypeError):
        pass
    return config


# -- the game window ------------------------------------------------------------
def launch_game(folder):
    """Opens NRO if it is not open yet. True when the bot opened it."""
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


def log_in(config, report=print):
    """Packet login never types credentials or guesses which game dialog is open."""
    report('Login por pacotes preparado: aguardando abertura nativa da autenticacao pelo cliente. '
           'Reconhecimento das telas de desconexao/login ainda precisa ser validado; nenhuma tecla foi enviada.')
    return False
