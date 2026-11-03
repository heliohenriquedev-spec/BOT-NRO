import copy
import struct
import time
import pytest
from nrobot import quest_library as lib
from nrobot.quest_routes import QuestRoutes
from nrobot.quest_slots import effective_steps
from nrobot.npc_labels import mission_label
from nrobot.portals import PortalGuard


def recipes():
    npc=dict(kind='npc',map='ra_in01',position=[219,95],name='Quadro')
    def s(kind,**values):return dict(kind=kind,map='ra_in01',**values)
    pickup=[npc,s('next'),s('select',option='Aceitar uma missão'),s('select',option='#7 ^FF0000Vázio^000000'),
            s('next'),s('select',option='Rank A-2'),s('next'),s('select',option='Aceitar missão'),s('close')]
    delivery=[npc,s('next'),s('select',option='Completar missão'),s('select',option='#7 Rank A-2'),s('next'),s('close')]
    return lib.validate(dict(missions=[dict(id='model',name='Rank A-2',board_id='vip',pickup_steps=pickup,delivery_steps=delivery,
                                         pickup_confirmation='Tempo restante',delivery_confirmation='Recompensa recebida'),
                                       dict(id='D4',name='Rank D-4',board_id='vip'),dict(id='D5',name='Rank D-5',board_id='vip')]))


@pytest.fixture
def engine(tmp_path):
    q=QuestRoutes();q.start([dict(id='R',name='Rota',enabled=True,mission_ids=['D4','D5'],target_map='field',species=[1034],kills=50,
                               steps=[dict(kind='portal',map='ra_in01',position=[2,2]),dict(kind='wait_map',map='field')])],0,library=recipes())
    q.actors[90]=dict(position=[219,95],name='Quadro');p=PortalGuard(tmp_path/'p')
    q.plan('ra_in01',[219,95],None,p,0)
    return q,p


def put_menu(q,kind,options):
    q.steps=effective_steps(q.library,q.current_mission,q.phase)
    q.dynamic_pickup=q.phase=='pickup';q.dynamic_delivery=q.phase=='delivery'
    q.step=next(i for i,s in enumerate(q.steps) if s['kind']==kind);q.npc=90
    q.dialog=dict(entity_id=90,action='menu',options=options)


def test_explicit_targets_display_even_without_any_matching_sprite(monkeypatch):
    import nrobot.monster_db as db
    monkeypatch.setattr(db,'all_monsters',lambda:[])
    m=lib.enrich_mission(dict(name='Rank D-4'),['Monstros necessários : ^0000FF25 Verme^000000','[Limitações]'])
    assert m['monster_ids']==[] and m['monster_names']==['Verme']
    assert 'Verme' in mission_label(m) and 'nao informados' not in mission_label(m)
    m=lib.enrich_mission(dict(name='Rank C-5'),['Monstros necessários : 35 Barata Macho [Limitações] Base Level : 200'])
    assert m['monster_names']==['Barata Macho']


def test_explicit_target_does_not_add_catalog_substring(monkeypatch):
    import nrobot.monster_db as db
    monkeypatch.setattr(db,'all_monsters',lambda:[dict(species_id=1,name='Guardião'),dict(species_id=2,name='Inseto Guardião')])
    m=lib.enrich_mission(dict(name='Rank S-2'),['Monstros necessários : 50 Inseto Guardião','[Limitações]'])
    assert m['monster_ids']==[2] and m['monster_names']==['Inseto Guardião']


def test_saved_descriptions_backfill_previously_imported_mission():
    data=lib.validate(dict(missions=[dict(id='D4',name='Rank D-4',board_id='vip')],
                           option_details={'vip':{'Rank D-4':['Monstros necessários : 25 Verme']}}))
    assert data['missions'][0]['monster_names']==['Verme']


def test_live_free_slot_replaces_recorded_slot_seven_and_binds_selected_rank(engine):
    q,p=engine;put_menu(q,'select_free_slot',['#1 Rank S-11','#2 ^FF0000Vázio^000000','#3 Vázio'])
    action=q.plan('ra_in01',[219,95],None,p,1)
    assert action==dict(kind='select',entity_id=90,choice=2) and q.slot_number==2
    assert any(s.get('option')=='Rank D-4' for s in q.steps)
    assert not any(s.get('option')=='Rank A-2' for s in q.steps)


def test_all_selected_missions_are_confirmed_in_new_slots_before_return(engine):
    q,p=engine
    for identity,number,options in [('D4',2,['#1 Rank S-11','#2 Vázio','#3 Vázio']),('D5',3,['#1 Rank S-11','#2 Rank D-4','#3 Vázio'])]:
        assert q.current_mission['id']==identity
        put_menu(q,'select_free_slot',options);action=q.plan('ra_in01',[219,95],None,p,1);q.sent(action,1)
        assert q.slot_number==number
        put_menu(q,'verify_slot',['#1 Rank S-11','#2 Rank D-4']+(['#3 Rank D-5'] if number==3 else []))
        q.plan('ra_in01',[219,95],None,p,2)
        assert q.stage_confirmed
        q.sent(q.plan('ra_in01',[219,95],None,p,3),3)
        q.plan('ra_in01',[219,95],None,p,4)
    assert q.completed_missions['pickup']==['D4','D5'] and q.phase=='return'


def test_already_active_mission_is_not_accepted_twice(engine):
    q,p=engine;put_menu(q,'select_free_slot',['#1 Rank D-4','#2 Rank S-11'])
    assert q.plan('ra_in01',[219,95],None,p,1) is None
    action=q.plan('ra_in01',[219,95],None,p,2)
    assert action['kind']=='cancel'
    q.sent(action,2);q.plan('ra_in01',[219,95],None,p,3)
    assert q.completed_missions['pickup']==['D4'] and q.current_mission['id']=='D5'


def test_full_slots_pause_without_abandoning_missions(engine):
    q,p=engine;put_menu(q,'select_free_slot',['#1 Rank S-11','#2 Rank A-3'])
    assert q.plan('ra_in01',[219,95],None,p,1) is None
    assert q.phase=='paused' and 'Sem slots livres' in q.reason and q.completed_missions['pickup']==[]


def test_wrong_or_missing_allocation_does_not_confirm_pickup(engine):
    q,p=engine;q.slot_number=2;put_menu(q,'verify_slot',['#1 Rank S-11','#2 Vázio'])
    q.plan('ra_in01',[219,95],None,p,1)
    assert q.phase=='paused' and not q.stage_confirmed


def test_delivery_uses_current_mission_slot_and_requires_ack(engine):
    q,p=engine;q.enter_stage('delivery',0)
    put_menu(q,'select_mission_slot',['#3 Rank D-4','#5 Rank S-11'])
    assert q.plan('ra_in01',[219,95],None,p,1)['choice']==1
    put_menu(q,'verify_slot_absent',['#3 Vázio','#5 Rank S-11'])
    q.plan('ra_in01',[219,95],None,p,2)
    assert q.phase=='paused' and not q.stage_confirmed


def test_return_recording_survives_npc_disappearance_and_late_close(tmp_path,monkeypatch):
    from nrobot.session_relay import SessionRelay
    monkeypatch.setattr(lib,'FILE',tmp_path/'library.json')
    r=SessionRelay('127.0.0.1',folder=tmp_path);r.upstream=object()
    o=r.tracker.observer;o.player_id=1;o.player=[219,95];o.player_at=time.monotonic();o.map_name='ra_in01'
    r.library_control('quest_library_record',dict(scope='return',board_id='vip'))
    q=r.quests;q.actors[110000001]=dict(position=[213,81],name='Retorno',species_id=837)
    q.native(0x90,struct.pack('<HIB',0x90,110000001,1),'ra_in01')
    q.observe([dict(kind='map_change',map='hospital2',position=[5,5])],1,'hospital2',time.monotonic())
    assert q.recording['finished_at_transition'] and not q.actors
    q.native(0x146,struct.pack('<HI',0x146,110000001),'hospital2')
    q.native(0x90,struct.pack('<HIB',0x90,110000001,1),'hospital2')
    o.player=None;o.map_name=None  # saving does not depend on seeing the old NPC or remaining connected
    r.library_control('quest_library_save',{})
    steps=lib.load()['return_paths']['vip']['steps']
    assert steps[-1]==dict(kind='walk',map='hospital2',position=[5,5])


def test_sala_vip_can_be_resolved_before_name_reply(tmp_path):
    q=QuestRoutes();q.start_validation([dict(kind='npc',map='areia',position=[144,195],name='Sala Vip#1')],'ra_in01',0,mode='travel',label='VIP')
    q.actors[110000001]=dict(position=[144,195],species_id=837)
    q.actors[2000001]=dict(position=[144,195],name='Sala Vip',species_id=837)
    action=q.plan('areia',[144,194],None,PortalGuard(tmp_path/'p'),1)
    assert action['kind']=='npc' and action['entity_id']==110000001


def test_all_mission_stage_test_waits_until_every_selected_mission_and_return(tmp_path):
    q=QuestRoutes();q.start_validation([],'field',0,mode='pickup',label='Coleta da rota',library=recipes(),mission_ids=['D4','D5'])
    p=PortalGuard(tmp_path/'p')
    q.steps=[];q.stage_confirmed=True;q.plan('ra_in01',[219,95],None,p,1)
    assert q.current_mission['id']=='D5' and not q.validation['completed']
    q.steps=[];q.stage_confirmed=True;q.plan('ra_in01',[219,95],None,p,2)
    assert q.phase=='return' and q.completed_missions['pickup']==['D4','D5']
    q.actors[90]=dict(position=[213,81],name='Retorno');q.sent(q.plan('ra_in01',[213,81],None,p,3),3)
    q.observe([dict(kind='map_change',map='hospital2',position=[5,5])],1,'hospital2',4)
    q.plan('hospital2',[5,5],None,p,4);q.plan('hospital2',[5,5],None,p,5)
    assert q.validation['completed'] and q.phase=='done' and q.index==0


def test_delivery_ack_and_current_slot_removal_confirm_delivery(engine):
    q,p=engine;q.enter_stage('delivery',0);put_menu(q,'verify_slot_absent',['#3 Vázio','#5 Rank S-11'])
    q.delivery_ack=True;q.plan('ra_in01',[219,95],None,p,1)
    assert q.stage_confirmed and q.phase=='delivery'


def test_template_example_does_not_replace_different_selected_rank_metadata(tmp_path,monkeypatch):
    from nrobot.session_relay import SessionRelay
    monkeypatch.setattr(lib,'FILE',tmp_path/'library.json')
    data=recipes();wanted=lib.mission(data,'D4');wanted.update(description='Monstros necessários : 25 Verme',monster_names=['Verme'])
    lib.save(data)
    r=SessionRelay('127.0.0.1',folder=tmp_path);q=r.quests;q.record('D4','pickup')
    q.recording.update(scope='mission',board_id='vip',steps=lib.mission(data,'model')['pickup_steps'],observed_texts=['Tempo restante','Monstros necessários : 50 Gremlin'])
    r.library_control('quest_library_save',dict(confirmation='Tempo restante'))
    m=lib.mission(lib.load(),'D4')
    assert m['rank']=='Rank D-4' and m['monster_names']==['Verme']
