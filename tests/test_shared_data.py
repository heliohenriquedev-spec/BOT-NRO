"""Quests, boards, missions, map routes and portals published for every user."""
import json

from nrobot import shared_data


def write(root, relative, data):
    path = root/relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')


def read(root, relative):
    return json.loads((root/relative).read_text(encoding='utf-8'))


STEPS = [dict(kind='portal', map='town.gat', position=[1, 1]), dict(kind='wait_map', map='field.gat')]


def test_published_data_reaches_a_new_pc_once(tmp_path):
    dev, user = tmp_path/'dev', tmp_path/'user'
    write(dev, 'data/rede/rotas_mapas.json', [dict(id='m1', name='Campo', target_map='field.gat', steps=STEPS)])
    write(dev, 'data/rede/rotas_quests.json', [dict(id='q1', name='Quest A', map_route_id='m1', mission_ids=[])])
    write(dev, 'data/mapas/portais_internos.json', {'prt_sewb2': {'20,175': [60, 28]}})
    shared_data.export(log=lambda t: None, root=dev)
    (user/'data').mkdir(parents=True)
    import shutil
    shutil.copytree(dev/'data/compartilhado', user/'data/compartilhado')
    assert shared_data.merge(user, log=lambda t: None)
    assert [r['name'] for r in read(user, 'data/rede/rotas_quests.json')] == ['Quest A']
    assert read(user, 'data/mapas/portais_internos.json') == {'prt_sewb2': {'20,175': [60, 28]}}
    assert not shared_data.merge(user, log=lambda t: None)  # same publication: nothing to do


def test_published_entries_replace_their_copy_and_the_users_own_stay():
    mine = [dict(id='old', name='Campo', target_map='field.gat', steps=STEPS),
            dict(id='mine', name='Meu mapa', target_map='cave.gat', steps=STEPS)]
    theirs = [dict(id='m1', name='Campo novo', target_map='field.gat', steps=STEPS)]
    maps, renamed = shared_data.merge_map_routes(mine, theirs)
    assert [m['id'] for m in maps] == ['m1', 'mine'] and renamed == {'old': 'm1'}
    quests = shared_data.merge_quests([dict(id='u', name='Minha', map_route_id='old', mission_ids=['a']),
                                       dict(id='q1', name='Quest A', enabled=False)],
                                      [dict(id='q1', name='Quest A', enabled=True, kills=3)], {'a': 'A'}, renamed)
    assert quests[0]['map_route_id'] == 'm1' and quests[0]['mission_ids'] == ['A']
    assert quests[1]['kills'] == 3 and quests[1]['enabled'] is False  # the user's queue choice stays


def test_missions_recorded_by_the_user_follow_the_published_one_of_the_same_option():
    library, renamed = shared_data.merge_library(
        dict(missions=[dict(id='u1', board_id='kakashi', name='Rank D-1', menu_option='Rank D-1')], checked_missions=['u1']),
        dict(missions=[dict(id='p1', board_id='kakashi', name='Rank D-1', menu_option='Rank D-1', rank='D-1')],
             menus={'kakashi': [['Rank D-1']]}))
    assert [m['id'] for m in library['missions']] == ['p1'] and renamed == {'u1': 'p1'}
    assert library['menus'] == {'kakashi': [['Rank D-1']]} and library['checked_missions'] == ['u1']


def test_portal_margins_keep_the_smallest_learned():
    assert shared_data.merge_portals({'a': {'1,1': 3}}, {'a': {'1,1': 1, '2,2': 2}}, smallest=True) == {'a': {'1,1': 1, '2,2': 2}}


def test_voltar_and_gm_signs_go_but_no_personal_setting(tmp_path):
    """Updates carry what the routes need; skills, hunt, combat and the Switch stay on each PC."""
    dev, user = tmp_path/'dev', tmp_path/'user'
    write(dev, 'data/rede/quest_extras.json', dict(voltar_frame='f300', voltar_enabled=True, voltar_name='Dev',
                                                  clear_radius=6, characters={'Dev': dict(mount_item=2642)}, mount=dict(item_id=1)))
    write(dev, 'data/rede/buffs_aprendidos.json', {'29': 12})
    write(dev, 'data/rede/painel_config.json', {'species': [1051], 'radius': 5})
    write(dev, 'data/jogadores/gm_sinais.json', {'visuais': [7], 'marcas': []})
    shared_data.export(log=lambda t: None, root=dev)
    published = {path.name for path in (dev/'data/compartilhado').iterdir()}
    assert 'buffs_aprendidos.json' not in published and 'alvos_monstros.json' not in published
    assert read(dev, 'data/compartilhado/quest_extras.json') == {'voltar_frame': 'f300', 'voltar_enabled': True}
    import shutil
    shutil.copytree(dev/'data/compartilhado', user/'data/compartilhado')
    write(user, 'data/rede/buffs_aprendidos.json', {'8': 1})
    write(user, 'data/jogadores/gm_sinais.json', {'visuais': [3], 'marcas': ['x']})
    assert shared_data.merge(user, log=lambda t: None)
    extras = read(user, 'data/rede/quest_extras.json')
    assert extras['voltar_frame'] == 'f300' and 'clear_radius' not in extras and 'characters' not in extras
    assert read(user, 'data/rede/buffs_aprendidos.json') == {'8': 1}  # untouched
    assert read(user, 'data/jogadores/gm_sinais.json') == {'visuais': [3, 7], 'marcas': ['x']}


def test_a_voltar_learned_on_this_pc_is_kept():
    mine = dict(voltar_frame='mine', voltar_enabled=False, clear_radius=9)
    assert shared_data.merge_extras(mine, dict(voltar_frame='dev', clear_radius=6)) == mine


def test_files_from_github_with_other_line_endings_are_still_imported(tmp_path):
    """The manifest held the hash of this PC's CRLF bytes; GitHub delivers LF: every import was
    refused as altered and the other PCs had no quests at all."""
    import hashlib
    import json
    from nrobot import shared_data
    folder = tmp_path/'data/compartilhado'
    folder.mkdir(parents=True)
    data = b'{\r\n "missions": [],\r\n "boards": []\r\n}'
    (folder/'quadros_missoes.json').write_bytes(data.replace(b'\r\n', b'\n'))  # as GitHub delivers
    (folder/'manifesto.json').write_text(json.dumps({'schema': 1, 'files': {
        'quadros_missoes.json': hashlib.sha256(data).hexdigest()}}), encoding='utf-8')  # old CRLF hash
    messages = []
    shared_data.merge(tmp_path, log=messages.append)
    assert not any('alterado' in m for m in messages), messages
    assert shared_data.matches(data, shared_data.content_hash(data.replace(b'\r\n', b'\n')))


def test_shared_files_are_written_with_lf(tmp_path):
    from nrobot import shared_data
    shared_data._write(tmp_path/'x.json', {'a': [1, 2]})
    assert b'\r\n' not in (tmp_path/'x.json').read_bytes()
