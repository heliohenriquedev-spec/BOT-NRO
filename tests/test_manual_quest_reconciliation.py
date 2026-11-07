import struct

import pytest

from nrobot.quest_routes import QuestRoutes
from nrobot import quest_daily, quest_progress
from test_quest_recording_slots_regressions import recipes
from test_bg_entry import relay


@pytest.fixture
def setup_queue(tmp_path,monkeypatch):
    monkeypatch.setattr(quest_daily,'FILE',tmp_path/'daily.json')
    monkeypatch.setattr(quest_daily,'SLOTS',tmp_path/'slots.json')
    monkeypatch.setattr(quest_daily,'CHARACTER','Teste')
    library=recipes()
    for m in library['missions']:
        if m['id']=='D4':m.update(monster_targets=[dict(name='Ninkame',count=50)],monster_ids=[1315])
        if m['id']=='D5':m.update(monster_targets=[dict(name='Girino',count=50)],monster_ids=[1034])
    routes=[dict(id='R',name='Rota',enabled=True,mission_ids=['D4','D5'],target_map='field',species=[1315,1034],kills=50,
                 steps=[dict(kind='portal',map='ra_in01',position=[2,2]),dict(kind='wait_map',map='field')])]
    q=QuestRoutes();q.start(routes,0,library=library)
    q.phase='hunt';q.last_stage=('hunt',0);q.completed_missions['pickup']=['D4','D5']
    q.kill_counts={1315:45,1034:7};q.kills=52
    q.actors[90]=dict(position=[219,95],name='Quadro')
    q.stop('Manual');q.map='ra_in01'
    return q,routes,library


def open_board(q):q.native(0x90,struct.pack('<HIB',0x90,90,1),'ra_in01')


def menu(q,options):q.observe([dict(kind='npc_dialog',entity_id=90,action='menu',options=options)],1,'ra_in01',1)


def select(q,choice):q.native(0xb8,struct.pack('<HIB',0xb8,90,choice),'ra_in01')


def say(q,text):q.observe([dict(kind='npc_dialog',entity_id=90,action='text',text=text)],1,'ra_in01',2)


def choose_delivery(q):
    open_board(q);menu(q,['#1 Rank D-4','#2 Rank D-5']);select(q,1)
    menu(q,['Completar missao']);select(q,1)


def test_manual_delivery_requires_confirmation_and_survives_resume(setup_queue,tmp_path):
    q,routes,library=setup_queue
    choose_delivery(q)
    say(q,'Voce precisa matar todos os monstros da lista')
    assert not q.completed_missions['delivery'] and not q.daily_marks
    menu(q,['#1 Vazio','#2 Rank D-5'])
    assert q.completed_missions['delivery']==['D4']
    saved=q.progress_state()
    other=QuestRoutes();other.resume_from(routes,saved,3,library=library,map_name='field')
    assert other.route['mission_ids']==['D5'] and other.kill_counts[1034]==7


def test_manual_new_acceptance_resets_only_matching_counter_after_slot_confirms(setup_queue):
    q,_,_=setup_queue
    open_board(q);menu(q,['#1 Vazio','#2 Rank D-5']);select(q,1)
    menu(q,['Rank D-4']);select(q,1)
    menu(q,['Aceitar missao']);select(q,1)
    say(q,'Aguarde')
    assert q.kill_counts[1315]==45
    menu(q,['#1 Rank D-4','#2 Rank D-5'])
    assert q.kill_counts.get(1315,0)==0 and q.kill_counts[1034]==7
    assert q.slot_owner[1]=='D4' and q.external_updates[-1][1]=='pickup'
    menu(q,['#1 Rank D-4','#2 Rank D-5'])
    assert len(q.external_updates)==1


def test_expired_mission_is_not_marked_delivered(setup_queue):
    q,_,_=setup_queue
    choose_delivery(q);say(q,'O tempo da missao acabou')
    assert q.kill_counts.get(1315,0)==0 and q.kill_counts[1034]==7
    assert not q.daily_marks and q.last_stage==('pickup',0)


def test_pickup_timer_is_confirmation_only_after_accept_request(setup_queue):
    q,_,_=setup_queue
    open_board(q);menu(q,['#1 Vazio']);select(q,1)
    menu(q,['Rank D-4']);select(q,1)
    say(q,'Tempo restante : 1 horas')  # description before acceptance is not a new quest
    assert q.kill_counts[1315]==45
    menu(q,['Aceitar missao']);select(q,1)
    say(q,'Tempo restante : 1 horas')
    assert q.kill_counts.get(1315,0)==0 and q.kill_counts[1034]==7
    assert q.external_updates[-1][1]=='pickup'


def test_saved_manual_completion_while_queue_not_loaded(tmp_path,setup_queue):
    q,_,library=setup_queue
    saved=q.progress_state();saved['character']='Teste';quest_progress.save(saved)
    r=relay(tmp_path);r.own_look={'name':'Teste'}
    mission=next(m for m in library['missions'] if m['id']=='D4')
    r.quests.external_updates=[(mission,'delivery')]
    r.quests.daily_marks=[(mission['board_id'],mission['rank'])]
    r.flush_daily()
    assert 'D4' in quest_progress.load()['completed_missions']['delivery']
    assert quest_daily.done_today('vip','Rank D-4')


def test_all_delivered_resume_ends_without_returning_to_hunt(setup_queue):
    q,routes,library=setup_queue
    q.completed_missions['delivery']=['D4','D5']
    other=QuestRoutes();other.resume_from(routes,q.progress_state(),3,library=library,map_name='field')
    assert other.phase=='done' and not other.active


def test_bot_new_acceptance_resets_counter_only_when_verified(setup_queue):
    q,_,_=setup_queue
    q.pending_new_pickup=('D4',1)
    assert q.kill_counts[1315]==45
    q.own_slot(1,'D4')
    assert q.kill_counts.get(1315,0)==0 and q.kill_counts[1034]==7


def test_new_acceptance_confirmation_can_arrive_on_next_mission(setup_queue):
    q,_,_=setup_queue
    q.pending_new_pickup=('D4',1)
    q.enter_stage('pickup',3,1)
    q.own_slot(1,'D4')
    assert q.kill_counts.get(1315,0)==0 and q.kill_counts[1034]==7


def test_missing_delivery_slot_restarts_pickup_instead_of_getting_stuck(setup_queue,tmp_path):
    from nrobot.quest_slots import effective_steps
    from nrobot.portals import PortalGuard
    q,_,_=setup_queue
    q.enter_stage('delivery',3)
    q.steps=effective_steps(q.library,q.current_mission,'delivery')
    q.step=next(i for i,s in enumerate(q.steps) if s['kind']=='select_mission_slot')
    q.npc=90;q.dialog=dict(entity_id=90,action='menu',options=['#1 Vazio','#2 Rank D-5'])
    q.plan('ra_in01',[219,95],None,PortalGuard(tmp_path/'portals.json'),4)
    assert q.phase=='pickup' and q.kill_counts.get(1315,0)==0
    assert 'D4' not in q.completed_missions['pickup'] and q.kill_counts[1034]==7
