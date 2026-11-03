import copy
import os
import struct
import pytest
from nrobot import quest_library as lib
from nrobot.quest_routes import QuestRoutes,validate_routes
from nrobot.portals import PortalGuard


def mission(identity='A',board_id='vip'):
    b=next(b for b in lib.BOARDS if b['id']==board_id)
    steps=[dict(kind='npc',map=b['map'],position=b['position'],name=b['npc_name']),dict(kind='close',map=b['map'])]
    return dict(id=identity,name='Missao '+identity,board_id=board_id,pickup_steps=copy.deepcopy(steps),delivery_steps=copy.deepcopy(steps),
                pickup_confirmation='Aceita '+identity,delivery_confirmation='Entregue '+identity)


def route(ids):
    return dict(id='R',name='Caca',enabled=True,kills=50,species=[1262],target_map='anthell02',mission_ids=ids,
                steps=[dict(kind='portal',map='ra_in01',position=[1,1]),dict(kind='wait_map',map='anthell02')])


def vip_access():
    return [dict(kind='portal',map='hospital2',position=[2,2]),dict(kind='wait_map',map='areia'),
            dict(kind='npc',map='areia',position=[144,195],name='Sala Vip'),dict(kind='wait_map',map='ra_in01'),
            dict(kind='walk',map='ra_in01',position=[219,95])]


def test_shared_persistence_keeps_conversations_out_of_routes(tmp_path):
    path=tmp_path/'library.json';data=lib.save(dict(missions=[mission()],access_paths=[]),path)
    assert lib.load(path)==data
    stored=validate_routes([route(['A'])])[0]
    assert stored['pickup_steps']==[] and stored['delivery_steps']==[] and stored['lifecycle_enabled']
    q=QuestRoutes();q.start([stored],0,library=data)
    assert q.current_mission['id']=='A' and q.phase=='pickup'
    data['missions'][0]['pickup_confirmation']='Mudou'
    assert q.confirmation()=='Aceita A'  # running queue holds an isolated snapshot
    q.start([stored],1,library=data)
    assert q.confirmation()=='Mudou'


def test_vip_access_requires_actual_sala_vip_npc(tmp_path):
    b=lib.BOARDS[0];steps=vip_access()
    assert lib.validate_access(steps,b,'ra_in01',[219,95])==steps
    without_gate=[s for s in steps if s['kind']!='npc']
    with pytest.raises(ValueError,match='Sala Vip'):lib.validate_access(without_gate,b,'ra_in01',[219,95])
    with pytest.raises(ValueError,match='Termine'):lib.validate_access(steps,b,'areia',[219,95])
    with pytest.raises(ValueError,match='pare antes'):
        lib.validate_access(steps+[dict(kind='npc',map='ra_in01',position=[219,95],name='Quadro')],b,'ra_in01',[219,95])


def test_mission_conversation_cannot_capture_other_npc_or_path():
    b=lib.BOARDS[0];m=mission()
    assert lib.validate_conversation(m['pickup_steps'],b)==m['pickup_steps']
    wrong=copy.deepcopy(m['pickup_steps']);wrong[0]['position']=[144,195]
    with pytest.raises(ValueError,match='outro NPC'):lib.validate_conversation(wrong,b)
    wrong=copy.deepcopy(m['pickup_steps']);wrong.append(dict(kind='walk',map='ra_in01',position=[2,2]))
    with pytest.raises(ValueError,match='sem caminhar'):lib.validate_conversation(wrong,b)


def test_missing_or_incomplete_mission_blocks_queue():
    q=QuestRoutes()
    with pytest.raises(ValueError,match='nao cadastrada'):q.start([route(['missing'])],0,library={})
    m=mission();m['delivery_steps']=[]
    with pytest.raises(ValueError):q.start([route(['A'])],0,library=dict(missions=[m]))


def test_access_is_composed_with_mission_without_copying_to_route(tmp_path):
    library=dict(missions=[mission()],access_paths=[dict(id='P',name='Hospital VIP',board_id='vip',steps=vip_access())])
    q=QuestRoutes();q.start([route(['A'])],0,library=library)
    steps=q.itinerary('hospital2')
    assert steps[:5]==vip_access()
    assert steps[-2]['position']==[219,95] and steps[-2]['kind']=='npc'
    assert q.route['pickup_steps']==[]
    # Starting inside the VIP room never repeats the entrance conversation.
    assert q.itinerary('ra_in01')==mission()['pickup_steps']


def complete_dialog(q,identity,message,map_name,position,portals,now):
    if q.map!=map_name:q.observe([dict(kind='map_change',map=map_name,position=position)],1,map_name,now)
    q.actors[identity]=dict(position=position,name='Quadro de Missões')
    action=q.plan(map_name,position,None,portals,now)
    assert action['kind']=='npc';q.sent(action,now)
    q.observe([dict(kind='npc_dialog',entity_id=identity,action='text',text=message),
               dict(kind='npc_dialog',entity_id=identity,action='close')],1,map_name,now+1)
    action=q.plan(map_name,position,None,portals,now+1)
    assert action['kind']=='close';q.sent(action,now+1)
    q.plan(map_name,position,None,portals,now+2)


def complete_return(q,board_id,portals,now):
    npc=next(b for b in lib.BOARDS if b['id']==board_id)['return_npc']
    q.actors[777]=dict(position=npc['position'],name='Retorno')
    q.sent(q.plan(npc['map'],npc['position'],None,portals,now),now)
    q.observe([dict(kind='map_change',map='home',position=[2,2])],1,'home',now+1)
    q.plan('home',[2,2],None,portals,now+1);q.plan('home',[2,2],None,portals,now+2)


def test_two_boards_require_each_acceptance_and_each_delivery(tmp_path):
    q=QuestRoutes();q.start([route(['A','B'])],0,library=dict(missions=[mission(),mission('B','kakashi')]))
    p=PortalGuard(tmp_path/'p')
    complete_dialog(q,90,'Aceita A','ra_in01',[219,95],p,0)
    assert q.phase=='return'
    complete_return(q,'vip',p,2)
    assert q.phase=='pickup' and q.current_mission['id']=='B'
    assert q.completed_missions['pickup']==['A'] and not q.stage_confirmed
    complete_dialog(q,91,'Aceita B','kakashi',[87,140],p,3)
    complete_return(q,'kakashi',p,5)
    assert q.phase=='travel' and q.completed_missions['pickup']==['A','B']
    q.plan('anthell02',[2,2],None,p,6);assert q.phase=='hunt'
    q.kills=50;q.finish_hunt(7)
    complete_dialog(q,92,'Entregue A','ra_in01',[219,95],p,8)
    complete_return(q,'vip',p,10)
    assert q.phase=='delivery' and q.index==0 and q.current_mission['id']=='B'
    complete_dialog(q,93,'Entregue B','kakashi',[87,140],p,11)
    complete_return(q,'kakashi',p,13)
    assert q.phase=='done' and q.completed_missions['delivery']==['A','B']


def test_success_from_first_mission_cannot_confirm_second(tmp_path):
    q=QuestRoutes();q.start([route(['A','B'])],0,library=dict(missions=[mission(),mission('B')]))
    p=PortalGuard(tmp_path/'p');complete_dialog(q,90,'Aceita A','ra_in01',[219,95],p,0)
    q.actors[90]=dict(position=[219,95],name='Quadro de Missões')
    q.sent(q.plan('ra_in01',[219,95],None,p,3),3)
    q.observe([dict(kind='npc_dialog',entity_id=90,action='text',text='Aceita A'),
               dict(kind='npc_dialog',entity_id=90,action='close')],1,'ra_in01',4)
    q.sent(q.plan('ra_in01',[219,95],None,p,4),4)
    q.plan('ra_in01',[219,95],None,p,26)
    assert q.phase=='paused' and q.completed_missions['pickup']==['A']


def test_cancel_menu_is_recorded_but_does_not_confirm_success(tmp_path):
    q=QuestRoutes();q.record('A','pickup');q.actors[90]=dict(position=[219,95],name='Quadro')
    q.native(0x90,struct.pack('<HIB',0x90,90,1),'ra_in01')
    q.observe([dict(kind='npc_dialog',entity_id=90,action='menu',options=['Missao A','Voltar'])],1,'ra_in01',0)
    q.native(0xb8,struct.pack('<HIB',0xb8,90,255),'ra_in01')
    assert q.recording['steps'][-1]['kind']=='cancel' and not q.recording.get('error')
    assert not q.stage_confirmed


def test_editor_selects_both_boards_without_duplicating_dialogs(tmp_path,monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from nrobot.quest_panel import RouteEditor
    monkeypatch.setattr(lib,'FILE',tmp_path/'library.json')
    lib.save(dict(missions=[mission(),mission('B','kakashi')]))
    app=QApplication.instance() or QApplication([])
    editor=RouteEditor(route(['B','A']),{})
    assert editor.selected_missions()==['B','A']
    assert not editor.stage_tabs.isTabEnabled(0) and editor.stage_tabs.currentIndex()==1
    editor.accept()
    assert editor.route['mission_ids']==['B','A'] and not editor.route['pickup_steps']
    editor.close()


def test_shared_recorder_writes_library_only_and_preserves_other_missions(tmp_path,monkeypatch):
    from nrobot.session_relay import SessionRelay
    monkeypatch.setattr(lib,'FILE',tmp_path/'library.json')
    data=lib.save(dict(missions=[mission(),mission('B','kakashi')]))
    r=SessionRelay('127.0.0.1',folder=tmp_path)
    r.quests.record('A','pickup');r.quests.recording.update(scope='mission',board_id='vip',
        steps=mission()['pickup_steps'],observed_texts=['Nova confirmacao'],observed_menus=[['Missao A','Missao C','Voltar']])
    with pytest.raises(ValueError,match='realmente recebido'):
        r.library_control('quest_library_save',dict(confirmation='Texto ausente'))
    assert lib.load()['missions'][0]['pickup_confirmation']=='Aceita A'
    r.library_control('quest_library_save',dict(confirmation='Nova confirmacao'))
    saved=lib.load()
    assert saved['missions'][0]['pickup_confirmation']=='Nova confirmacao'
    assert saved['missions'][1]==data['missions'][1]
    assert saved['menus']['vip']==[['Missao A','Missao C','Voltar']]
    assert not (tmp_path/'rotas_quests.json').exists() and r.quests.recording is None


def test_access_recording_is_saved_without_mission_interaction(tmp_path,monkeypatch):
    from nrobot.session_relay import SessionRelay
    monkeypatch.setattr(lib,'FILE',tmp_path/'library.json')
    r=SessionRelay('127.0.0.1',folder=tmp_path)
    r.tracker.observer.player=[219,95];r.tracker.observer.map_name='ra_in01'
    r.quests.record('vip');r.quests.recording.update(scope='access',board_id='vip',steps=vip_access())
    r.library_control('quest_library_save',{})
    data=lib.load()
    assert len(data['access_paths'])==1 and data['missions']==[]
    assert data['access_paths'][0]['steps']==vip_access()


def test_shared_paths_are_protected_from_updates():
    from nrobot.updater import PROTECTED
    assert 'data/rede/quadros_missoes.json' in PROTECTED


def test_unseen_return_path_is_not_invented():
    q=QuestRoutes();q.start([route(['A'])],0,library=dict(missions=[mission()]))
    with pytest.raises(ValueError,match='percurso de acesso'):q.itinerary('anthell02')


def test_access_recorder_remembers_origin_before_first_transition(tmp_path,monkeypatch):
    import time
    from nrobot.session_relay import SessionRelay
    monkeypatch.setattr(lib,'FILE',tmp_path/'library.json')
    r=SessionRelay('127.0.0.1',folder=tmp_path);r.upstream=object()
    o=r.tracker.observer;o.player_id=1;o.player=[10,10];o.player_at=time.monotonic();o.map_name='areia'
    r.library_control('quest_library_record',dict(scope='access',board_id='vip'))
    assert r.quests.recording['steps'][0]==dict(kind='walk',map='areia',position=[10,10])
    # A map change alone must not disguise a missing Sala Vip interaction.
    r.quests.append(dict(kind='wait_map',map='ra_in01'))
    r.quests.append(dict(kind='walk',map='ra_in01',position=[219,95]))
    o.player=[219,95];o.map_name='ra_in01'
    with pytest.raises(ValueError,match='Sala Vip'):r.library_control('quest_library_save',{})


def test_fast_npc_response_is_not_erased_after_drain(tmp_path,monkeypatch):
    import asyncio,time
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_hunt import PacketHunt
    r=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True);r.hunt=PacketHunt();r.apply_settings({})
    q=r.quests;q.start([route(['A'])],time.monotonic(),library=dict(missions=[mission()]))
    o=r.tracker.observer;o.player_id=1;o.player=[219,95];o.player_at=time.monotonic();o.map_name='ra_in01'
    q.actors[90]=dict(position=[219,95],name='Quadro de Missões')
    async def no_hold():return False
    monkeypatch.setattr(r,'update_presence_hold',no_hold)
    monkeypatch.setattr(r.native_frames,'fallback',lambda:{0x90:7})
    class Writer:
        def write(self,data):pass
        async def drain(self):
            q.observe([dict(kind='npc_dialog',entity_id=90,action='text',text='Aceita A'),
                       dict(kind='npc_dialog',entity_id=90,action='close')],1,'ra_in01',time.monotonic())
    r.upstream=Writer()
    assert asyncio.run(r.quest_tick(lambda:True))
    assert q.stage_confirmed and q.dialog['action']=='close'
