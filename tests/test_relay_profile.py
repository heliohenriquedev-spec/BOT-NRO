from pathlib import Path
import xml.etree.ElementTree as E

import pytest

from nrobot import relay_profile as module


XML = b'<clientinfo><servicetype>korea</servicetype><connection><display>NRO</display><address>187.77.36.200</address><port>6900</port><version>21</version></connection></clientinfo>'


def test_profile_preserves_original_connection():
    proposed = module.make_profile(XML)
    nodes = E.fromstring(proposed).findall('connection')
    assert len(nodes) == 2
    nodes[0].tail = None
    assert E.tostring(nodes[0]) == E.tostring(E.fromstring(XML).find('connection'))
    assert nodes[1].findtext('address') == '127.0.0.1'
    assert nodes[1].findtext('version') == '21'


def test_install_and_restore_both_preexisting_and_created_files(monkeypatch, tmp_path):
    game = tmp_path/'game'
    (game/'data').mkdir(parents=True)
    (game/'data/clientinfo.xml').write_bytes(XML)
    bot = tmp_path/'bot'
    monkeypatch.setattr(module, 'ROOT', bot)
    import nrobot.game_folder as game_folder
    monkeypatch.setattr(game_folder, 'require', lambda: game)
    (game/'DATA.INI').write_text('[Data]')
    monkeypatch.setattr(module, 'MANIFEST', bot/'perfis/relay/instalacao.json')
    class FakeGrf:
        def __init__(self, root):
            pass
        def read(self, name):
            assert name == 'data'+chr(92)+'sclientinfo.xml'
            return XML
    monkeypatch.setattr(module, 'GrfSet', FakeGrf)
    module.install()
    assert (game/'data/sclientinfo.xml').exists()
    module.restore()
    assert (game/'data/clientinfo.xml').read_bytes() == XML
    assert not (game/'data/sclientinfo.xml').exists()


def test_restore_does_not_overwrite_later_user_changes(monkeypatch, tmp_path):
    game = tmp_path/'game'
    (game/'data').mkdir(parents=True)
    for name in ('clientinfo.xml', 'sclientinfo.xml'):
        (game/'data'/name).write_bytes(XML)
    bot = tmp_path/'bot'
    monkeypatch.setattr(module, 'ROOT', bot)
    import nrobot.game_folder as game_folder
    monkeypatch.setattr(game_folder, 'require', lambda: game)
    (game/'DATA.INI').write_text('[Data]')
    monkeypatch.setattr(module, 'MANIFEST', bot/'perfis/relay/instalacao.json')
    monkeypatch.setattr(module, 'GrfSet', lambda root: None)
    module.install()
    (game/'data/clientinfo.xml').write_bytes(b'user change')
    with pytest.raises(ValueError, match='alterado'):
        module.restore()
