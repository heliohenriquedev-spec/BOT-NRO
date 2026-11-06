"""Per-monster counters: finished monsters keep being hunted; the route leaves only when all are done."""
import pytest
from nrobot import quest_library as lib
from nrobot.quest_routes import QuestRoutes, validate_routes


def route(**extra):
    return {**dict(name='Q',id='Q',enabled=True,kills=1,species=[],target_map='field',
                   steps=[dict(kind='walk',map='field',position=[5,5])]),**extra}


def kill(q,identity,species,t):
    q.observe([dict(kind='appearance',entity_id=identity,species_id=species,position=[5,6]),
               dict(kind='skill_damage',source_id=1,target_id=identity,damage_raw=10),
               dict(kind='remove',entity_id=identity,reason=1)],1,'field',t)


def test_counts_each_monster_and_finishes_only_when_all_are_done():
    q=QuestRoutes()
    q.start([route(kill_targets=[dict(name='Gorila',count=2,species=[10]),dict(name='Louva-a-Deus',count=1,species=[11])])],0)
    assert sorted(q.route['species'])==[10,11]  # both hunted from the start
    q.phase='hunt'
    for i in range(3):kill(q,100+i,10,i)  # Gorila past its goal: still counted as hunted, no finish
    assert [(p['name'],p['done'],p['complete']) for p in q.progress()]==[('Gorila',2,True),('Louva-a-Deus',0,False)]
    assert not q.hunt_complete() and 10 in q.route['species']
    kill(q,200,11,5)
    assert q.hunt_complete()
    assert q.snapshot()['kill_progress'][1]==dict(name='Louva-a-Deus',count=1,done=1,complete=True)


def test_kill_by_someone_else_or_leaving_view_does_not_count():
    q=QuestRoutes();q.start([route(kill_targets=[dict(name='Gorila',count=1,species=[10])])],0);q.phase='hunt'
    q.observe([dict(kind='appearance',entity_id=5,species_id=10,position=[5,6]),dict(kind='remove',entity_id=5,reason=1)],1,'field',1)
    q.observe([dict(kind='appearance',entity_id=6,species_id=10,position=[5,6]),
               dict(kind='skill_damage',source_id=1,target_id=6,damage_raw=10),dict(kind='remove',entity_id=6,reason=0)],1,'field',2)
    assert not q.hunt_complete()


def test_without_counter_the_total_still_works():
    q=QuestRoutes();q.start([route(kills=2,species=[10])],0);q.phase='hunt'
    kill(q,1,10,1);assert not q.hunt_complete()
    kill(q,2,10,2);assert q.hunt_complete() and q.progress()[0]['name']=='Total'


def test_counter_from_missions_uses_largest_amount_per_monster(monkeypatch):
    import nrobot.monster_db as db
    monkeypatch.setattr(db,'all_monsters',lambda:[dict(species_id=10,name='Gorila'),dict(species_id=11,name='Louva-a-Deus')])
    data=lib.validate(dict(missions=[
        dict(id='a',name='Rank A-1',board_id='vip',description='Monstros necessários : 50 Gorila'),
        dict(id='b',name='Rank S-11',board_id='vip',description='Monstros necessários : 30 Gorila, 20 Louva-a-Deus'),
        dict(id='c',name='Rank A-4',board_id='vip',description='Monstros necessários : 50 Abelha Macho')]))
    assert lib.kill_targets(data,['a','b'])==[dict(name='Gorila',count=50,species=[10]),dict(name='Louva-a-Deus',count=20,species=[11])]
    with pytest.raises(ValueError,match='Abelha Macho'):lib.kill_targets(data,['c'])
    data['missions'][2]['monster_ids']=[1004]  # linked by hand in Configurar rank e monstros
    assert lib.kill_targets(data,['c'])==[dict(name='Abelha Macho',count=50,species=[1004])]


def test_invalid_counter_is_rejected():
    with pytest.raises(ValueError,match='Contador'):validate_routes([route(kill_targets=[dict(name='Gorila',count=0,species=[10])])])


SHARED = {1201: {'species_id': 1201, 'name': 'Abelha Macho',
                 'names_by_map': {'um_dun02': ['Abelha Macho'], 'prt_sewb4': ['Shinobi Ladrão']}}}


def test_kills_of_the_other_monster_with_the_same_sprite_do_not_count():
    q = QuestRoutes()
    q.start([route(kill_targets=[dict(name='Shinobi Ladrão', count=5, species=[1201])])], 0); q.phase = 'hunt'
    for identity, name in ((1, 'Abelha Macho'), (2, 'Shinobi Ladrão'), (3, None)):
        q.observe([dict(kind='appearance', entity_id=identity, species_id=1201, position=[5, 6])]
                  +([dict(kind='name', entity_id=identity, name=name)] if name else [])
                  +[dict(kind='skill_damage', source_id=1, target_id=identity, damage_raw=10), dict(kind='remove', entity_id=identity, reason=1)],
                  1, 'field', identity)
    assert q.kills == 2 and q.progress()[0]['done'] == 2  # the Abelha Macho is not a Shinobi Ladrão


def test_quest_hunt_attacks_only_the_names_asked(tmp_path, monkeypatch):
    import nrobot.monster_db as db
    from nrobot.session_relay import SessionRelay
    monkeypatch.setattr(db, 'load_captured', lambda: {1201: {'species_id': 1201, 'names_by_map': {'mix': ['Abelha Macho', 'Shinobi Ladrão']}}})
    monkeypatch.setattr(db, 'load_base', lambda: {})
    r = SessionRelay('127.0.0.1', folder=tmp_path)
    q = r.quests; q.routes = [route(target_map='mix', kill_targets=[dict(name='Shinobi Ladrão', count=5, species=[1201])])]; q.index = 0
    assert r.quest_name_choices(q) == {'mix:1201:Abelha Macho': False, 'mix:1201:Shinobi Ladrão': True}
