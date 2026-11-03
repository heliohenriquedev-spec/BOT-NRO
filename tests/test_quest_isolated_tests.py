import asyncio
import copy
import os
import time
import pytest
from nrobot import quest_library as lib
from nrobot.quest_routes import QuestRoutes
from nrobot.portals import PortalGuard


def mission():
    steps=[dict(kind='npc',map='ra_in01',position=[219,95],name='Quadro'),dict(kind='close',map='ra_in01')]
    return dict(id='A',board_id='vip',name='A',pickup_steps=steps,delivery_steps=copy.deepcopy(steps),
                pickup_confirmation='Aceita A',delivery_confirmation='Entregue A')


def test_access_validation_stops_at_destination_without_hunt(tmp_path):
    q=QuestRoutes();steps=[dict(kind='walk',map='home',position=[5,5])]
    q.start_validation(steps,'home',0,mode='access',label='Acesso',target_position=[5,5])
    q.plan('home',[5,5],None,PortalGuard(tmp_path/'p'),0)
    q.plan('home',[5,5],None,PortalGuard(tmp_path/'p'),1)
    assert q.phase=='done' and q.validation['completed'] and not q.active
    assert q.kills==0 and q.index==0


@pytest.mark.parametrize('stage,success',[('pickup','Aceita A'),('delivery','Entregue A')])
def test_single_mission_stage_finishes_without_running_next_stage(tmp_path,stage,success):
    q=QuestRoutes();q.start_validation([],'ra_in01',0,mode=stage,label='Teste',library=lib.validate(dict(missions=[mission()])),mission_id='A')
    p=PortalGuard(tmp_path/'p');q.actors[90]=dict(position=[219,95],name='Quadro')
    q.sent(q.plan('ra_in01',[219,95],None,p,0),0)
    q.observe([dict(kind='npc_dialog',entity_id=90,action='text',text=success),
               dict(kind='npc_dialog',entity_id=90,action='close')],1,'ra_in01',1)
    q.sent(q.plan('ra_in01',[219,95],None,p,1),1)
    q.plan('ra_in01',[219,95],None,p,2)
    assert q.phase=='return' and not q.validation['completed']
    q.actors[99]=dict(position=[213,81],name='Retorno')
    q.sent(q.plan('ra_in01',[213,81],None,p,3),3)
    q.observe([dict(kind='map_change',map='home',position=[2,2])],1,'home',4)
    q.plan('home',[2,2],None,p,4);q.plan('home',[2,2],None,p,5)
    assert q.phase=='done' and q.validation['completed']
    assert q.completed_missions[stage]==['A'] and q.index==0
    other='delivery' if stage=='pickup' else 'pickup'
    assert q.completed_missions[other]==[]


def test_missing_npc_success_is_failure_not_validation(tmp_path):
    q=QuestRoutes();q.start_validation([],'ra_in01',0,mode='pickup',label='Teste',library=lib.validate(dict(missions=[mission()])),mission_id='A')
    p=PortalGuard(tmp_path/'p');q.steps=mission()['pickup_steps'];q.step=len(q.steps)
    q.plan('ra_in01',[219,95],None,p,0);q.plan('ra_in01',[219,95],None,p,21)
    assert q.phase=='paused' and not q.validation['completed']


@pytest.fixture
def relay(tmp_path,monkeypatch):
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_hunt import PacketHunt
    monkeypatch.setattr(lib,'FILE',tmp_path/'library.json')
    r=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True);r.hunt=PacketHunt();r.apply_settings({})
    o=r.tracker.observer;o.player_id=1;o.player=[219,95];o.player_at=time.monotonic();o.map_name='ra_in01'
    r.upstream=object()
    return r


def test_catalog_mode_saves_all_menu_options_without_accepting_any_mission(relay):
    r=relay
    r.library_control('quest_library_record',dict(scope='menus',board_id='vip'))
    r.quests.recording.update(steps=[dict(kind='npc',map='ra_in01',position=[219,95]),dict(kind='cancel',map='ra_in01')],
                             observed_menus=[['A','B','Voltar'],['C','D']])
    r.library_control('quest_library_save',{})
    data=lib.load()
    assert data['menus']['vip']==[['A','B','Voltar'],['C','D']]
    assert data['missions']==[] and not r.hunt.enabled and r.quests.recording is None


def test_pickup_can_be_tested_without_delivery_recipe_and_f12_interrupts(relay):
    m=mission();m['delivery_steps']=[];m['delivery_confirmation']='';lib.save(dict(missions=[m]))
    relay.library_control('quest_library_test',dict(mode='pickup',mission_id='A'))
    assert relay.quests.phase=='pickup' and not relay.hunt.enabled
    relay.commands_blocked=True
    asyncio.run(relay.quest_tick(lambda:True))
    assert not relay.quests.active and not relay.quests.validation['completed']


def test_test_cannot_replace_active_recording(relay):
    lib.save(dict(missions=[mission()]))
    relay.quests.record('A','pickup')
    with pytest.raises(ValueError,match='encerre a gravacao'):
        relay.library_control('quest_library_test',dict(mode='pickup',mission_id='A'))
    assert relay.quests.recording['id']=='A'


def test_catalog_selection_registers_only_checked_missions_and_keeps_all_options(relay,monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication,QDialog,QListWidget
    from PySide6.QtCore import Qt
    from nrobot.quest_library_panel import QuestLibraryPanel
    lib.save(dict(menus={'vip':[['A','B','C','Voltar']]}))
    app=QApplication.instance() or QApplication([])
    def choose(dialog):
        items=dialog.findChild(QListWidget)
        for i in (0,2):items.item(i).setCheckState(Qt.Checked)
        return QDialog.Accepted
    monkeypatch.setattr(QDialog,'exec',choose)
    panel=QuestLibraryPanel();panel.import_options()
    assert [m['name'] for m in lib.load()['missions']]==['A','C']
    assert lib.load()['menus']['vip']==[['A','B','C','Voltar']]
    panel.close()


def test_route_travel_validation_does_not_start_combat(relay,monkeypatch):
    import nrobot.quest_relay as module
    route=dict(id='R',name='Viagem',target_map='ra_in01',steps=[dict(kind='walk',map='ra_in01',position=[219,95])],needs_recording=False)
    monkeypatch.setattr(module,'load',lambda:[route])
    relay.quest_control('quest_test_route',dict(route_id='R'),lambda:True)
    assert relay.quests.validation['mode']=='travel' and not relay.hunt.enabled
    async def no_hold():return False
    monkeypatch.setattr(relay,'update_presence_hold',no_hold)
    asyncio.run(relay.quest_tick(lambda:True));asyncio.run(relay.quest_tick(lambda:True))
    assert relay.quests.phase=='done' and relay.quests.validation['completed'] and not relay.hunt.enabled


def test_checked_missions_are_all_taken_with_one_return_at_the_end(tmp_path):
    a=mission();b={**mission(),'id':'B','name':'B','pickup_confirmation':'Aceita B'}
    q=QuestRoutes();q.start_validation([],'ra_in01',0,mode='pickup',label='Pegar: A, B',
                                       library=lib.validate(dict(missions=[a,b])),mission_ids=['A','B'])
    p=PortalGuard(tmp_path/'p');q.actors[90]=dict(position=[219,95],name='Quadro')
    for t,success in ((0,'Aceita A'),(10,'Aceita B')):
        q.sent(q.plan('ra_in01',[219,95],None,p,t),t)
        q.observe([dict(kind='npc_dialog',entity_id=90,action='text',text=success),
                   dict(kind='npc_dialog',entity_id=90,action='close')],1,'ra_in01',t+1)
        q.sent(q.plan('ra_in01',[219,95],None,p,t+1),t+1)
        q.plan('ra_in01',[219,95],None,p,t+2)
        if t==0:assert q.phase=='pickup' and q.mission_index==1  # same board: no Retorno in between
    assert q.phase=='return' and q.completed_missions['pickup']==['A','B']
    q.actors[99]=dict(position=[213,80],name='Retorno#D')
    q.sent(q.plan('ra_in01',[213,81],None,p,13),13)
    q.observe([dict(kind='map_change',map='home',position=[2,2])],1,'home',14)
    q.plan('home',[2,2],None,p,14);q.plan('home',[2,2],None,p,15)
    assert q.phase=='done' and q.validation['completed']


def test_panel_command_runs_every_checked_mission(relay):
    a=mission();b={**mission(),'id':'B','name':'B'}
    lib.save(dict(missions=[a,b],checked_missions=['B','A','gone']))
    assert lib.load()['checked_missions']==['B','A']  # removed missions drop out of the selection
    relay.library_control('quest_library_test',dict(mode='pickup',mission_ids=['A','B'],mission_id='A'))
    q=relay.quests
    assert q.phase=='pickup' and q.route['mission_ids']==['A','B'] and q.validation['all_missions']
    assert q.reason=='Testando: Pegar: A, B'
