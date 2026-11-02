"""REDE-22: limpeza independente da vida da janela, sem serviço permanente."""
from __future__ import annotations

import argparse
import ctypes as C
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from .etw_capture import active_session_file


def cleanup(filter_name, folder):
    """This Windows version removes ALL filters: only do so for our sole filter."""
    def command(*args):
        result = subprocess.run(['pktmon', *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        with (folder/'vigia-pktmon.log').open('ab') as log:
            log.write(result.stdout)
        if result.returncode:
            raise ValueError(f'PktMon falhou: {args}')
        return result.stdout.decode('oem', errors='replace')
    filters = command('filter', 'list')
    rows = re.findall(r'^[ \t]*\d+[ \t]+(\S+)[ \t]+(\S+)', filters, re.M)
    if not rows:
        return 'already_released'
    if rows != [(filter_name, 'TCP')]:
        raise ValueError('Filtros de terceiros ou mistos preservados')
    capture = active_session_file()
    if capture is not None:
        if capture and not Path(capture).resolve().is_relative_to(folder.resolve()):
            # Some real-time PktMon builds retain their default filename in the
            # session header. Accept it only with our matching ownership record.
            lease_path = folder/'vigia-dono.json'
            lease = json.loads(lease_path.read_text(encoding='utf-8')) if lease_path.exists() else {}
            default = Path(__file__).resolve().parents[1]/'PktMon.etl'
            if Path(capture).resolve() != default or lease.get('filter') != filter_name:
                raise ValueError('Arquivo da sessão pertence a outra captura; preservado')
        command('stop')
    command('filter', 'remove')
    return 'released'


def watch(owner, filter_name, folder):
    api = C.WinDLL('kernel32', use_last_error=True)
    api.OpenProcess.argtypes = [C.c_uint32, C.c_int, C.c_uint32]
    api.OpenProcess.restype = C.c_void_p
    api.WaitForSingleObject.argtypes = [C.c_void_p, C.c_uint32]
    api.WaitForSingleObject.restype = C.c_uint32
    api.CloseHandle.argtypes = [C.c_void_p]
    handle = api.OpenProcess(0x100000, False, owner)  # SYNCHRONIZE
    if not handle:
        raise C.WinError(C.get_last_error())
    (folder/'vigia-pronto').write_text(str(os.getpid()), encoding='ascii')
    try:
        while not (folder/'vigia-dispensado').exists():
            state = api.WaitForSingleObject(handle, 200)
            if state == 0:
                result = cleanup(filter_name, folder)
                (folder/'vigia-resultado.json').write_text(json.dumps({'state': result, 'owner': owner}), encoding='utf-8')
                return
            if state != 258:
                raise C.WinError(C.get_last_error())
    finally:
        api.CloseHandle(handle)


def start_guard(owner, filter_name, folder):
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    for marker in ('vigia-pronto', 'vigia-dispensado'):
        (folder/marker).unlink(missing_ok=True)
    (folder/'vigia-dono.json').write_text(json.dumps({'owner': owner, 'filter': filter_name, 'folder': str(folder)}), encoding='utf-8')
    with (folder/'vigia-erros.log').open('ab') as log:
        child = subprocess.Popen([sys.executable, '-m', 'nrobot.capture_guard', '--owner', str(owner),
            '--filter', filter_name, '--folder', str(folder)], cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True)
    until = time.monotonic()+5
    while time.monotonic() < until:
        if (folder/'vigia-pronto').exists():
            return child
        if child.poll() is not None:
            break
        time.sleep(0.05)
    raise RuntimeError('O vigia de encerramento não iniciou; captura não será iniciada')


def disarm(folder):
    (Path(folder)/'vigia-dispensado').write_text('normal cleanup', encoding='ascii')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--owner', type=int)
    parser.add_argument('--filter', required=True)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--spawn', action='store_true')
    parser.add_argument('--cleanup', action='store_true')
    args = parser.parse_args()
    if args.cleanup:
        print(cleanup(args.filter, args.folder))
    elif args.spawn:
        start_guard(args.owner, args.filter, args.folder)
    else:
        watch(args.owner, args.filter, args.folder)


if __name__ == '__main__':
    main()
