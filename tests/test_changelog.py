import json
from datetime import datetime

from nrobot import changelog


def write(tmp_path, text):
    path = tmp_path/'CHANGELOG.md'
    path.write_text(text, encoding='utf-8')
    return path


SAMPLE = """# Changelog do BOT NRO

Intro.

## Próxima atualização

- RCX desenha a área da Nevasca
- Patrulha mais rápida

## 2026.11.05.3 (05/11/2026)

- Antigo
"""


def test_pending_items(tmp_path):
    path = write(tmp_path, SAMPLE)
    assert changelog.pending_items(path) == ['- RCX desenha a área da Nevasca', '- Patrulha mais rápida']


def test_stamp_moves_topics_under_the_version_and_keeps_history(tmp_path):
    path = write(tmp_path, SAMPLE)
    items = changelog.stamp('2026.11.06.1', path, now=datetime(2026, 11, 6))
    assert items == ['- RCX desenha a área da Nevasca', '- Patrulha mais rápida']
    text = path.read_text(encoding='utf-8')
    assert changelog.pending_items(path) == []
    assert text.index('## Próxima atualização') < text.index('## 2026.11.06.1 (06/11/2026)') < text.index('## 2026.11.05.3')
    assert '- Antigo' in text and text.count('RCX desenha') == 1


def test_empty_pending_section_changes_nothing(tmp_path):
    path = write(tmp_path, '# C\n\n## Próxima atualização\n\n## 1 (01/01/2026)\n\n- x\n')
    before = path.read_text(encoding='utf-8')
    assert changelog.stamp('2', path) == [] and path.read_text(encoding='utf-8') == before


def test_long_notes_are_split_for_discord_without_cutting_topics():
    items = [f'- topico {i} '+'x'*300 for i in range(20)]
    chunks = changelog.messages('2026.11.06.1', items)
    assert len(chunks) > 1 and all(len(c) <= 2000 for c in chunks)
    assert chunks[0].startswith('**BOT NRO: atualização 2026.11.06.1**')
    assert sum(c.count('- topico') for c in chunks) == 20


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b''


def test_send_posts_to_the_webhook_without_mentions(tmp_path):
    hook = tmp_path/'hook.txt'
    hook.write_text('https://discord.com/api/webhooks/1/abc\n', encoding='utf-8')
    sent = []
    def opener(request, timeout):
        sent.append((request.full_url, json.loads(request.data)))
        return Response()
    logs = []
    assert changelog.send('v1', ['- a', '- b'], logs.append, hook, opener)
    assert sent == [('https://discord.com/api/webhooks/1/abc',
                     {'content': '**BOT NRO: atualização v1**\n- a\n- b', 'allowed_mentions': {'parse': []}})]


def test_send_without_webhook_or_with_invalid_url_only_logs(tmp_path):
    logs = []
    def opener(*args, **kwargs):
        raise AssertionError('nao deveria enviar')
    assert not changelog.send('v1', ['- a'], logs.append, tmp_path/'missing.txt', opener)
    bad = tmp_path/'bad.txt'
    bad.write_text('https://example.com/x', encoding='utf-8')
    assert not changelog.send('v1', ['- a'], logs.append, bad, opener)
    assert all('não enviado' in line for line in logs)


def test_network_failure_does_not_raise(tmp_path):
    hook = tmp_path/'hook.txt'
    hook.write_text('https://discord.com/api/webhooks/1/abc', encoding='utf-8')
    def opener(*args, **kwargs):
        raise OSError('sem internet')
    logs = []
    assert not changelog.send('v1', ['- a'], logs.append, hook, opener)
    assert 'sem internet' in logs[-1]
