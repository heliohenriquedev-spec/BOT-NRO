import copy
import struct
import pytest
from nrobot.quest_routes import QuestRoutes,save,load
from nrobot.map_navigation import CollisionMap
from nrobot.portals import PortalGuard


def route(name='Quest',**values):
    return dict(id=name,name=name,enabled=True,kills=2,species=[1037],target_map='field',
        steps=[dict(kind='walk',map='home',position=[8,8]),dict(kind='wait_map',map='field')],**values)


@pytest.fixture
def engine():
    q=QuestRoutes();q.start([route()],0);return q


def test_routes_persist_order_and_enabled_flags(tmp_path):
    a=route('A');b=route('B');b['enabled']=False
    path=tmp_path/'quests.json';save([b,a],path)
    q=QuestRoutes();q.start(load(path),0)
    assert [r['name'] for r in q.routes]==['A']
    assert [r['name'] for r in load(path)]==['B','A']


def test_draft_cannot_execute_and_queue_advances_in_order():
    q=QuestRoutes();draft=route();draft['needs_recording']=True
    with pytest.raises(ValueError,match='Grave o percurso'):q.start([draft],0)
    q.start([route('A'),route('B')],0);q.kills=2;q.advance(10)
    assert q.route['name']=='B' and q.kills==0 and q.phase=='travel'
    q.advance(20)
    assert q.phase=='done'


def test_recorder_uses_observed_portal_center_not_distant_click(engine):
    engine.stop();engine.record('Quest');engine.map='home'
    engine.observe([dict(kind='appearance',entity_id=99,species_id=45,position=[8,8]),
                    dict(kind='player_move',position=[1,1],destination=[12,12]),
                    dict(kind='map_change',map='field',position=[2,2])],1,'field',1)
    assert engine.recording['steps'][0]==dict(kind='portal',map='home',position=[8,8])


def test_portal_is_allowed_only_for_explicit_transition(engine,tmp_path):
    portal=PortalGuard(tmp_path/'portals.json');portal.known={'home':{'8,8':1,'20,20':2}}
    collision=CollisionMap(32,32,[1]*1024)
    engine.route['steps'][0]['kind']='portal'
    action=engine.plan('home',[7,7],collision,portal,0)
    assert action['kind']=='move' and action['position']==[8,8]
    assert collision.forbidden==frozenset()  # executor never mutates shared collision
    engine.observe([dict(kind='map_change',map='field.gat',position=[3,3])],1,'field.gat',1)
    engine.plan('field.gat',[3,3],collision,portal,1)
    engine.plan('field.gat',[3,3],collision,portal,2)
    assert engine.phase=='hunt'


def test_missing_connection_pauses_instead_of_inventing_return(engine,tmp_path):
    engine.plan('unrecorded',[5,5],None,PortalGuard(tmp_path/'p'),0)
    assert engine.phase=='paused' and 'Sem conexao' in engine.reason


def test_reuses_directed_connections_from_unchecked_routes(engine):
    link=route('Return');link.update(enabled=False,target_map='home',steps=[dict(kind='portal',map='town',position=[5,5]),dict(kind='wait_map',map='home')])
    engine.start([route(),link],0)
    steps=engine.itinerary('town')
    assert steps[0]['map']=='town' and steps[-1]['map']=='field'
    with pytest.raises(ValueError):engine.itinerary('other')


def test_menu_resolves_current_id_and_exact_option_not_saved_index(engine,tmp_path):
    engine.routes[0]['steps']=[dict(kind='npc',map='home',position=[5,5],name='Viajante Ninja'),
                              dict(kind='select',map='home',option='Kamizuru Nivel 2')]
    engine.actors={900:dict(position=[5,5],name='Viajante Ninja')}
    portals=PortalGuard(tmp_path/'p');c=CollisionMap(20,20,[1]*400)
    action=engine.plan('home',[5,4],c,portals,0)
    assert action==dict(kind='npc',entity_id=900)
    engine.sent(action,0)
    engine.observe([dict(kind='npc_dialog',entity_id=900,action='menu',options=['Outra','Kamizuru Nivel 2'])],1,'home',1)
    assert engine.plan('home',[5,4],c,portals,1)['choice']==2
    engine.dialog['options']=['Outra']
    assert engine.plan('home',[5,4],c,portals,2) is None
    assert engine.phase=='paused'


def test_npc_waits_for_matching_dialog_and_times_out(engine,tmp_path):
    engine.routes[0]['steps']=[dict(kind='next',map='home')]
    engine.npc=90;engine.dialog=dict(entity_id=90,action='menu',options=['Sim'])
    assert engine.plan('home',[5,5],None,PortalGuard(tmp_path/'p'),1) is None
    engine.plan('home',[5,5],None,PortalGuard(tmp_path/'p'),20)
    assert engine.phase=='paused' and 'recebido: menu' in engine.reason


def test_dialog_answered_from_duplicated_npc_id_is_followed(engine,tmp_path):
    # "Sala Vip#2": the conversation opened by our click may come back with another id.
    engine.routes[0]['steps']=[dict(kind='next',map='home'),dict(kind='select',map='home',option='Sim')]
    engine.npc=90;engine.dialog=dict(entity_id=91,action='next')
    action=engine.plan('home',[5,5],None,PortalGuard(tmp_path/'p'),1)
    assert action==dict(kind='next',entity_id=91)
    engine.sent(action,1);engine.dialog=dict(entity_id=91,action='menu',options=['Sim','Nao'])
    assert engine.plan('home',[5,5],None,PortalGuard(tmp_path/'p'),2)==dict(kind='select',entity_id=91,choice=1)


def test_next_pressed_by_hand_skips_to_the_menu(engine,tmp_path):
    engine.routes[0]['steps']=[dict(kind='next',map='home'),dict(kind='next',map='home'),dict(kind='select',map='home',option='Sim')]
    engine.npc=90;engine.dialog=dict(entity_id=90,action='menu',options=['Sim','Nao'])
    assert engine.plan('home',[5,5],None,PortalGuard(tmp_path/'p'),1) is None and engine.step==2
    assert engine.plan('home',[5,5],None,PortalGuard(tmp_path/'p'),2)==dict(kind='select',entity_id=90,choice=1)


def test_npc_found_by_name_one_cell_from_saved_coordinates(engine,tmp_path):
    engine.routes[0]['steps']=[dict(kind='npc',map='home',position=[213,81],name='Retorno')]
    engine.actors[110000005]=dict(position=[213,80],name='Retorno#D',species_id=706)
    engine.actors[110000006]=dict(position=[212,81],name='Estilista',species_id=819)
    assert engine.plan('home',[213,82],None,PortalGuard(tmp_path/'p'),1)==dict(kind='npc',entity_id=110000005)


def test_counts_confirmed_deaths_only_not_disappearances_or_other_players(engine):
    engine.phase='hunt'
    spawn=dict(kind='appearance',entity_id=50,species_id=1037,position=[5,5])
    hit=dict(kind='skill_damage',source_id=1,target_id=50,damage_raw=10)
    engine.observe([spawn,hit,dict(kind='remove',entity_id=50,reason=0)],1,'field',1)
    assert engine.kills==0
    engine.observe([spawn,hit,dict(kind='remove',entity_id=50,reason=1)],1,'field',2)
    assert engine.kills==1
    engine.observe([dict(kind='remove',entity_id=50,reason=1)],1,'field',3)
    assert engine.kills==1
    engine.observe([spawn,hit,{**hit,'source_id':2000002},dict(kind='remove',entity_id=50,reason=1)],1,'field',4)  # another player
    assert engine.kills==1
    engine.observe([spawn,hit,dict(kind='remove',entity_id=50,reason=1)],1,'field',5)
    assert engine.kills==2  # reused entity ID belongs to a new life


def test_recorder_stores_semantics_and_map_transition(engine):
    engine.stop();engine.record('Quest');engine.map='home'
    engine.observe([dict(kind='appearance',entity_id=8,species_id=46,position=[5,5],name='Sala Vip')],1,'home',0)
    engine.native(0x90,struct.pack('<HIB',0x90,8,1),'home')
    engine.observe([dict(kind='npc_dialog',entity_id=8,action='menu',options=['Entrar','Sair'])],1,'home',1)
    engine.native(0xb8,struct.pack('<HIB',0xb8,8,1),'home')
    engine.observe([dict(kind='map_change',map='field',position=[1,1])],1,'field',2)
    steps=engine.recording['steps']
    assert steps[0]['name']=='Sala Vip' and steps[1]['option']=='Entrar'
    assert steps[-1]==dict(kind='wait_map',map='field')
    assert all('entity_id' not in step for step in steps)


def test_already_at_destination_starts_hunt_without_repeating_npc(engine,tmp_path):
    engine.plan('field.gat',[1,1],None,PortalGuard(tmp_path/'p'),0)
    assert engine.phase=='hunt'


def test_packet_reader_decodes_menu_next_close():
    from nrobot.packet_reader import decode
    data=b'Kamizuru:Outra\0';frame=struct.pack('<HHI',0xb7,8+len(data),55)+data
    event=decode(frame)
    assert event['options']==['Kamizuru','Outra'] and event['entity_id']==55
    assert decode(struct.pack('<HI',0xb5,55))['action']=='next'
    assert decode(struct.pack('<HI',0xb6,55))['action']=='close'


@pytest.fixture
def relay(tmp_path,monkeypatch):
    import time
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_hunt import PacketHunt
    r=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    r.hunt=PacketHunt();r.apply_settings(dict(pause_on_players=False,pause_on_hidden=False,pause_on_disguised=False))
    o=r.tracker.observer;o.player_id=1;o.player=[5,5];o.player_at=time.monotonic();o.map_name='home'
    monkeypatch.setattr(r,'collision_map',lambda:CollisionMap(32,32,[1]*1024))
    class Writer:
        def __init__(self):self.packets=[]
        def write(self,data):self.packets.append(data)
        async def drain(self):pass
    r.upstream=Writer();r.quests.start([route()],time.monotonic())
    return r


def test_relay_routes_move_without_combat_and_f12_stops(relay):
    import asyncio
    r=relay
    assert asyncio.run(r.quest_tick(lambda:True))
    assert len(r.upstream.packets)==1 and not r.hunt.enabled
    r.commands_blocked=True
    asyncio.run(r.quest_tick(lambda:True))
    assert r.quests.phase=='paused' and len(r.upstream.packets)==1


def test_relay_does_not_inject_in_fragmented_native_frame(relay):
    import asyncio
    relay.native_frames.buffer.extend(b'\x90')
    asyncio.run(relay.quest_tick(lambda:True))
    assert not relay.upstream.packets


def test_relay_queue_arrival_runs_combat_then_advances_on_goal(relay):
    import asyncio,time
    r=relay;r.tracker.observer.map_name='field';r.quest_base_settings=copy.deepcopy(r.settings)
    original=copy.deepcopy(r.settings)
    asyncio.run(r.quest_tick(lambda:True))
    asyncio.run(r.quest_tick(lambda:True))
    assert r.quests.phase=='hunt' and r.hunt.enabled
    assert r.settings['species']==[1037] and not r.settings['auto_map_targets']
    r.quests.kills=2
    asyncio.run(r.quest_tick(lambda:True))
    assert r.quests.phase=='done' and not r.hunt.enabled
    assert r.settings==original


def test_quest_panel_reorders_and_persists_disabled_route(tmp_path,monkeypatch):
    import os
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    import nrobot.quest_panel as module
    app=QApplication.instance() or QApplication([])
    path=tmp_path/'quests.json';save([route('A'),route('B')],path)
    monkeypatch.setattr(module,'load',lambda:load(path))
    monkeypatch.setattr(module,'save',lambda data:save(data,path))
    panel=module.QuestPanel();panel.list.setCurrentRow(1);panel.reorder(-1)
    assert load(path)[0]['name']=='B'
    panel.list.item(0).setCheckState(Qt.Unchecked)
    assert not load(path)[0]['enabled']
    panel.update_state({'quests':dict(phase='travel')})
    assert not panel.start.isEnabled() and not panel.list.isEnabled()
    panel.close()


def test_extra_next_page_is_pressed_before_the_recorded_menu(engine,tmp_path):
    # Sala Vip: two "Proximo" pages, one recorded.
    engine.routes[0]['steps']=[dict(kind='next',map='home'),dict(kind='select',map='home',option='Sim')]
    engine.npc=90;engine.dialog=dict(entity_id=90,action='next')
    p=PortalGuard(tmp_path/'p')
    engine.sent(engine.plan('home',[5,5],None,p,1),1)
    engine.dialog=dict(entity_id=90,action='next')
    action=engine.plan('home',[5,5],None,p,2)
    assert action==dict(kind='next',entity_id=90,extra=True)
    engine.sent(action,2);assert engine.step==1
    engine.dialog=dict(entity_id=90,action='menu',options=['Sim','Nao'])
    assert engine.plan('home',[5,5],None,p,3)==dict(kind='select',entity_id=90,choice=1)


def test_recording_keeps_consecutive_next_pages():
    from nrobot.quest_routes import QuestRoutes
    q=QuestRoutes();q.record('x','travel')
    q.append(dict(kind='next',map='a'));q.append(dict(kind='next',map='a'))
    q.append(dict(kind='walk',map='a',position=[1,1]));q.append(dict(kind='walk',map='a',position=[1,1]))
    assert [s['kind'] for s in q.recording['steps']]==['next','next','walk']
