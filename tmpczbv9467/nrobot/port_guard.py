"""Porta local do bot ocupada: encerra um relay antigo do bot ou diz qual programa a usa."""
from __future__ import annotations

import os
import re
import subprocess

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def run(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                timeout=15, creationflags=NO_WINDOW)
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def listening_pids(port, netstat=None):
    """PIDs listening on 127.0.0.1/0.0.0.0:port (works on any Windows language)."""
    text = netstat if netstat is not None else run(['netstat', '-ano', '-p', 'tcp'])
    pids = set()
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[0].upper() == 'TCP' and re.search(rf'[:.]{port}$', fields[1]) \
                and fields[2] in ('0.0.0.0:0', '[::]:0', '*:*') and fields[-1].isdigit():
            pids.add(int(fields[-1]))
    pids.discard(0)
    return pids


def command_line(pid):
    text = run(['powershell', '-NoProfile', '-Command',
                f'(Get-CimInstance Win32_Process -Filter "ProcessId={pid}").CommandLine'])
    return text.strip()


def is_bot_relay(command):
    return 'nrobot.session_relay' in command


def free(port):
    """(freed, message). Ends old bot relays holding the port; never touches other programs."""
    if os.name != 'nt':
        return False, f'porta {port} ocupada'
    pids = listening_pids(port)
    if not pids:
        return True, ''
    others = []
    for pid in pids:
        command = 'este mesmo processo' if pid == os.getpid() else command_line(pid)
        if pid != os.getpid() and is_bot_relay(command):
            run(['taskkill', '/PID', str(pid), '/T', '/F'])
        else:
            others.append(f'PID {pid}: {command or "programa desconhecido"}')
    if others:
        return False, (f'a porta {port} está sendo usada por outro programa ({"; ".join(others)}). '
                       'Feche esse programa e abra a conexão de novo.')
    return True, f'uma conexão antiga do bot ainda estava aberta na porta {port} e foi encerrada'
