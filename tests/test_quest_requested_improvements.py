import copy
import time
from datetime import date
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QMessageBox
from nrobot import quest_daily,quest_library,quest_routes,map_routes
from nrobot.quest_routes import QuestRoutes
from nrobot.mob_scan import MobScan
from nrobot.map_navigation import CollisionMap


def setup_files(tmp_path,monkeypatch):
    monkeypatch.setattr(quest_daily,'FILE',tmp_path/'daily.json')
    monkeypatch.setattr(quest_daily,'CHARACTER','Boa Hancock')
    monkeypatch.setattr(quest_library,'FILE',tmp_path/'library.json')
    monkeypatch.setattr(quest_routes,'FILE',tmp_path/'routes.json')
    monkeypatch.setattr(map_routes,'FILE',tmp_path/'maps.json')
    board=quest_library.BOARDS[0]
    steps=[dict(kind='npc',map=board['map'],position=board['position'],name=board['npc_name']),dict(kind='close',map=board['map'])]
    mission=dict(id='A',name='Rank A-1',rank='Rank A-1',board_id=board['id'],pickup_steps=steps,delivery_steps=steps,
                 pickup_confirmation='Aceita',delivery_confirmation='Entregue')
    access=[dict(kind='portal',map='hospital2',position=[2,2]),dict(kind='wait_map',map='areia'),
            dict(kind='npc',map='areia',position=[144,195],name='Sala Vip'),dict(kind='wait_map',map=board['map']),
            dict(kind='walk',map=board['map'],position=board['position'])]
    library=quest_library.save(dict(missions=[mission],access_paths=[dict(id='access',name='VIP',board_id=board['id'],steps=access)]))
    route=dict(id='R',name='Quest',enabled=True,kills=50,species=[1037],target_map='field',mission_ids=['A'],
               steps=[dict(kind='portal',map=board['map'],position=[1,1]),dict(kind='wait_map',map='field')])
    route=quest_routes.save([route])[0]
    return route,library,board


def test_explicitly_selected_completed_route_travels_and_hunts_without_erasing_daily_marks(tmp_path,monkeypatch):
    route,library,board=setup_files(tmp_path,monkeypatch)
    quest_daily.mark(board['id'],'Rank A-1')
    before=quest_daily.FILE.read_bytes()
    q=QuestRoutes();q.start([route],0,library=library,replay_completed=True)
    assert q.phase=='travel' and q.route['repeat_completed'] and not q.route['lifecycle_enabled']
    assert quest_daily.FILE.read_bytes()==before and q.route['kills']==50
    saved=q.progress_state();assert saved['replay_completed']
    route['enabled']=False
    q.stop();q.resume_from([route],saved,1,library=library,map_name='hospital2')
    assert q.route['repeat_completed'] and q.phase=='travel'


def test_completed_routes_start_unchecked_but_manual_selection_is_kept(tmp_path,monkeypatch):
    route,library,board=setup_files(tmp_path,monkeypatch)
    quest_daily.mark(board['id'],'Rank A-1')
    from nrobot.quest_panel import QuestPanel
    p=QuestPanel()
    item=p.list.item(0)
    assert item.checkState()==Qt.Unchecked and not quest_routes.load()[0]['enabled']
    item.setCheckState(Qt.Checked)
    p.reload()
    assert p.list.item(0).checkState()==Qt.Checked and quest_routes.load()[0]['enabled']
    p.close()


def test_travel_only_from_another_character_uses_shared_vip_access(tmp_path,monkeypatch):
    route,library,board=setup_files(tmp_path,monkeypatch)
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_hunt import PacketHunt
    r=SessionRelay('127.0.0.1',folder=tmp_path/'session',allow_commands=True)
    r.hunt=PacketHunt();r.apply_settings({});r.upstream=object()
    r.own_look={'name':'Outro usuario'};r.tracker.observer.map_name='hospital2'
    r.quest_control('quest_test_route',{'route_id':'R'},lambda:True)
    q=r.quests
    assert q.validation['mode']=='travel' and q.steps[0]['map']=='hospital2'
    itinerary=q.itinerary('hospital2')
    assert itinerary[0]['map']=='hospital2'
    assert any(s.get('name')=='Sala Vip' for s in itinerary)
    assert itinerary[-1]['map']=='field'


def test_showmobs_chooses_largest_combined_group_across_three_species():
    scan=MobScan();scan.start('field',[1,2,3],0,True)
    def add(species,now,points):
        scan.sent(species,now)
        scan.observe([dict(kind='viewpoint',mark_type=1,npc_id=10000+species*100+i,position=p) for i,p in enumerate(points)],now+.1)
    add(1,0,[[10,10],[11,10],[12,10],[13,10],[60,60],[61,60]])
    add(2,4,[[60,61],[61,61]])
    add(3,8,[[60,62],[61,62]])
    found=scan.finish([5,5],12)
    assert found['monsters']==6 and found['species_counts']=={1:2,2:2,3:2}
    assert found['position'][0]>50


def test_repeated_mark_does_not_inflate_density_and_unreachable_group_is_ignored():
    scan=MobScan();scan.start('field',[1],0,True);scan.sent(1,0)
    events=[dict(kind='viewpoint',mark_type=1,npc_id=i+100,position=p) for i,p in enumerate([[5,5],[6,5],[5,6],[30,30],[31,30],[30,31],[31,31]])]
    scan.observe(events+events,.1)
    cells=[1]*1600
    for y in range(40):cells[y*40+20]=0
    collision=CollisionMap(40,40,cells)
    found=scan.finish([2,2],4,collision.walkable,collision=collision)
    assert found['monsters']==3 and found['total']==3 and found['route_cells'] is not None


def test_update_requires_five_seconds_and_confirmation(monkeypatch):
    import nrobot.update_panel as module
    class Clock:
        elapsed_ms=0
        def start(self):pass
        def elapsed(self):return self.elapsed_ms
    monkeypatch.setattr(module,'QElapsedTimer',Clock)
    p=module.UpdatePanel();calls=[];p.run=lambda action:calls.append(action)
    p.apply();dialog=p.confirm_dialog;yes=dialog.button(QMessageBox.Yes)
    assert not yes.isEnabled() and not calls
    Clock.elapsed_ms=4999;dialog.findChild(QTimer).timeout.emit();assert not yes.isEnabled()
    Clock.elapsed_ms=5000;dialog.findChild(QTimer).timeout.emit();assert yes.isEnabled() and not calls
    dialog.done(QMessageBox.No);assert not calls
    Clock.elapsed_ms=0;p.apply();dialog=p.confirm_dialog
    Clock.elapsed_ms=5000;dialog.findChild(QTimer).timeout.emit();dialog.done(QMessageBox.Yes)
    assert calls==['apply'];p.close()


def test_early_programmatic_confirmation_cannot_bypass_update_countdown(monkeypatch):
    import nrobot.update_panel as module
    class Clock:
        def start(self):pass
        def elapsed(self):return 0
    monkeypatch.setattr(module,'QElapsedTimer',Clock)
    p=module.UpdatePanel();calls=[];p.run=lambda action:calls.append(action)
    p.apply();p.confirm_dialog.done(QMessageBox.Yes)
    assert calls==[];p.close()


def test_default_route_path_respects_runtime_isolation(tmp_path,monkeypatch):
    path=tmp_path/'isolated'/'routes.json'
    monkeypatch.setattr(quest_routes,'FILE',path)
    assert quest_routes.load()==[]
    route=dict(id='isolation',name='Isolation',enabled=False,kills=1,species=[1037],target_map='field',steps=[])
    quest_routes.save([route])
    assert path.exists() and quest_routes.load()[0]['id']=='isolation'
