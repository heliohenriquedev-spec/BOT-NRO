"""Release notes: topics collected in CHANGELOG.md, stamped and announced when publishing.

Changes are written under "## Próxima atualização" while they are made. Publishing turns that
section into "## <version> (<date>)" and posts it to a Discord channel through a webhook whose
URL lives only on the developer's PC (perfis/ is never published).
"""
from datetime import datetime
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT/'CHANGELOG.md'
WEBHOOK_FILE = ROOT/'perfis'/'desenvolvedor'/'discord_webhook.txt'
PENDING = '## Próxima atualização'
HEADER = ('# Changelog do BOT NRO\n\n'
          'Novidades de cada atualização. O que ainda não foi publicado fica em "Próxima atualização".\n')
WEBHOOK_PREFIXES = ('https://discord.com/api/webhooks/', 'https://discordapp.com/api/webhooks/',
                    'https://ptb.discord.com/api/webhooks/', 'https://canary.discord.com/api/webhooks/')
LIMIT = 1900  # Discord rejects messages over 2000 characters


def read(path=None):
    path = path or CHANGELOG
    try:
        return path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return HEADER+'\n'+PENDING+'\n'


def split(text):
    """(before, pending lines, after) around the pending section."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == PENDING)
    except StopIteration:
        return lines, [], []
    end = next((i for i in range(start+1, len(lines)) if lines[i].startswith('## ')), len(lines))
    return lines[:start], lines[start+1:end], lines[end:]


def pending_items(path=None):
    _, body, _ = split(read(path))
    while body and not body[-1].strip():
        body.pop()
    while body and not body[0].strip():
        body.pop(0)
    return body


def stamp(version, path=None, now=None):
    """Move the pending topics under the version heading; returns them (empty: nothing changes)."""
    path = path or CHANGELOG
    text = read(path)
    items = pending_items(path)
    if not items:
        return []
    before, _, after = split(text)
    while before and not before[-1].strip():
        before.pop()
    date = (now or datetime.now()).strftime('%d/%m/%Y')
    lines = before+['', PENDING, '', f'## {version} ({date})', '', *items, '']
    if after:
        lines += after
    path.write_text('\n'.join(lines).rstrip()+'\n', encoding='utf-8')
    return items


def messages(version, items):
    """Discord-sized chunks; a topic is never cut in the middle unless it alone is too long."""
    chunks, current = [], f'**BOT NRO: atualização {version}**'
    for line in items:
        while len(line) > LIMIT:
            chunks.append(current)
            current, line = line[:LIMIT], line[LIMIT:]
        if len(current)+1+len(line) > LIMIT:
            chunks.append(current)
            current = line
        else:
            current += '\n'+line
    chunks.append(current)
    return [chunk for chunk in chunks if chunk.strip()]


def webhook_url(path=None):
    path = path or WEBHOOK_FILE
    try:
        url = path.read_text(encoding='utf-8-sig').strip()  # Notepad may add a BOM
    except FileNotFoundError:
        return None
    return url if url.startswith(WEBHOOK_PREFIXES) else None


def send(version, items, log=print, path=None, opener=urllib.request.urlopen):
    """Post the release notes; failures are reported but never undo a publication."""
    if not items:
        log('Changelog vazio; nada enviado ao Discord.')
        return False
    url = webhook_url(path)
    if not url:
        log(f'Changelog não enviado: crie {WEBHOOK_FILE.relative_to(ROOT)} com a URL do webhook do canal.')
        return False
    try:
        for content in messages(version, items):
            data = json.dumps({'content': content, 'allowed_mentions': {'parse': []}}).encode('utf-8')
            request = urllib.request.Request(url, data=data, method='POST', headers={
                'Content-Type': 'application/json', 'User-Agent': 'BOT-NRO-changelog'})
            with opener(request, timeout=20) as response:
                response.read()
    except OSError as exc:
        log(f'Publicado, mas o changelog não chegou ao Discord: {exc}')
        return False
    log('Changelog enviado ao Discord.')
    return True
