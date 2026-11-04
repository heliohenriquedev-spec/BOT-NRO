import copy
import os
import pytest
from nrobot import quest_library as lib
from nrobot.quest_routes import QuestRoutes
from nrobot.map_navigation import CollisionMap
from nrobot.portals import PortalGuard
from nrobot.npc_labels import clean,mission_option,mission_label


def test_walk_waypoint_inside_portal_margin_is_replaced_by_portal_approach(tmp_path):
    q=QuestRoutes();steps=[dict(kind='walk',map='hospital2',position=[103,5]),dict(kind='portal',map='hospital2',position=[103,3]),dict(kind='wait_map',map='areia')]
    q.start_validation(steps,'areia',0,mode='travel',label='Viagem')
    p=PortalGuard(tmp_path/'p');p.known={'hospital2':{'103,3':3}}
    c=CollisionMap(120,120,[1]*14400)
    action=q.plan('hospital2',[103,7],c,p,0)
    assert action['kind']=='move' and q.step==1 and action['position']==[103,3]
    assert q.phase=='travel'


def test_early_warp_advances_to_new_map_even_before_last_walk(tmp_path):
    q=QuestRoutes();steps=[dict(kind='walk',map='hospital2',position=[103,5]),dict(kind='portal',map='hospital2',position=[103,3]),dict(kind='wait_map',map='areia'),dict(kind='walk',map='areia',position=[10,10])]
    q.start_validation(steps,'areia',0,mode='travel',label='Viagem');q.map='hospital2'
    q.observe([dict(kind='map_change',map='areia.gat',position=[10,10])],1,'areia.gat',50)
    assert q.step==3 and q.progress_at==50
    p=PortalGuard(tmp_path/'p');q.plan('areia.gat',[10,10],None,p,51);q.plan('areia.gat',[10,10],None,p,52)
    assert q.phase=='done' and q.validation['completed']


def test_wrong_map_cannot_skip_an_expected_transition(tmp_path):
    q=QuestRoutes();steps=[dict(kind='portal',map='home',position=[5,5]),dict(kind='wait_map',map='areia'),dict(kind='wait_map',map='ra_in01')]
    q.start_validation(steps,'ra_in01',0,mode='travel',label='Viagem');q.map='home'
    q.observe([dict(kind='map_change',map='ra_in01',position=[10,10])],1,'ra_in01',1)
    assert q.step==0
    q.plan('ra_in01',[10,10],None,PortalGuard(tmp_path/'p'),2)
    assert not q.validation['completed']


@pytest.mark.parametrize('board_id,map_name,point',[('vip','ra_in01',[213,81]),('kakashi','kakashi',[83,150])])
def test_default_return_uses_registered_npc_and_waits_for_server_warp(tmp_path,board_id,map_name,point):
    q=QuestRoutes();q.start_validation([],map_name,0,mode='return',label='Retorno',library=lib.validate({}),return_board=board_id)
    q.actors[90]=dict(position=point,name='Retorno#interno')
    p=PortalGuard(tmp_path/'p');action=q.plan(map_name,point,None,p,0)
    assert action==dict(kind='npc',entity_id=90)
    q.sent(action,0);assert q.plan(map_name,point,None,p,1) is None and q.active
    q.observe([dict(kind='map_transfer',map='hospital2.gat',position=[10,10])],1,'hospital2.gat',2)
    q.plan('hospital2.gat',[10,10],None,p,2);q.plan('hospital2.gat',[10,10],None,p,3)
    assert q.phase=='done' and q.validation['completed']


def test_return_dialog_is_not_guessed(tmp_path):
    q=QuestRoutes();q.start_validation([],'ra_in01',0,mode='return',label='Retorno',library=lib.validate({}),return_board='vip')
    p=PortalGuard(tmp_path/'p');q.actors[90]=dict(position=[213,81],name='Retorno')
    q.sent(q.plan('ra_in01',[213,81],None,p,0),0)
    q.observe([dict(kind='npc_dialog',entity_id=90,action='menu',options=['Konoha','Suna'])],1,'ra_in01',1)
    q.plan('ra_in01',[213,81],None,p,3)
    assert q.phase=='paused' and not q.validation['completed'] and 'gravar' in q.reason.lower()


def test_display_cleans_codes_without_modifying_raw_options():
    raw='#1 ^0000FFRank A-1^000000'
    assert clean(raw)=='#1 Rank A-1' and raw.endswith('^000000')
    assert not mission_option('#1 ^FF0000Vázio^000000')
    assert mission_option('Rank SS^000000') and not mission_option('Sim')
    assert not mission_option(raw)  # occupied slots are managed separately from mission definitions


def test_npc_description_identifies_monsters_without_guessing_from_rank(monkeypatch):
    import nrobot.monster_db as db
    monkeypatch.setattr(db,'all_monsters',lambda:[dict(species_id=1262,name='Dragão Mutante'),dict(species_id=1294,name='Inseto Assassino')])
    data=lib.validate(dict(option_details={'vip':{'^0000FFRank A-1^000000':['Elimine Dragão Mutante e Inseto Assassino.']}}))
    m=lib.enrich_mission(dict(name='Rank A-1'),lib.option_descriptions(data,'vip','Rank A-1'))
    assert 1262 in m['monster_ids'] and 1294 in m['monster_ids']
    assert 'Dragão Mutante' in mission_label(m) and '^' not in mission_label(m)
    unknown=lib.enrich_mission(dict(name='Rank S-99'),[])
    assert not unknown['monster_ids']


def test_route_can_use_monsters_assigned_to_selected_mission(tmp_path,monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from nrobot.quest_panel import RouteEditor
    from nrobot import map_routes
    monkeypatch.setattr(lib,'FILE',tmp_path/'library.json');monkeypatch.setattr(map_routes,'FILE',tmp_path/'maps.json')
    lib.save(dict(missions=[dict(id='A',name='Rank A-1',board_id='vip',monster_ids=[1262,1294],target_map='anthell02')]))
    map_routes.save([dict(id='M',name='Kamizuru',target_map='anthell02',steps=[dict(kind='portal',map='hospital2',position=[1,1]),dict(kind='wait_map',map='anthell02')])])
    app=QApplication.instance() or QApplication([])
    editor=RouteEditor(dict(name='Rota',mission_ids=['A'],steps=[],species=[],kills=50),{})
    assert 'Dragão Mutante' in editor.mission_list.item(0).text()
    editor.map_route.setCurrentIndex(editor.map_route.findData('M'));editor.accept()
    assert editor.route['species']==[1262,1294] and editor.route['target_map']=='anthell02' and editor.route['map_route_id']=='M'
    editor.close()


def test_return_ignores_player_id_even_if_named_return_npc(tmp_path):
    q=QuestRoutes();q.start_validation([],'ra_in01',0,mode='return',label='Retorno',library=lib.validate({}),return_board='vip')
    q.actors[2000005]=dict(position=[213,80],name='Retorno',species_id=837)
    q.actors[110000005]=dict(position=[213,80],species_id=837)
    action=q.plan('ra_in01',[213,80],None,PortalGuard(tmp_path/'p'),0)
    assert action['entity_id']==110000005


def test_close_text_before_immediate_warp_does_not_pause_return(tmp_path):
    q=QuestRoutes();q.start_validation([],'ra_in01',0,mode='return',label='Retorno',library=lib.validate({}),return_board='vip')
    p=PortalGuard(tmp_path/'p');q.actors[90]=dict(position=[213,81],name='Retorno')
    q.sent(q.plan('ra_in01',[213,81],None,p,0),0)
    q.observe([dict(kind='npc_dialog',entity_id=90,action='close')],1,'ra_in01',1)
    q.plan('ra_in01',[213,81],None,p,1)
    assert q.active
    q.observe([dict(kind='map_change',map='hospital2',position=[5,5])],1,'hospital2',1.5)
    q.plan('hospital2',[5,5],None,p,2);q.plan('hospital2',[5,5],None,p,3)
    assert q.validation['completed']


def test_return_dialog_recording_is_saved_separately_from_quests(tmp_path,monkeypatch):
    import time
    from nrobot.session_relay import SessionRelay
    monkeypatch.setattr(lib,'FILE',tmp_path/'library.json')
    r=SessionRelay('127.0.0.1',folder=tmp_path);r.upstream=object()
    o=r.tracker.observer;o.player_id=1;o.player=[219,95];o.player_at=time.monotonic();o.map_name='ra_in01'
    r.library_control('quest_library_record',dict(scope='return',board_id='vip'))
    for step in [dict(kind='npc',map='ra_in01',position=[213,81],name='Retorno'),
                 dict(kind='select',map='ra_in01',option='Voltar ao ponto salvo'),dict(kind='wait_map',map='hospital2')]:r.quests.append(step)
    o.player=[5,5];o.map_name='hospital2'
    r.library_control('quest_library_save',{})
    saved=lib.load();assert saved['missions']==[] and 'vip' in saved['return_paths']
    assert any(s.get('option')=='Voltar ao ponto salvo' for s in lib.return_steps(saved,'vip'))


def test_two_confirmed_map_transitions_in_same_batch_do_not_stall(tmp_path):
    q=QuestRoutes();steps=[dict(kind='portal',map='home',position=[5,5]),dict(kind='wait_map',map='areia'),
                          dict(kind='portal',map='areia',position=[6,6]),dict(kind='wait_map',map='ra_in01'),
                          dict(kind='walk',map='ra_in01',position=[10,10])]
    q.start_validation(steps,'ra_in01',0,mode='travel',label='Viagem');q.map='home'
    q.observe([dict(kind='map_change',map='areia',position=[6,6]),dict(kind='map_change',map='ra_in01',position=[10,10])],1,'ra_in01',1)
    assert q.step==4
    p=PortalGuard(tmp_path/'p');q.plan('ra_in01',[10,10],None,p,2);q.plan('ra_in01',[10,10],None,p,3)
    assert q.validation['completed']


def test_return_npc_talking_first_is_clicked_through(tmp_path):
    q=QuestRoutes();q.start_validation([],'ra_in01',0,mode='return',label='Retorno',library=lib.validate({}),return_board='vip')
    p=PortalGuard(tmp_path/'p');q.actors[90]=dict(position=[213,80],name='Retorno#D')
    q.sent(q.plan('ra_in01',[213,81],None,p,0),0)
    q.observe([dict(kind='npc_dialog',entity_id=90,action='text',text='Ola, Guerreiro'),dict(kind='npc_dialog',entity_id=90,action='next')],1,'ra_in01',1)
    action=q.plan('ra_in01',[213,81],None,p,2);assert action==dict(kind='next',entity_id=90,extra=True);q.sent(action,2)
    q.observe([dict(kind='npc_dialog',entity_id=90,action='close')],1,'ra_in01',3)
    action=q.plan('ra_in01',[213,81],None,p,4);assert action==dict(kind='close',entity_id=90,extra=True);q.sent(action,4)
    q.observe([dict(kind='map_change',map='home',position=[2,2])],1,'home',5)
    q.plan('home',[2,2],None,p,5);q.plan('home',[2,2],None,p,6)
    assert q.phase=='done' and q.validation['completed']


def test_return_menu_stops_and_names_the_options(tmp_path):
    q=QuestRoutes();q.start_validation([],'ra_in01',0,mode='return',label='Retorno',library=lib.validate({}),return_board='vip')
    p=PortalGuard(tmp_path/'p');q.actors[90]=dict(position=[213,80],name='Retorno#D')
    q.sent(q.plan('ra_in01',[213,81],None,p,0),0)
    q.observe([dict(kind='npc_dialog',entity_id=90,action='menu',options=['Hospital','Cancelar'])],1,'ra_in01',1)
    q.plan('ra_in01',[213,81],None,p,2)
    assert q.phase=='paused' and 'Hospital / Cancelar' in q.reason


def test_return_question_yes_no_is_answered_yes(tmp_path):
    q=QuestRoutes();q.start_validation([],'ra_in01',0,mode='return',label='Retorno',library=lib.validate({}),return_board='vip')
    p=PortalGuard(tmp_path/'p');q.actors[90]=dict(position=[213,80],name='Retorno#D')
    q.sent(q.plan('ra_in01',[213,81],None,p,0),0)
    q.observe([dict(kind='npc_dialog',entity_id=90,action='text',text='Quer retornar para sua vila?'),
               dict(kind='npc_dialog',entity_id=90,action='menu',options=['Sim','Não'])],1,'ra_in01',1)
    action=q.plan('ra_in01',[213,81],None,p,2)
    assert action==dict(kind='select',entity_id=90,choice=1,extra=True);q.sent(action,2)
    q.observe([dict(kind='map_change',map='konoha',position=[2,2])],1,'konoha',3)
    q.plan('konoha',[2,2],None,p,3);q.plan('konoha',[2,2],None,p,4)
    assert q.phase=='done' and q.validation['completed']
