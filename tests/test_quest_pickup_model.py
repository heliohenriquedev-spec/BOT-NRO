"""One recorded "pegar" teaches every mission of both boards; slots are checked without extra visits."""
from nrobot import quest_library as lib
from nrobot.quest_routes import QuestRoutes
from nrobot.quest_slots import effective_steps
from nrobot.portals import PortalGuard

MODEL=[dict(kind='npc',map='ra_in01.gat',position=[219,95],name='Quadro de missões#3'),dict(kind='next',map='ra_in01.gat'),
       dict(kind='select',map='ra_in01.gat',option='Aceitar uma missão'),dict(kind='select',map='ra_in01.gat',option='#1 ^FF0000Vázio^000000'),
       dict(kind='next',map='ra_in01.gat'),dict(kind='select',map='ra_in01.gat',option='Rank A-2'),dict(kind='next',map='ra_in01.gat'),
       dict(kind='select',map='ra_in01.gat',option='Aceitar missão'),dict(kind='close',map='ra_in01.gat')]
EMPTY='^FF0000Vázio^000000'
BOARD=90


def data(*missions):
    return lib.validate(dict(missions=[dict(id=i,name=n,menu_option=n,board_id=b) for i,n,b in missions],
                             board_templates={'vip':{'pickup':dict(steps=MODEL,confirmation='Tempo restante')}}))


def slots(*taken):
    labels=dict(taken)
    return ['#%d %s'%(n,'^0000FF'+labels[n]+'^000000' if n in labels else EMPTY) for n in range(1,9)]


class Board:
    """Plays the board script for the executor; `refuse` ranks are not accepted."""
    def __init__(self,q,map_name,position,refuse=(),done=()):
        self.q,self.map,self.position,self.taken,self.refuse,self.done=q,map_name,position,{},set(refuse),set(done)
        self.p=PortalGuard();self.t=0;self.sent=[]

    def say(self,*events):
        self.q.observe([dict(kind='npc_dialog',entity_id=BOARD,**e) for e in events],1,self.map,self.t)

    def run(self,limit=200):
        menu=None;rank=None
        for _ in range(limit):
            self.t+=1
            action=self.q.plan(self.map,self.position,None,self.p,self.t)
            if not self.q.active or self.q.phase in ('return','travel'):return
            if action is None:continue
            self.q.sent(action,self.t);self.sent.append(action)
            kind=action['kind']
            if kind=='npc':self.say(dict(action='text',text='[Quadro de missões]'),dict(action='next'));menu='start'
            elif kind=='next' and menu=='start':self.say(dict(action='menu',options=['Completar missão','Desistir de uma missão','Aceitar uma missão','']));menu='main'
            elif kind=='select' and menu=='main':self.say(dict(action='menu',options=slots(*self.taken.items())));menu='slots'
            elif kind=='select' and menu=='slots':self.slot=action['choice'];self.say(dict(action='next'));menu='ranks'
            elif kind=='next' and menu=='ranks':self.say(dict(action='menu',options=['^0000FFRank D-1','Rank A-2','Rank B-1','Rank S-11^000000']));menu='rank'
            elif kind=='select' and menu=='rank':rank=['Rank D-1','Rank A-2','Rank B-1','Rank S-11'][action['choice']-1];self.say(dict(action='text',text=rank),dict(action='text',text='Status : '+('Completa' if rank in self.done else 'Incompleta')),dict(action='next'));menu='desc'
            elif kind=='next' and menu=='desc':self.say(dict(action='menu',options=['Aceitar missão','Escolher outra']));menu='accept'
            elif kind=='select' and menu=='accept':
                if rank in self.done:
                    self.say(dict(action='text',text='Você já completou esta missão'),dict(action='next'));menu='refused'
                elif rank in self.refuse:
                    self.say(dict(action='text',text='[Quadro de missões]'),dict(action='text',text='Seu nível é baixo para este rank.'),dict(action='next'));menu='refused'
                else:
                    self.taken[self.slot]=rank;self.say(dict(action='text',text='Tempo restante : 1 horas'),dict(action='close'));menu=None
            elif kind=='next' and menu=='refused':self.say(dict(action='close'));menu=None
            elif kind in ('close','cancel'):menu=None


def test_kakashi_mission_uses_the_vip_recording_without_its_own():
    d=data(('k','Rank B-1','kakashi'))
    steps=effective_steps(d,lib.mission(d,'k'),'pickup')
    lib.validate_conversation(steps,lib.board(d,'kakashi'))
    assert steps[0]['position']==[87,140] and steps[3]==dict(kind='select_free_slot',map='kakashi',option='Rank B-1')
    lib.ready_mission  # delivery still needs its own model; pickup does not
    q=QuestRoutes();q.start_validation([],'kakashi',0,mode='pickup',label='t',library=d,mission_id='k')
    q.actors[BOARD]=dict(position=[87,140],name='Quadro de missões#4')
    board=Board(q,'kakashi',[87,141]);board.run()
    assert board.taken=={1:'Rank B-1'} and q.completed_missions['pickup']==['k'] and q.phase=='return'


def test_missions_of_one_board_skip_the_extra_reopening_but_are_still_checked():
    d=data(('a','Rank A-2','vip'),('b','Rank B-1','vip'))
    q=QuestRoutes();q.start_validation([],'ra_in01',0,mode='pickup',label='t',library=d,mission_ids=['a','b'])
    q.actors[BOARD]=dict(position=[219,95],name='Quadro de missões#3')
    board=Board(q,'ra_in01',[219,96]);board.run()
    assert board.taken=={1:'Rank A-2',2:'Rank B-1'} and q.phase=='return'
    # first mission: one visit (proved by the second one's slot menu); last one: visit + check
    assert sum(a['kind']=='npc' for a in board.sent)==3


def test_refused_mission_stops_with_the_board_answer():
    d=data(('a','Rank S-11','vip'),('b','Rank B-1','vip'))
    q=QuestRoutes();q.start_validation([],'ra_in01',0,mode='pickup',label='t',library=d,mission_ids=['a','b'])
    q.actors[BOARD]=dict(position=[219,95],name='Quadro de missões#3')
    board=Board(q,'ra_in01',[219,96],refuse={'Rank S-11'});board.run()
    assert q.phase=='paused' and 'Rank S-11' in q.reason and 'nível é baixo' in q.reason
    assert board.taken=={}


def test_unrecorded_confirmation_after_accepting_is_answered_yes():
    d=data(('a','Rank A-2','vip'))
    q=QuestRoutes();q.start_validation([],'ra_in01',0,mode='pickup',label='t',library=d,mission_id='a')
    q.steps=effective_steps(d,lib.mission(d,'a'),'pickup');q.step=8;q.npc=BOARD
    q.steps[7]['option']='Aceitar missão'
    q.dialog=dict(entity_id=BOARD,action='menu',options=['Sim','Não'])
    assert q.plan('ra_in01',[219,96],None,PortalGuard(),1)==dict(kind='select',entity_id=BOARD,choice=1,extra=True)
    q.dialog=dict(entity_id=BOARD,action='menu',options=['Konoha','Suna'])
    assert q.plan('ra_in01',[219,96],None,PortalGuard(),2)==dict(kind='cancel',entity_id=BOARD,choice=255,extra=True)


def test_daily_mission_already_done_is_skipped_and_the_others_are_taken():
    d=data(('s','Rank S-11','vip'),('b','Rank B-1','vip'))
    q=QuestRoutes();q.start_validation([],'ra_in01',0,mode='pickup',label='t',library=d,mission_ids=['s','b'])
    q.actors[BOARD]=dict(position=[219,95],name='Quadro de missões#3')
    board=Board(q,'ra_in01',[219,96],done={'Rank S-11'});board.run()
    assert q.phase=='return' and board.taken=={1:'Rank B-1'}
    assert q.completed_missions['pickup']==['b'] and q.skipped[0].startswith('Rank S-11: ja completada')
    # it never pressed "Aceitar missao" for the completed one
    assert sum(a['kind']=='select' and a.get('choice')==1 and not a.get('extra') for a in board.sent)>=1


def test_refusal_after_accepting_already_done_is_skipped_too():
    d=data(('s','Rank S-11','vip'),('b','Rank B-1','vip'))
    q=QuestRoutes();q.start_validation([],'ra_in01',0,mode='pickup',label='t',library=d,mission_ids=['s','b'])
    q.actors[BOARD]=dict(position=[219,95],name='Quadro de missões#3')
    q.already_done=lambda:any('completou' in t for t in q.npc_texts)  # description without status line
    board=Board(q,'ra_in01',[219,96],done={'Rank S-11'});board.run()
    assert q.phase=='return' and board.taken=={1:'Rank B-1'} and q.completed_missions['pickup']==['b']
    assert len(q.skipped)==1
