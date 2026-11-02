"""Pasta do jogo: encontrada sozinha (jogo aberto, lugares comuns) ou escolhida pelo usuário.

A escolha fica em perfis/jogo.json, que é de cada PC: nunca vai para o GitHub e o
atualizador não a troca.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import string

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT/'perfis'/'jogo.json'
DEFAULT = Path(r'C:\NRO - Jogo COMPLETO')
NAME_HINTS = ('nro', 'naruto')


def is_game_dir(path) -> bool:
    path = Path(path)
    return (path/'DATA.INI').is_file() and any(path.glob('*.grf'))


def saved():
    try:
        folder = Path(json.loads(SETTINGS.read_text(encoding='utf-8'))['game_dir'])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return folder if is_game_dir(folder) else None


def save(folder):
    folder = Path(folder)
    if not is_game_dir(folder):
        raise ValueError(f'{folder} não é a pasta do jogo (falta DATA.INI ou os arquivos .grf)')
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps({'game_dir': str(folder)}, ensure_ascii=False, indent=1), encoding='utf-8')
    return folder


def running_game():
    """Folder of the game client that is open right now, if any."""
    if os.name != 'nt':
        return None
    try:
        import ctypes
        from ctypes import wintypes
        from .radar_overlay import find_game_window
        hwnd = find_game_window()
        if hwnd is None:
            return None
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return None
        try:
            size, buffer = wintypes.DWORD(1024), ctypes.create_unicode_buffer(1024)
            if not ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return None
            return Path(buffer.value).parent
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except (OSError, AttributeError, ValueError):
        return None


def candidates():
    """Common install places: drive roots, Desktop, Downloads, Documents, Program Files."""
    yield DEFAULT
    home = Path.home()
    bases = [home/'Desktop', home/'OneDrive'/'Desktop', home/'OneDrive'/'Área de Trabalho', home/'Downloads',
             home/'Documents', home/'OneDrive'/'Documentos']
    for letter in string.ascii_uppercase:
        drive = Path(f'{letter}:\\')
        if drive.exists():
            bases += [drive, drive/'Games', drive/'Jogos', drive/'Program Files', drive/'Program Files (x86)']
    seen = set()
    for base in bases:
        try:
            children = [child for child in base.iterdir() if child.is_dir()]
        except OSError:
            continue
        for child in children:
            if any(hint in child.name.lower() for hint in NAME_HINTS):
                for folder in (child, *(sub for sub in _subfolders(child))):
                    if folder not in seen:
                        seen.add(folder)
                        yield folder


def _subfolders(folder):
    try:
        return [sub for sub in folder.iterdir() if sub.is_dir()]
    except OSError:
        return []


def find():
    """The game folder without asking, or None."""
    folder = saved()
    if folder is not None:
        return folder
    for folder in (running_game(), *candidates()):
        if folder is not None and is_game_dir(folder):
            return save(folder)
    return None


def ask_console():
    """Folder chooser for the .bat installers (no Qt needed)."""
    print('Não encontrei a pasta do jogo sozinho. Escolha a pasta onde está o NRO (a que tem DATA.INI).')
    try:
        import tkinter
        from tkinter import filedialog
        window = tkinter.Tk()
        window.withdraw()
        window.attributes('-topmost', True)
        chosen = filedialog.askdirectory(title='Escolha a pasta do jogo NRO (a que tem DATA.INI)')
        window.destroy()
    except Exception:  # no Tk: fall back to typing the path
        chosen = input('Caminho da pasta do jogo: ').strip().strip('"')
    if not chosen:
        raise SystemExit('Nenhuma pasta escolhida.')
    return save(chosen)


def require(ask=ask_console):
    folder = find()
    return folder if folder is not None else ask()


if __name__ == '__main__':
    print(f'Pasta do jogo: {require()}')
