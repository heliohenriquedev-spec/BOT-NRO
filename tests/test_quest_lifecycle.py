import asyncio
import os
import struct
import time
import pytest
from nrobot.quest_routes import QuestRoutes,validate_routes
from nrobot.map_navigation import CollisionMap
from nrobot.portals import PortalGuard


def lifecycle():
    return dict(id='Q',name='Quest',enabled=True,kills=50,species=[1262],target_map='field',
        lifecycle_enabled=True,pickup_confirmation='Quest aceita',delivery_confirmation='Recompensa recebida',
        pickup_steps=[dict(kind='npc',map='home',position=[5,5],name='Missoes'),dict(kind='close',map='home')],
        steps=[dict(kind='portal',map='home',position=[10,10]),dict(kind='wait_map',map='field')],
        delivery_steps=[dict(kind='portal',map='field',position=[10,10]),dict(kind='wait_map',map='home'),
                        dict(kind='npc',map='home',position=[5,5],name='Missoes'),dict(kind='close',map='home')])


def test_complete_cycle_never_advances_before_confirmed_delivery(tmp_path):
    q=QuestRoutes();q.start([lifecycle(),{**lifecycle(),'id':'Q2','name':'Proxima'}],0)
    c=CollisionMap(32,32,[1]*1024);p=PortalGuard(tmp_path/'p')
    q.actors[90]=dict(position=[5,5],name='Missoes')
    assert q.phase=='pickup'
    q.sent(q.plan('home',[5,4],c,p,0),0)
    q.observe([dict(kind='npc_dialog',entity_id=90,action='text',text='Quest aceita com sucesso!'),
               dict(kind='npc_dialog',entity_id=90,action='close')],1,'home',1)
    q.sent(q.plan('home',[5,4],c,p,1),1)
    q.plan('home',[5,4],c,p,2)
    assert q.phase=='travel' and q.index==0 and not q.stage_confirmed
    # Travel from an already confirmed destination is allowed only after pickup.
    q.plan('field',[5,4],c,p,3)
    assert q.phase=='hunt'
    q.kills=50;q.finish_hunt(4)
    assert q.phase=='delivery' and q.index==0 and q.kills==50
    q.plan('field',[5,4],c,p,4)
    q.observe([dict(kind='map_change',map='home',position=[5,4])],1,'home',5)
    q.plan('home',[5,4],c,p,5)
    q.actors[999]=dict(position=[5,5],name='Missoes')
    q.sent(q.plan('home',[5,4],c,p,6),6)
    # Correct completion text from another NPC cannot complete this delivery.
    q.observe([dict(kind='npc_dialog',entity_id=91,action='text',text='Recompensa recebida')],1,'home',7)
    assert not q.stage_confirmed
    q.observe([dict(kind='npc_dialog',entity_id=999,action='text',text='Recompensa recebida: 100 zeny'),
               dict(kind='npc_dialog',entity_id=999,action='close')],1,'home',8)
    q.sent(q.plan('home',[5,4],c,p,8),8);q.plan('home',[5,4],c,p,9)
    assert q.index==1 and q.phase=='pickup' and q.kills==0 and not q.stage_confirmed


def test_missing_acceptance_stops_instead_of_hunting(tmp_path):
    q=QuestRoutes();q.start([lifecycle()],0)
    q.steps=q.route['pickup_steps'];q.step=len(q.steps)
    q.plan('home',[5,4],None,PortalGuard(tmp_path/'p'),21)
    # First position observation establishes the timer, then absence must time out.
    q.plan('home',[5,4],None,PortalGuard(tmp_path/'p'),42)
    assert q.phase=='paused' and q.index==0


@pytest.mark.parametrize('field',['pickup_steps','delivery_steps','pickup_confirmation','delivery_confirmation'])
def test_start_requires_each_enabled_stage(field):
    data=lifecycle();data[field]=[] if field.endswith('steps') else ''
    with pytest.raises(ValueError,match='Configure o trecho'):QuestRoutes().start([data],0)


def test_recording_carries_stage_and_only_actual_npc_responses():
    q=QuestRoutes();q.record('Q','pickup');q.actors[90]=dict(position=[5,5],name='Missoes')
    q.native(0x90,struct.pack('<HIB',0x90,90,1),'home')
    q.observe([dict(kind='npc_dialog',entity_id=91,action='text',text='Errado'),
               dict(kind='npc_dialog',entity_id=90,action='text',text='Quest aceita')],1,'home',1)
    assert q.recording['stage']=='pickup'
    assert q.recording['observed_texts']==['Quest aceita']
    assert q.snapshot()['last_npc_text']=='Quest aceita'


def test_legacy_routes_keep_saved_travel_steps():
    data=lifecycle();data.pop('lifecycle_enabled');data.pop('pickup_steps');data.pop('delivery_steps')
    normalized=validate_routes([data])[0]
    assert not normalized['lifecycle_enabled'] and normalized['steps']==data['steps']


def test_editor_preserves_independent_segments():
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from nrobot.quest_panel import RouteEditor
    app=QApplication.instance() or QApplication([])
    route=lifecycle();editor=RouteEditor(route,{})
    assert editor.read_steps('pickup')==route['pickup_steps']
    assert editor.read_steps('travel')==route['steps']
    assert editor.read_steps('delivery')==route['delivery_steps']
    editor.kills.setValue(60);editor.accept()
    assert editor.route['kills']==60 and editor.route['delivery_confirmation']=='Recompensa recebida'
    assert editor.route['pickup_steps']==route['pickup_steps']
    editor.close()


def test_saving_pickup_does_not_overwrite_travel_and_requires_received_text(tmp_path,monkeypatch):
    from nrobot.session_relay import SessionRelay
    import nrobot.quest_relay as module
    route=lifecycle();saved=[]
    monkeypatch.setattr(module,'load',lambda:[route.copy()])
    monkeypatch.setattr(module,'save',lambda routes:saved.extend(validate_routes(routes)))
    relay=SessionRelay('127.0.0.1',folder=tmp_path)
    q=relay.quests;q.record('Q','pickup')
    q.recording.update(steps=route['pickup_steps'],observed_texts=['Quest aceita com sucesso'])
    with pytest.raises(ValueError,match='nao apareceu'):
        relay.quest_control('quest_record_save',dict(confirmation='Recompensa recebida'),lambda:True)
    assert not saved and q.recording
    relay.quest_control('quest_record_save',dict(confirmation='Quest aceita'),lambda:True)
    assert saved[0]['steps']==route['steps']
    assert saved[0]['target_map']=='field' and saved[0]['delivery_steps']==route['delivery_steps']
    assert q.recording is None


def test_relay_goal_moves_to_delivery_without_advancing_queue(tmp_path,monkeypatch):
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_hunt import PacketHunt
    relay=SessionRelay('127.0.0.1',folder=tmp_path,allow_commands=True)
    relay.hunt=PacketHunt();relay.apply_settings({})
    q=relay.quests;q.start([lifecycle()],time.monotonic());q.phase='hunt';q.kills=50
    o=relay.tracker.observer;o.player=[5,5];o.player_id=1;o.player_at=time.monotonic();o.map_name='field'
    relay.upstream=object()
    async def no_hold():return False
    monkeypatch.setattr(relay,'update_presence_hold',no_hold)
    assert asyncio.run(relay.quest_tick(lambda:True))
    assert q.phase=='delivery' and q.index==0 and not relay.hunt.enabled
