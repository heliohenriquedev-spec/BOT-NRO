"""Consulta teclas/foco e dono da conexão; não simula entrada nem lê memória."""
import ctypes as C
from pathlib import PureWindowsPath
import socket
import struct
import time


def connection_pid(peer, local):
    api = C.WinDLL('iphlpapi')
    api.GetExtendedTcpTable.argtypes = [C.c_void_p, C.POINTER(C.c_uint32), C.c_int, C.c_uint32, C.c_int, C.c_uint32]
    size = C.c_uint32()
    result = api.GetExtendedTcpTable(None, C.byref(size), False, 2, 5, 0)
    if result not in (0, 122):
        return None
    data = C.create_string_buffer(size.value)
    if api.GetExtendedTcpTable(data, C.byref(size), False, 2, 5, 0):
        return None
    count = struct.unpack_from('<I', data)[0]
    for index in range(count):
        state, addr, port, remote, remote_port, pid = struct.unpack_from('<6I', data, 4+index*24)
        source = (socket.inet_ntoa(struct.pack('<I', addr)), socket.ntohs(port & 65535))
        destination = (socket.inet_ntoa(struct.pack('<I', remote)), socket.ntohs(remote_port & 65535))
        if state == 5 and source == peer and destination == local:
            return pid
    return None


class GameControls:
    # The relay asks "is the game still connected?" before every packet, many times per tick.
    # Reading the whole TCP table and opening the process each time took ~20% of the relay's
    # time in combat, and that loop also forwards the server's packets to the game (2026-11-06).
    PID_TTL = 1.0  # s a found connection owner is reused
    MISS_TTL = .25  # s a missing one is reused
    WALK_INPUT_TTL = .5  # tolerate packet framing/delivery after a real game click

    def __init__(self):
        self.owner_cache = {}  # (peer, local) -> (pid or None, checked at)
        self.exe_cache = {}  # pid -> is NRO.exe
        self.last_walk_input = -float('inf')
        self.ui = C.WinDLL('user32')
        self.ui.GetForegroundWindow.restype = C.c_void_p
        self.ui.GetWindowThreadProcessId.argtypes = [C.c_void_p, C.POINTER(C.c_uint32)]
        self.ui.GetAsyncKeyState.argtypes = [C.c_int]
        self.ui.GetAsyncKeyState.restype = C.c_int16

    def down(self, key):
        return bool(self.ui.GetAsyncKeyState(key) & 0x8000)

    def panic(self):
        return self.down(0x7b)  # F12

    def test_pressed(self):
        return self.down(0x11) and self.down(0x12) and self.down(0x79)

    def hunt_pressed(self, key=0x24):
        return self.down(key)  # Home unless configured (REDE-82)

    def connected(self, peer, local):
        return self._check_connection(peer, local, require_focus=False)

    def focused(self, peer, local):
        return self._check_connection(peer, local, require_focus=True)

    def movement_input(self, peer, local):
        """A real left click in the game, including a short click between control ticks.

        The client also emits walk packets by itself after an attack; those packets alone
        are not evidence that the user took control. This reads input only, never simulates it.
        """
        now = time.monotonic()
        pressed = bool(self.ui.GetAsyncKeyState(0x01) & 0x8001)
        if not pressed and now-self.last_walk_input > self.WALK_INPUT_TTL:
            return False
        if not self.focused(peer, local):
            self.last_walk_input = -float('inf')
            return False
        if pressed:
            self.last_walk_input = now
        return now-self.last_walk_input <= self.WALK_INPUT_TTL

    def _check_connection(self, peer, local, require_focus):
        if self.panic() or peer is None or local is None:
            return False
        expected = self.owner(peer, local)
        current = C.c_uint32()
        self.ui.GetWindowThreadProcessId(self.ui.GetForegroundWindow(), C.byref(current))
        if expected is None or (require_focus and current.value != expected):
            return False
        if expected not in self.exe_cache:
            if len(self.exe_cache) > 64:
                self.exe_cache.clear()
            self.exe_cache[expected] = self.is_game(expected)
        return self.exe_cache[expected]

    def owner(self, peer, local):
        key, now = (tuple(peer), tuple(local)), time.monotonic()
        cached = self.owner_cache.get(key)
        if cached is not None and now-cached[1] < (self.PID_TTL if cached[0] is not None else self.MISS_TTL):
            return cached[0]
        pid = connection_pid(peer, local)
        if len(self.owner_cache) > 16:
            self.owner_cache.clear()
        self.owner_cache[key] = (pid, now)
        return pid

    @staticmethod
    def is_game(expected):
        kernel = C.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [C.c_uint32, C.c_int, C.c_uint32]
        kernel.OpenProcess.restype = C.c_void_p
        kernel.QueryFullProcessImageNameW.argtypes = [C.c_void_p, C.c_uint32, C.c_wchar_p, C.POINTER(C.c_uint32)]
        kernel.CloseHandle.argtypes = [C.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, expected)
        if not handle:
            return False
        try:
            path = C.create_unicode_buffer(32768)
            size = C.c_uint32(len(path))
            return bool(kernel.QueryFullProcessImageNameW(handle, 0, path, C.byref(size))) and PureWindowsPath(path.value).name.lower() == 'nro.exe'
        finally:
            kernel.CloseHandle(handle)
