"""Window-bound input for recognized login screens; no real credentials are typed."""
import ctypes
from ctypes import wintypes
import time


class _Mouse(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('data', wintypes.DWORD),
                ('flags', wintypes.DWORD), ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]


class _Key(ctypes.Structure):
    _fields_ = [('vk', wintypes.WORD), ('scan', wintypes.WORD), ('flags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]


class _Union(ctypes.Union):
    _fields_ = [('mouse', _Mouse), ('key', _Key)]


class _Input(ctypes.Structure):
    _anonymous_ = ('value',)
    _fields_ = [('type', wintypes.DWORD), ('value', _Union)]


class GameLoginWindow:
    def __init__(self, cancelled):
        self.cancelled = cancelled
        self.hwnd = None
        self.origin = None

    def capture(self):
        from .radar_overlay import find_game_window
        from .screen_capture import grab
        user = ctypes.windll.user32
        hwnd = find_game_window()
        if not hwnd or user.GetForegroundWindow() != hwnd or user.IsIconic(hwnd):
            return None
        rect, point = wintypes.RECT(), wintypes.POINT(0, 0)
        if not user.GetClientRect(hwnd, ctypes.byref(rect)) or not user.ClientToScreen(hwnd, ctypes.byref(point)):
            return None
        if rect.right < 280 or rect.bottom < 200:
            return None
        self.hwnd, self.origin = hwnd, (point.x, point.y)
        return grab(point.x, point.y, rect.right, rect.bottom)

    def guard(self):
        if self.cancelled() or not self.hwnd or ctypes.windll.user32.GetForegroundWindow() != self.hwnd:
            raise InterruptedError('Login suspenso: pausa ou foco fora da janela do jogo')

    def send(self, item):
        self.guard()
        if ctypes.windll.user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(item)) != 1:
            raise OSError('Windows nao aceitou a entrada na janela do jogo')

    def click(self, x, y):
        self.guard()
        if not ctypes.windll.user32.SetCursorPos(self.origin[0]+int(x), self.origin[1]+int(y)):
            raise OSError('Windows nao posicionou o cursor; nenhuma confirmacao enviada')
        self.send(_Input(type=0, mouse=_Mouse(flags=2)))
        # Always release even if pause is pressed between down and up.
        ctypes.windll.user32.SendInput(1, ctypes.byref(_Input(type=0, mouse=_Mouse(flags=4))), ctypes.sizeof(_Input))
        time.sleep(.04)

    def key(self, vk, up=False):
        item = _Input(type=1, key=_Key(vk=vk, scan=ctypes.windll.user32.MapVirtualKeyW(vk, 0), flags=2 if up else 0))
        if up:
            ctypes.windll.user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(item))
        else:
            self.send(item)

    def placeholder(self):
        from .auto_login import BOOTSTRAP_USER
        self.key(0x11)
        try:
            self.key(0x41); self.key(0x41, True)
        finally:
            self.key(0x11, True)
        for char in BOOTSTRAP_USER:
            self.key(ord(char.upper())); self.key(ord(char.upper()), True)
            time.sleep(.015)

    def apply(self, action, dialog, button, verify):
        """Recheck the screen between operations; never select/delete a character by pixels."""
        if not verify():
            raise InterruptedError('Tela de login mudou antes da acao')
        s, x, y = dialog.scale, dialog.x, dialog.y
        if action['kind'] == 'authenticate':
            for field_y in (39, 70):
                if not verify():
                    raise InterruptedError('Tela de login mudou; preenchimento ficticio interrompido')
                self.click(x+150*s, y+field_y*s)
                self.placeholder()
        elif action['kind'] in ('connection', 'world'):
            self.click(x+30*s, y+(28+16*action['row'])*s)
        if not verify():
            raise InterruptedError('Tela de login mudou antes da confirmacao')
        self.click(button.x+21*s, button.y+10*s)
