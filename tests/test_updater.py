"""Atualizador pelo GitHub: troca só os arquivos do bot e preserva os do usuário."""
import io
import json
import zipfile

import pytest

from nrobot import updater


def bundle(files, version='2026.11.03.1', listed=None):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('BOT-NRO-main/versao.json', json.dumps({'version': version, 'files': listed or sorted(files)}))
        for name, content in files.items():
            archive.writestr('BOT-NRO-main/'+name, content)
    return data.getvalue()


def test_update_replaces_bot_files_removes_dropped_ones_and_keeps_user_files(tmp_path):
    (tmp_path/'nrobot').mkdir()
    (tmp_path/'nrobot/session_relay.py').write_text('old')
    (tmp_path/'nrobot/antigo.py').write_text('dropped in the new version')
    (tmp_path/'data/rede').mkdir(parents=True)
    (tmp_path/'data/rede/painel_config.json').write_text('{"mine": true}')
    (tmp_path/'logs').mkdir()
    (tmp_path/'logs/sessao.log').write_text('keep')
    (tmp_path/'requirements.txt').write_text('numpy')
    (tmp_path/'versao.json').write_text(json.dumps({'version': '2026.11.02.1',
                                                    'files': ['nrobot/session_relay.py', 'nrobot/antigo.py']}))
    files = {'nrobot/session_relay.py': 'new', 'nrobot/updater.py': 'u', 'requirements.txt': 'numpy',
             'data/rede/painel_config.json': '{"author": true}', 'tests/test_x.py': 'dev only', 'logs/x': 'no'}
    new = updater.apply(log=lambda text: None, root=tmp_path, archive=bundle(files))
    assert new['version'] == '2026.11.03.1'
    assert (tmp_path/'nrobot/session_relay.py').read_text() == 'new'
    assert (tmp_path/'nrobot/updater.py').read_text() == 'u'
    assert not (tmp_path/'nrobot/antigo.py').exists()
    assert (tmp_path/'data/rede/painel_config.json').read_text() == '{"mine": true}'
    assert (tmp_path/'logs/sessao.log').read_text() == 'keep' and not (tmp_path/'logs/x').exists()
    assert not (tmp_path/'tests').exists()
    assert json.loads((tmp_path/'versao.json').read_text())['version'] == '2026.11.03.1'


def test_broken_or_foreign_package_changes_nothing(tmp_path):
    (tmp_path/'arquivo.txt').write_text('intact')
    with pytest.raises(updater.UpdateError):
        updater.apply(log=lambda text: None, root=tmp_path, archive=b'not a zip')
    with pytest.raises(updater.UpdateError):
        updater.apply(log=lambda text: None, root=tmp_path, archive=bundle({'outro.py': 'x'}))
    assert sorted(p.name for p in tmp_path.iterdir()) == ['arquivo.txt']


def test_versions_increase_per_day_and_compare_numerically(monkeypatch):
    class Day:
        @staticmethod
        def now():
            from datetime import datetime
            return datetime(2026, 11, 3, 10)
    monkeypatch.setattr(updater, 'datetime', Day)
    assert updater.next_version('2026.11.02.4') == '2026.11.03.1'
    assert updater.next_version('2026.11.03.9') == '2026.11.03.10'
    assert updater.version_key('2026.11.03.10') > updater.version_key('2026.11.03.9')


def test_user_paths_are_protected():
    assert updater.is_protected('perfis/relay/instalacao.json')
    assert updater.is_protected('data/mapas/map_cache.dat')
    assert not updater.is_protected('data/rede/especies_nro.json')
    assert not updater.distributed('tools/validar_patrulha.py') and updater.distributed('nrobot/updater.py')
