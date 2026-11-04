import json

import pytest

from nrobot import ammo, shared_data
from nrobot.grf import GrfError, GrfSet, data_ini_grfs
from test_grf_versions import make_grf


@pytest.mark.parametrize('encoding', ['utf-8-sig', 'utf-16', 'cp1252'])
def test_ini_preserves_custom_accented_grf_filename(tmp_path, encoding):
    name = 'Mapa limpo edição.grf'
    make_grf(tmp_path/name, {'data\\mapa.gat': b'GAT'})
    ini = tmp_path/'DATA.INI'
    ini.write_bytes(('[Data]\n0='+name+'\n1=ausente.grf').encode(encoding))
    assert data_ini_grfs(str(ini))[0] == name
    grfs = GrfSet(str(tmp_path))
    assert grfs.read('data\\mapa.gat') == b'GAT'
    assert any('ausente.grf' in row for row in grfs.skipped)


def test_ammo_works_without_private_extracted_grfs(tmp_path, monkeypatch):
    catalog = tmp_path/'municao.json'
    catalog.write_text(json.dumps({'1': 'Kunai', '2': 'Shuriken'}))
    monkeypatch.setattr(ammo, 'CATALOG', catalog)
    class Resources:
        entries = {'data\\idnum2itemdisplaynametable.txt': 'custom'}
        alternates = {'data\\idnum2itemdisplaynametable.txt': ['base']}
        def read_entry(self, entry):
            if entry == 'custom':
                raise GrfError('tabela ilegivel')
            return b'2#Shuriken_de_ferro#3#Kunai_de_fogo#'
    names = ammo.names_from_grfs(Resources())
    inventory = ammo.AmmoInventory(names)
    assert inventory.kind({'type': 10, 'item_id': 1}) == 524
    assert inventory.kind({'type': 10, 'item_id': 2}) == 523
    assert inventory.kind({'type': 0, 'item_id': 1}) is None
    assert ammo.names_from_grfs(Resources(), bundled=False) == {2: 'Shuriken de ferro', 3: 'Kunai de fogo'}


def test_publish_rejects_quest_with_missing_dependencies_before_writing(tmp_path):
    path = tmp_path/'data/rede/rotas_quests.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps([{'name': 'Quest', 'mission_ids': ['missing']}]))
    with pytest.raises(ValueError, match='missoes nao incluidas'):
        shared_data.export(root=tmp_path)
    assert not (tmp_path/shared_data.SHARED).exists()


def test_manifest_detects_incomplete_download_without_overwriting_user(tmp_path):
    shared_data._write(tmp_path/'data/rede/buffs_aprendidos.json', {'29': 160})
    shared_data.export(root=tmp_path, log=lambda _: None)
    (tmp_path/shared_data.MARKER).unlink()
    (tmp_path/shared_data.SHARED/'buffs_aprendidos.json').write_text('{}')
    assert not shared_data.merge(root=tmp_path, log=lambda _: None)
    assert json.loads((tmp_path/'data/rede/buffs_aprendidos.json').read_text()) == {'29': 160}


def test_explicit_monster_type_does_not_wait_for_client_hover_requests():
    from nrobot.map_monsters import is_confirmed_monster
    monster = dict(entity_id=111411301, species_id=1139, object_type_raw=5)
    assert is_confirmed_monster(monster)
    assert not is_confirmed_monster(dict(monster, entity_id=2003143))
    assert not is_confirmed_monster(dict(monster, owner_id=2003143))
    assert not is_confirmed_monster(dict(monster, summoned=True))
    assert not is_confirmed_monster(dict(monster, species_id=111))
    assert not is_confirmed_monster(dict(monster, object_type_raw=0))


def test_quest_maps_are_checked_without_developer_game_or_private_cache(tmp_path):
    import base64
    import zlib
    from nrobot.release_assets import validate_quest_maps
    shared_data._write(tmp_path/'data/compartilhado/rotas_mapas.json',
                       [{'target_map': 'field.gat', 'steps': [{'map': 'town.gat'}]}])
    cells = base64.b64encode(zlib.compress(bytes([1])*4)).decode()
    shared_data._write(tmp_path/'data/recursos/colisoes.json', {'town': [2, 2, cells]})
    with pytest.raises(ValueError, match='field'):
        validate_quest_maps(tmp_path)
    shared_data._write(tmp_path/'data/recursos/colisoes.json', {'town': [2, 2, cells], 'field': [2, 2, cells]})
    assert validate_quest_maps(tmp_path) == 2


def test_runtime_ignores_visual_grfs_and_loose_gat_even_when_valid(tmp_path, monkeypatch):
    import base64
    import zlib
    from nrobot import map_navigation
    bundle = tmp_path/'colisoes.json'
    cells = bytes([1, 1, 1, 1, 0, 1, 1, 1, 1])
    shared_data._write(bundle, {'field': [3, 3, base64.b64encode(zlib.compress(cells)).decode()]})
    monkeypatch.setattr(map_navigation, 'BUNDLED_MAPS', bundle)
    def forbidden(*a, **kw):
        raise AssertionError('runtime must not open DATA.INI or GRFs')
    monkeypatch.setattr(map_navigation, 'GrfSet', forbidden)
    for ini in ('[Data]\n0=custom.grf', 'invalid INI'):
        (tmp_path/'DATA.INI').write_text(ini)
        repo = map_navigation.MapRepository(tmp_path, cache_folder=tmp_path/'empty', independent=True)
        assert repo.get('field.gat').walkable((1, 1))
        assert repo.grfs is None
        assert repo.get('unknown.gat') is None
        assert 'base do bot' in repo.errors['unknown.gat']


def test_runtime_ammo_does_not_depend_on_grf_names(tmp_path, monkeypatch):
    catalog = tmp_path/'municao.json'
    catalog.write_text('{"1":"Kunai", "2":"Shuriken"}')
    monkeypatch.setattr(ammo, 'CATALOG', catalog)
    assert ammo.names_from_catalog() == {1: 'Kunai', 2: 'Shuriken'}
    catalog.write_text('{}')
    with pytest.raises(ValueError, match='vazio'):
        ammo.names_from_catalog()


def test_publish_preserves_combat_resources_without_reading_visual_grfs(tmp_path, monkeypatch):
    import base64
    import zlib
    from nrobot import release_assets
    folder = tmp_path/'data/recursos'
    folder.mkdir(parents=True)
    (folder/'municao.json').write_text('{"1":"Kunai"}')
    shared_data._write(folder/'colisoes.json', {'field': [2, 2, base64.b64encode(zlib.compress(bytes(4))).decode()]})
    monkeypatch.setattr(ammo, 'CATALOG', folder/'municao.json')
    monkeypatch.setattr(release_assets, 'ROOT', tmp_path)
    def forbidden(*a, **kw):
        raise AssertionError('publish must preserve the operational base')
    monkeypatch.setattr(release_assets, 'MapRepository', forbidden)
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    release_assets.prepare(log=lambda _: None)
    assert before == {p.name: p.read_bytes() for p in folder.iterdir()}
