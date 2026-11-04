"""REDE-71/76: locating the game window for the overlays (minimap, own shadow)."""
import ctypes
import os
from ctypes import wintypes

GAME_TITLE = 'Naruto Redemption Online'
GAME_EXECUTABLE = 'nro.exe'


_window = None


def game_window():
    """The game window, found once and kept while it exists (searching every window is slow)."""
    global _window
    if os.name != 'nt':
        return None
    if _window is not None and ctypes.windll.user32.IsWindow(_window):
        return _window
    _window = find_game_window()
    return _window


def game_in_front():
    """The game is the active window and not minimized: the overlays show only then (they hide
    with it on Alt+Tab or minimize)."""
    hwnd = game_window()
    if hwnd is None:
        return False
    user32 = ctypes.windll.user32
    return not user32.IsIconic(hwnd) and user32.GetForegroundWindow() == hwnd


def game_client_rect():
    """(x, y, width, height) of the game's client area in physical pixels, or None."""
    hwnd = game_window()
    if hwnd is None or ctypes.windll.user32.IsIconic(hwnd):
        return None
    rect = wintypes.RECT()
    ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = wintypes.POINT(0, 0)
    ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(origin))
    return origin.x, origin.y, rect.right, rect.bottom


def bring_game_to_front():
    """Restore and focus the game window (allowed: the panel is the foreground window)."""
    hwnd = find_game_window()
    if hwnd is None:
        return False
    user32 = ctypes.windll.user32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    return True


def find_game_window():
    if os.name != 'nt':
        return None
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    found = []

    def executable(hwnd):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ''
        try:
            size = wintypes.DWORD(260)
            buffer = ctypes.create_unicode_buffer(260)
            kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
            return os.path.basename(buffer.value).lower()
        finally:
            kernel32.CloseHandle(handle)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(length+1)
            user32.GetWindowTextW(hwnd, title, length+1)
            if title.value.startswith(GAME_TITLE) or executable(hwnd) == GAME_EXECUTABLE:
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else None
