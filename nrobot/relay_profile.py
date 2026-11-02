"""Perfil local opcional, reversível; nunca modifica executáveis nem GRFs."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from .grf import GrfSet

ROOT = Path(__file__).resolve().parents[1]
GAME = Path(r'C:\NRO - Jogo COMPLETO')
MANIFEST = ROOT/'perfis/relay/instalacao.json'


def make_profile(original: bytes, port=16900):
    if not 1 <= port <= 65535:
        raise ValueError('Porta inválida')
    connection = re.search(rb'<connection\s*>.*?</connection>', original, re.S)
    if connection is None or original.count(b'</clientinfo>') != 1:
        raise ValueError('XML de conexão incompatível')
    local = connection.group()
    for tag, value in [(b'display', b'NRO - BOT LOCAL (TESTE)'), (b'address', b'127.0.0.1'), (b'port', str(port).encode())]:
        local, n = re.subn(b'<' + tag + b'>.*?</' + tag + b'>', b'<' + tag + b'>' + value + b'</' + tag + b'>', local, count=1, flags=re.S)
        if n != 1:
            raise ValueError('Campo de conexão ausente')
    return original.replace(b'</clientinfo>', b'\n'+local+b'\n</clientinfo>')


def install():
    if MANIFEST.exists() and not json.loads(MANIFEST.read_text())['restored']:
        raise ValueError('Perfil local já instalado; use o restaurador antes de reinstalar')
    backup = ROOT/'backups/relay'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup.mkdir(parents=True)
    grfs = GrfSet(str(GAME))
    records = []
    for filename in ('clientinfo.xml', 'sclientinfo.xml'):
        target = GAME/'data'/filename
        existed = target.exists()
        original = target.read_bytes() if existed else grfs.read('data'+chr(92)+filename)
        proposed = make_profile(original)
        source = backup/filename
        source.write_bytes(original)
        records.append({'target': str(target), 'original_existed': existed, 'backup': str(source),
                        'installed_hash': hashlib.sha256(proposed).hexdigest()})
    manifest = {'restored': False, 'files': records, 'display': 'NRO - BOT LOCAL (TESTE)', 'local_port': 16900}
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    # Persist rollback information before making the two reversible writes.
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    for record in records:
        target = Path(record['target'])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(make_profile(Path(record['backup']).read_bytes()))
    print('Perfil local instalado; a conexão original continua no arquivo. Reabra o jogo para verificar se a opção aparece.')


def restore():
    data = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if data['restored']:
        print('Perfil já restaurado.')
        return
    for record in data['files']:
        target = Path(record['target'])
        if target.resolve().parent != (GAME/'data').resolve() or target.name not in ('clientinfo.xml', 'sclientinfo.xml'):
            raise ValueError('Caminho de restauração inesperado')
        if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != record['installed_hash']:
            raise ValueError('O perfil foi alterado depois da instalação; não sobrescrevi suas mudanças')
    for record in data['files']:
        target = Path(record['target'])
        if record['original_existed']:
            target.write_bytes(Path(record['backup']).read_bytes())
        else:
            target.unlink()
    data['restored'] = True
    MANIFEST.write_text(json.dumps(data, indent=2), encoding='utf-8')
    print('Perfil original restaurado.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('install', 'restore'))
    args = parser.parse_args()
    (install if args.action == 'install' else restore)()


if __name__ == '__main__':
    main()
