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
    write(dev, 'data/rede/rotas_quests.json', [dict(id='q1', name='Quest A', map_route_id='m1', mission_ids=['x'])])
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
