"""Persistent quest itineraries and a server-confirmed, non-combat route state machine.

NPC menus are matched by text, never by a saved selection index or entity ID.
No arbitrary packet payloads, purchases, input boxes or chat commands are replayed.
"""
from __future__ import annotations
import copy
import json
import re
import time
import uuid
from pathlib import Path
from .portals import PortalGuard, chebyshev
from .npc_labels import clean

FILE = Path(__file__).resolve().parents[1]/'data/rede/rotas_quests.json'
KINDS = {'walk','portal','npc','next','select','close','cancel','wait_map','wait_transfer','select_free_slot','select_mission_slot','verify_slot','verify_slot_absent'}
STAGES = {'pickup':'Pegar quests','travel':'Rota da quest','delivery':'Entregar quests','return':'Retornar ao ponto salvo'}
STAGE_FIELDS = {'pickup':'pickup_steps','travel':'steps','delivery':'delivery_steps'}
DIALOG = {'next':'next','select':'menu','cancel':'menu','close':'close','select_free_slot':'menu','select_mission_slot':'menu',
          'verify_slot':'menu','verify_slot_absent':'menu'}


def text(value):
    return clean(value).casefold()


def validate_routes(data):
    if not isinstance(data, list) or len(data)>100: raise ValueError('Limite de 100 quests')
    result = copy.deepcopy(data)
    seen = set()
    for route in result:
        route.setdefault('id', uuid.uuid4().hex)
        route.setdefault('enabled', True);route.setdefault('kills', 1);route.setdefault('species', [])
        route.setdefault('steps', []);route.setdefault('target_map', '')
        route.setdefault('lifecycle_enabled',False)
        route.setdefault('mission_ids',[])
        if (not isinstance(route['mission_ids'],list) or len(route['mission_ids'])>100
            or any(not isinstance(i,str) or not i for i in route['mission_ids'])
            or len(set(route['mission_ids']))!=len(route['mission_ids'])):raise ValueError('Missoes selecionadas invalidas/duplicadas')
        if route['mission_ids']:route['lifecycle_enabled']=True
        for field in ('pickup_steps','delivery_steps'):route.setdefault(field,[])
        for field in ('pickup_confirmation','delivery_confirmation'):
            route.setdefault(field,'')
            if not isinstance(route[field],str) or len(route[field])>1000:raise ValueError('Texto de confirmacao invalido')
        if type(route['lifecycle_enabled']) is not bool:raise ValueError('Ciclo de quest invalido')
        route.setdefault('needs_recording', False)
        if type(route['needs_recording']) is not bool: raise ValueError('Estado da gravacao invalido')
        # Contador por monstro: [{'name', 'count', 'species': [ids]}]; empty = total in 'kills'.
        route.setdefault('chain_next',False)
        if type(route['chain_next']) is not bool:raise ValueError('Encadeamento de rota invalido')
        route.setdefault('ignore_finished',False);route.setdefault('always_attack',[])
        if type(route['ignore_finished']) is not bool or not isinstance(route['always_attack'],list) or any(
            type(i) is not int or not 1<=i<=65535 for i in route['always_attack']):raise ValueError('Opcoes de monstros ignorados invalidas')
        route.setdefault('map_route_id','')
        if not isinstance(route['map_route_id'],str):raise ValueError('Mapa de caca invalido')
        route.setdefault('kill_targets',[])
        if not isinstance(route['kill_targets'],list) or len(route['kill_targets'])>50:raise ValueError('Contador de monstros invalido')
        for target in route['kill_targets']:
            if (not isinstance(target,dict) or not isinstance(target.get('name'),str) or not target['name'].strip()
                or type(target.get('count')) is not int or not 1<=target['count']<=100000
                or not isinstance(target.get('species'),list) or not target['species']
                or any(type(i) is not int or not 1<=i<=65535 for i in target['species'])):
                raise ValueError('Contador: informe monstro, quantidade e IDs de cada alvo')
        if not isinstance(route.get('name'),str) or not route['name'].strip(): raise ValueError('Informe o nome da quest')
        if not isinstance(route['id'],str) or route['id'] in seen: raise ValueError('Quest duplicada')
        seen.add(route['id'])
        if type(route['enabled']) is not bool or type(route['kills']) is not int or not 1<=route['kills']<=100000:
            raise ValueError('Quantidade de mortes invalida')
        if not isinstance(route['species'],list) or any(type(i) is not int or not 1<=i<=65535 for i in route['species']):
            raise ValueError('Informe os IDs de aparencia dos monstros separados por virgula')
        if not isinstance(route['target_map'],str): raise ValueError('Mapa de destino invalido')
        for field in STAGE_FIELDS.values():
            if not isinstance(route[field],list) or len(route[field])>5000: raise ValueError('Limite de 5000 etapas por trecho')
        for step in sum((route[field] for field in STAGE_FIELDS.values()),[]):
            if not isinstance(step,dict) or step.get('kind') not in KINDS or not isinstance(step.get('map'),str) or not step['map']:
                raise ValueError('Cada etapa precisa de tipo e mapa')
            if step['kind'] in ('walk','portal','npc'):
                p=step.get('position')
                if not isinstance(p,list) or len(p)!=2 or any(type(v) is not int or not 0<=v<1024 for v in p):
                    raise ValueError('Coordenadas invalidas')
            if step['kind']=='select' and not step.get('option'): raise ValueError('Informe o texto da opcao do NPC')
    return result


def load(path=FILE):
    path=Path(path)
    return validate_routes(json.loads(path.read_text(encoding='utf-8'))) if path.exists() else []


def save(routes, path=FILE):
    routes=validate_routes(routes);path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(routes,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
    return routes


class QuestRoutes:
    def __init__(self):
        self.recording=None;self.routes=[];self.index=0;self.step=0;self.phase='idle'
        self.reason='Fila parada';self.dialog=None;self.npc=None;self.sent_at=0;self.pending=None
        self.killed=set();self.hit={};self.kills=0;self.kill_counts={};self.actors={};self.map=None;self.progress_at=0;self.last_position=None
        self.known_routes=[];self.steps=None
        self.stage_confirmed=False;self.last_npc_text=''
        self.library=None;self.mission_index=0;self.completed_missions={'pickup':[],'delivery':[]}
        self.validation=None
        self.return_context=None;self.return_board=None;self.return_seen=None;self.return_sent=False
        self.extra_pages=0;self.deferred_check=None;self.npc_texts=[];self.skipped=[];self.skip_current=False
        self.map_routes=[];self.daily_marks=[];self.direct_failed=set();self.learned=[]
        self.nav_cache={};self.path_cache=None
        self.slot_owner={};self.slots_dirty=False  # slot number -> mission id (both boards share the 8 slots)
        from .quest_extras import Body
        self.body=Body();self.extras=None;self.errands=[];self.mount_displaced=None
        self.learning=None;self.learned_extras=None;self.aggressors=set();self.printed_notice=''
        self.voltar_sent_at=-1e9  # the server answers to @voltar are traced for 15 s
        self.borrow=None;self.prefetched={};self.skipped_ids=set()
        self.voltar_fallback=None;self.resume=None
        self.chain=None  # linked routes: one pickup, one map after the other, one delivery
        self.dynamic_pickup=False;self.dynamic_delivery=False;self.slot_number=None;self.delivery_ack=False

    @property
    def active(self): return self.phase in ('pickup','travel','hunt','delivery','return')
    @property
    def route(self): return self.routes[self.index] if self.index<len(self.routes) else None

    @property
    def current_mission(self):
        if not self.route or self.phase not in ('pickup','delivery'):return None
        from .quest_library import mission
        if self.borrow and self.phase=='pickup':
            return mission(self.library,self.borrow['ids'][self.borrow['pos']])  # next route's, taken on this visit
        if not self.route['mission_ids']:return None
        return mission(self.library,self.route['mission_ids'][self.mission_index])

    def confirmation(self):
        if self.current_mission:
            if self.dynamic_pickup or self.dynamic_delivery:return ''  # proved by the slots
            from .quest_slots import confirmation
            return confirmation(self.library,self.current_mission,self.phase)
        return (self.current_mission or self.route)[self.phase+'_confirmation']

    def start(self,routes,now,library=None,map_routes=None):
        self.validation=None;self.borrow=None;self.prefetched={};self.voltar_fallback=None;self.resume=None;self.chain=None
        self.map_routes=list(map_routes or [])
        self.known_routes=validate_routes(routes)
        self.routes=[copy.deepcopy(r) for r in self.known_routes if r['enabled']]
        if not self.routes: raise ValueError('Marque ao menos uma quest')
        self.library=None
        if any(r['mission_ids'] for r in self.routes):
            from .quest_library import load,validate,ready_mission
            self.library=validate(library) if library is not None else load()
            for r in self.routes:
                for identity in r['mission_ids']:ready_mission(self.library,identity)
        from .quest_library import board_rank
        for r in self.routes:
            if r['mission_ids'] and self.library:
                r['mission_ids']=sorted(r['mission_ids'],key=lambda i:board_rank(self.library,i))
            if r['needs_recording']:raise ValueError('Grave o percurso completo antes de executar: '+r['name'])
            if r['mission_ids'] and self.library:
                # The missions say what to kill ("Monstros necessarios"); nothing typed in the route.
                from .quest_library import kill_targets
                r['kill_targets']=kill_targets(self.library,r['mission_ids'])
            # Every counted monster is hunted until all counters are done, finished ones included.
            r['species']=sorted(set(r['species']).union(*(t['species'] for t in r['kill_targets'])))
            if not r['steps'] or not r['target_map']:raise ValueError('Escolha o mapa de caca da quest '+r['name'])
            if not r['species'] and not r['mission_ids']:raise ValueError('Complete os monstros da quest '+r['name'])
            if r['lifecycle_enabled'] and not r['mission_ids']:
                for phase in ('pickup','delivery'):
                    if (not r[STAGE_FIELDS[phase]] or not text(r[phase+'_confirmation'])
                        or not any(s['kind']=='npc' for s in r[STAGE_FIELDS[phase]])):
                        raise ValueError('Configure o trecho e a confirmacao de '+STAGES[phase]+': '+r['name'])
        self.index=0;self.recording=None;self.begin(now)

    def start_validation(self,steps,target_map,now,*,mode,label,library=None,mission_id=None,target_position=None,return_board=None,mission_ids=None,map_routes=None):
        if self.active or self.recording:raise ValueError('Pause a fila e encerre a gravacao antes de testar')
        self.map_routes=list(map_routes or []);self.borrow=None;self.prefetched={}
        if mode not in ('access','travel','pickup','delivery','return'):raise ValueError('Teste desconhecido')
        route=validate_routes([dict(name=label,id='validation',target_map=target_map,steps=steps,
                                   mission_ids=mission_ids if mission_ids is not None else [mission_id] if mission_id else [])])[0]
        self.routes=[route];self.index=0;self.known_routes=[];self.library=copy.deepcopy(library)
        self.completed_missions={'pickup':[],'delivery':[]};self.kills=0;self.deferred_check=None;self.skipped=[]
        self.enter_stage(mode if mode in ('pickup','delivery','return') else 'travel',now)
        if not route['mission_ids'] and mode!='return':self.steps=copy.deepcopy(steps)
        if mode=='return':self.return_board=return_board;self.return_context={'validation':True}
        self.validation=dict(mode=mode,label=label,completed=False,target_position=target_position)
        if mission_ids is not None:self.validation['all_missions']=True
        self.reason='Testando: '+label

    def complete_validation(self):
        self.validation['completed']=True;self.phase='done';self.pending=None
        self.reason='Teste concluido: '+self.validation['label']+self.skipped_note()

    def begin(self,now):
        self.kills=0;self.kill_counts={};self.killed.clear();self.hit.clear();self.aggressors=set()
        self.completed_missions={'pickup':[],'delivery':[]};self.deferred_check=None;self.skipped=[];self.skipped_ids=set()
        chain=self.chain_indices(self.index)
        if len(chain)>1 and self.library:
            self.chain=dict(indices=chain,own={str(k):list(self.routes[k]['mission_ids']) for k in chain})
            self.route['mission_ids']=self.chain_missions(self.index)
            print('[ROTA] Cadeia: '+' -> '.join(self.routes[k]['name'] for k in chain)+' (pega tudo, um mapa de cada vez, entrega tudo)')
        early=self.prefetched.pop(self.index,None)
        if early and self.route['lifecycle_enabled']:
            # Taken while delivering the previous route on the same boards.
            self.completed_missions['pickup']=[i for i in self.route['mission_ids'] if i in early['picked']]
            self.skipped=list(early['notes']);self.skipped_ids=set(early['skipped'])
            first=self.pending_index('pickup',0)
            if first>=len(self.route['mission_ids']):
                self.phase='pickup';self.after_pickup(now);return
            self.enter_stage('pickup',now,first);return
        self.enter_stage('pickup' if self.route['lifecycle_enabled'] else 'travel',now)

    def enter_stage(self,phase,now,mission_index=0):
        self.step=0;self.phase=phase
        if phase!='return':self.last_stage=(phase,mission_index)
        self.pending=None;self.dialog=None;self.npc=None;self.progress_at=now;self.last_position=None
        self.steps=None
        self.stage_confirmed=False;self.last_npc_text=''
        self.dynamic_pickup=False;self.dynamic_delivery=False;self.slot_number=None;self.delivery_ack=False
        self.return_seen=None;self.return_sent=False
        self.extra_pages=0;self.npc_texts=[];self.skip_current=False
        self.mission_index=mission_index
        self.reason=STAGES.get(phase,phase)+': '+self.route['name']
        if self.borrow and phase=='pickup':self.reason='Pegar quests da proxima rota: '+self.routes[self.borrow['route']]['name']
        if self.current_mission:self.reason+=' / '+self.current_mission['name']
        if phase in ('pickup','travel','delivery'):self.queue('mount',now)  # trips are made mounted

    def start_return(self,board_id,now,context):
        self.return_context=context;self.return_board=board_id;self.enter_stage('return',now)

    def after_board(self,phase,next_index,now):
        if next_index<len(self.route['mission_ids']):self.enter_stage(phase,now,next_index)
        elif self.validation and self.validation.get('all_missions'):self.complete_validation()
        elif phase=='pickup':self.after_pickup(now)
        else:self.advance(now)

    def chain_indices(self,index):
        """Routes linked from index on ("Encadear com a proxima rota"), all with missions."""
        result=[index]
        while (result[-1]+1<len(self.routes) and self.routes[result[-1]].get('chain_next')
               and self.routes[result[-1]]['lifecycle_enabled'] and self.routes[result[-1]+1]['mission_ids']):
            result.append(result[-1]+1)
        return result if self.routes[index]['mission_ids'] else [index]

    def chain_missions(self,index):
        """Every mission of the chain starting at index, Kakashi first, without repeats."""
        from .quest_library import board_rank
        ids=[]
        for k in self.chain_indices(index):
            for i in (self.chain or {}).get('own',{}).get(str(k),self.routes[k]['mission_ids']):
                if i not in ids:ids.append(i)
        return sorted(ids,key=lambda i:board_rank(self.library,i)) if self.library else ids

    def narrow(self,route,picked):
        """Hunt only for the missions that were taken, with counters from them."""
        from .quest_library import kill_targets
        route['mission_ids']=picked
        try:
            route['kill_targets']=kill_targets(self.library,picked,require=True)
            route['species']=sorted(set().union(*(t['species'] for t in route['kill_targets'])))
        except ValueError as exc:
            if not route['species']:raise
            route['kill_targets']=kill_targets(self.library,picked)
            route['species']=sorted(set(route['species']).union(*(t['species'] for t in route['kill_targets'])))

    def chain_after_pickup(self,now):
        """Each linked route keeps its own missions taken; the first map that has some is hunted first."""
        picked=[i for i in self.route['mission_ids'] if i in self.completed_missions['pickup']]
        self.chain['picked']=picked
        hunting=[]
        for k in self.chain['indices']:
            own=[i for i in self.chain['own'][str(k)] if i in picked]
            if own:
                try:self.narrow(self.routes[k],own)
                except ValueError as exc:self.stop(str(exc));return
                hunting.append(k)
        if not hunting:
            self.reason='Nenhuma missao pega na cadeia'+self.skipped_note()+'; proxima rota'
            print('[ROTA] '+self.reason);self.index=self.chain['indices'][-1];self.chain=None;self.advance(now);return
        self.chain['hunting']=hunting;self.index=hunting[0]
        self.completed_missions['pickup']=list(picked)
        self.enter_stage('travel',now)

    def after_pickup(self,now):
        """Missions skipped (done today) are neither hunted for nor delivered."""
        if self.chain and self.index==self.chain['indices'][0] and 'picked' not in self.chain:
            self.chain_after_pickup(now);return
        route=self.route;picked=[i for i in route['mission_ids'] if i in self.completed_missions['pickup']]
        if route['mission_ids'] and self.library:
            if not picked:
                self.reason='Nenhuma missao pega em '+route['name']+self.skipped_note()+'; proxima rota'
                print('[ROTA] '+self.reason);self.advance(now);return
            from .quest_library import kill_targets
            route['mission_ids']=picked
            try:
                route['kill_targets']=kill_targets(self.library,picked,require=True)
                route['species']=sorted(set().union(*(t['species'] for t in route['kill_targets'])))  # picked missions only
            except ValueError as exc:
                if not route['species']:self.stop(str(exc));return
                route['kill_targets']=kill_targets(self.library,picked)  # older route: its own monsters and total
                route['species']=sorted(set(route['species']).union(*(t['species'] for t in route['kill_targets'])))
        self.enter_stage('travel',now)

    def finish_hunt(self,now):
        if self.chain and 'hunting' in self.chain and self.index in self.chain['hunting']:
            following=self.chain['hunting'][self.chain['hunting'].index(self.index)+1:]
            if following:
                # This map is done: on to the next map of the chain, no delivery yet.
                print('[ROTA] Mapa concluido; seguindo para '+self.routes[following[0]]['target_map']+' ('+self.routes[following[0]]['name']+')')
                self.index=following[0];self.kills=0;self.kill_counts={};self.killed.clear();self.hit.clear();self.aggressors=set()
                self.enter_stage('travel',now);return
            # Last map: every mission of the chain is delivered together.
            self.route['mission_ids']=self.chain_missions(self.chain['indices'][0])
            self.route['mission_ids']=[i for i in self.route['mission_ids'] if i in self.chain['picked']]
            self.completed_missions['pickup']=list(self.route['mission_ids'])
        self.queue('voltar',now)  # leave the hunting map before anything else
        if self.route['lifecycle_enabled']:self.enter_stage('delivery',now)
        else:self.advance(now)

    def stop(self,reason='Fila pausada'):
        self.phase='paused';self.pending=None;self.reason=reason;self.errands=[]

    def queue(self,kind,now,force=False):
        """@voltar after the hunt, mount before trips, combat equipment before hunting (if set up)."""
        extras=self.extras or {}
        mount=extras.get('mount_enabled') and extras.get('mount')
        if kind=='voltar' and not (extras.get('voltar_enabled') or force and extras.get('voltar_frame')):return
        if kind=='mount' and not mount:return
        if kind=='gear' and not (mount or extras.get('combat_items')):return
        if any(e.kind==kind for e in self.errands):return
        if kind=='mount':self.errands=[e for e in self.errands if e.kind!='gear']
        from .quest_extras import Errand
        config=dict(extras,displaced=self.mount_displaced or (mount or {}).get('displaced') or [])
        self.errands.append(Errand(kind,config,now))

    def errand_done(self):
        errand=self.errands.pop(0)
        if errand.kind=='mount' and errand.displaced:self.mount_displaced=errand.displaced
        if not self.errands and self.route and self.phase in STAGES:
            self.reason=STAGES[self.phase]+': '+self.route['name']+(' / '+self.current_mission['name'] if self.current_mission else '')

    def advance(self,now):
        self.chain=None
        self.index+=1
        if self.route is None: self.phase='done';self.reason='Fila concluida';self.pending=None
        else: self.begin(now)

    def record(self,identity,stage='travel'):
        if self.active: raise ValueError('Pare a fila antes de gravar')
        if stage not in STAGES:raise ValueError('Etapa de gravacao invalida')
        self.validation=None
        self.recording={'id':identity,'stage':stage,'steps':[],
                        'npc_cache':{i:dict(map=self.map,actor=dict(a)) for i,a in list(self.actors.items())[-1000:]}}
        self.reason='Gravando: '+STAGES[stage]

    def append(self,step):
        if self.recording and self.recording.get('finished_at_transition'):return
        if self.recording and (not self.recording['steps'] or self.recording['steps'][-1]!=step
                               or step['kind'] not in ('walk','portal','wait_map')):
            if len(self.recording['steps'])>=5000:
                self.recording['error']='Limite de etapas da gravacao atingido';return
            self.recording['steps'].append(step)

    def native(self,opcode,frame,map_name):
        import struct
        if self.learning:self.learn_frame(opcode,frame)
        if not self.recording: return
        if self.recording.get('finished_at_transition'):return
        if opcode in (0x143,0x1d5,0xc5,0xc8,0xc9):
            self.recording['error']='Gravacao inclui entrada de texto, numero ou loja; este dialogo ainda nao e suportado'
            return
        if opcode==0x90 and len(frame)==7:
            identity=struct.unpack_from('<I',frame,2)[0];actor=self.actors.get(identity)
            old=self.recording.get('last_warp_npc')
            if old and old['id']==identity and PortalGuard.key(old['map'])!=PortalGuard.key(map_name):return
            cached=self.recording.get('npc_cache',{}).get(identity)
            if actor is None and cached and PortalGuard.key(cached['map'])==PortalGuard.key(map_name):actor=cached['actor']
            if actor:
                if self.recording.get('scope')=='menus' and (PortalGuard.key(map_name)!=PortalGuard.key(self.recording['board_map']) or actor['position']!=self.recording['board_position']):
                    self.recording['error']='Grave somente os menus do quadro selecionado';return
                self.recording['npc_id']=identity
                self.recording.pop('selected_mission_option',None)
                self.append(dict(kind='npc',map=map_name,position=list(actor['position']),name=actor.get('name','')))
            else: self.reason='NPC nao recebido; aproxime-se e grave novamente';self.recording['error']=self.reason
        elif opcode in (0xb8,0xb9,0x146):
            expected={0xb8:'menu',0xb9:'next',0x146:'close'}[opcode]
            identity=struct.unpack_from('<I',frame,2)[0] if len(frame)>=6 else None
            old=self.recording.get('last_warp_npc')
            if opcode==0x146 and old and identity==old['id'] and PortalGuard.key(old['map'])!=PortalGuard.key(map_name):return
            if not self.dialog or self.dialog['entity_id']!=identity or self.dialog['action']!=expected:
                self.recording['error']='Dialogo nao confirmado; refaca a gravacao';return
            step=dict(kind={0xb8:'select',0xb9:'next',0x146:'close'}[opcode],map=map_name)
            if opcode==0xb8:
                choice=frame[6] if len(frame)==7 else 0
                if choice==255:
                    step['kind']='cancel';self.append(step);self.dialog=None;return
                if not 1<=choice<=len(self.dialog['options']):
                    self.recording['error']='Selecao cancelada ou invalida';return
                step['option']=self.dialog['options'][choice-1]
                from .npc_labels import mission_option
                from .quest_slots import slot
                chosen_slot=slot(step['option'])
                if chosen_slot and not chosen_slot['empty']:self.recording['selected_mission_option']=chosen_slot['mission']
                elif chosen_slot:self.recording.pop('selected_mission_option',None)
                elif mission_option(step['option']):self.recording['selected_mission_option']=step['option']
            self.append(step);self.dialog=None

    def learn_frame(self,opcode,frame):
        """What the player does once in the game: type @voltar, equip the mount."""
        import struct
        what=self.learning['what']
        if what=='voltar' and opcode==0xf3 and b'@voltar' in frame.lower():
            self.learned_extras=dict(voltar_frame=bytes(frame).hex(),voltar_enabled=True);self.learning=None
            self.reason='@voltar aprendido'
        if opcode==0xf3 and b'@voltar' in frame.lower():self.voltar_sent_at=time.monotonic()
        elif what=='mount' and opcode==0xa9 and len(frame)==6 and 'captured' not in self.learning:
            index,location=struct.unpack_from('<HH',frame,2)
            self.learning['captured']=dict(index=index,location=location,at=time.monotonic())
            self.reason='Montaria enviada pelo jogo; aguardando o servidor'

    def progress_state(self):
        """What is needed to carry the queue on later: route, stage, missions done and kills."""
        if not self.route or self.validation or self.phase=='done':return None
        phase,index=getattr(self,'last_stage',None) or ('pickup',0)
        if self.phase=='return' and self.return_context and not self.return_context.get('validation'):
            phase,index=self.return_context['phase'],self.return_context['next_index']
        return dict(route_id=self.route['id'],route_name=self.route['name'],index=self.index,phase=phase,mission_index=index,
                    mission_ids=list(self.route['mission_ids']),kill_targets=copy.deepcopy(self.route['kill_targets']),
                    species=list(self.route['species']),kill_counts={str(k):v for k,v in self.kill_counts.items()},kills=self.kills,
                    completed_missions=copy.deepcopy(self.completed_missions),skipped=list(self.skipped),
                    skipped_ids=sorted(self.skipped_ids),prefetched=copy.deepcopy({str(k):v for k,v in self.prefetched.items()}),
                    aggressors=sorted(self.aggressors),chain=copy.deepcopy(self.chain),
                    chain_routes={str(k):dict(mission_ids=self.routes[k]['mission_ids'],kill_targets=self.routes[k]['kill_targets'],
                                              species=self.routes[k]['species']) for k in (self.chain or {}).get('indices',[])})

    def resume_from(self,routes,saved,now,library=None,map_routes=None):
        """Start the queue again where it was: same route and stage, missions done kept, kills kept."""
        self.start(routes,now,library=library,map_routes=map_routes)
        index=next((i for i,r in enumerate(self.routes) if r['id']==saved.get('route_id')),None)
        if index is None:raise ValueError('A rota salva nao esta mais marcada na fila: '+str(saved.get('route_name')))
        self.errands=[];self.index=index;route=self.route
        if saved.get('mission_ids') is not None and set(saved['mission_ids'])<=set(route['mission_ids']):
            route['mission_ids']=list(saved['mission_ids'])
        if saved.get('kill_targets'):route['kill_targets']=copy.deepcopy(saved['kill_targets'])
        if saved.get('species'):route['species']=list(saved['species'])
        self.kill_counts={int(k):v for k,v in (saved.get('kill_counts') or {}).items()};self.kills=saved.get('kills',0)
        self.completed_missions=copy.deepcopy(saved.get('completed_missions') or {'pickup':[],'delivery':[]})
        self.skipped=list(saved.get('skipped') or []);self.skipped_ids=set(saved.get('skipped_ids') or [])
        self.prefetched={int(k):v for k,v in (saved.get('prefetched') or {}).items()}
        self.aggressors=set(saved.get('aggressors') or [])
        self.chain=copy.deepcopy(saved.get('chain'))
        for k,values in (saved.get('chain_routes') or {}).items():
            if int(k)<len(self.routes):self.routes[int(k)].update(copy.deepcopy(values))
        phase=saved.get('phase','pickup')
        if phase in ('pickup','delivery'):
            first=self.pending_index(phase,0)
            if first>=len(route['mission_ids']):
                if phase=='pickup':self.phase='pickup';self.after_pickup(now)
                else:self.advance(now)
            else:self.enter_stage(phase,now,first)
        else:
            self.enter_stage('travel',now)  # hunt or trip: go (back) to the hunting map; already there = hunt
        self.reason='Retomando: '+self.reason

    def resume_after_move(self,map_name,now):
        """Paused for lack of a recorded way: once the character is somewhere else, carry on."""
        if not self.resume or self.phase!='paused' or PortalGuard.key(map_name)==self.resume['map']:return False
        resume=self.resume;self.resume=None;self.voltar_fallback=None
        self.enter_stage(resume['phase'],now,resume['mission_index'])
        print('[ROTA] Personagem em '+map_name+': continuando '+self.reason);return True

    def finish_learning(self,now):
        captured=(self.learning or {}).get('captured')
        if not captured or now-captured['at']<3:return
        index=captured['index'];item=self.body.gear.get(index)
        ack=next((a for a in self.body.acks if a[0]>=captured['at']-1 and a[1]==index and a[4]),None)
        self.learning=None
        if not item or not ack or not ack[3]:
            self.reason='O servidor nao confirmou a montaria (fora de combate?); aprenda de novo';return
        displaced=[dict(item_id=self.body.gear.get(i,{}).get('item_id',0),position=p)
                   for t,i,p in self.body.unequipped if t>=captured['at']-1 and i!=index]
        self.learned_extras=dict(mount=dict(item_id=item['item_id'],location=captured['location'],
                                            displaced=[d for d in displaced if d['item_id']]))
        self.reason='Montaria aprendida: item '+str(item['item_id'])+'; tira '+str(len(displaced))+' equipamento(s)'

    def observe(self,events,own,map_name,now):
        from .network_targets import is_player_id
        if self.body.map is None and map_name:self.body.map=map_name  # the map before any change seen here
        self.body.observe(events,own,now)
        if self.learning:self.finish_learning(now)
        current=self.map or map_name
        for e in events:
            kind=e['kind'];identity=e.get('entity_id')
            if kind in ('map_change','map_transfer') and e.get('map'):
                source=PortalGuard.key(current)
                destination=PortalGuard.key(e['map'])
                if self.phase=='return' and self.return_sent:self.return_seen=dict(map=e['map'],at=now)
                expected_npc=self.recording.get('return_npc') if self.recording else None
                recorded_return=bool(expected_npc and self.recording.get('scope')=='return' and any(s['kind']=='npc' and chebyshev(s['position'],expected_npc['position'])<=2 and PortalGuard.key(s['map'])==PortalGuard.key(expected_npc['map']) for s in self.recording['steps']))
                if self.recording and current and (PortalGuard.key(current)!=destination or recorded_return):
                    cache=self.recording.setdefault('npc_cache',{})
                    for key,actor in self.actors.items():cache[key]=dict(map=current,actor=dict(actor))
                    if len(cache)>1000:self.recording['npc_cache']=dict(list(cache.items())[-1000:])
                    steps=self.recording['steps']
                    if self.recording.get('npc_id'):self.recording['last_warp_npc']=dict(id=self.recording['npc_id'],map=current)
                    if steps and steps[-1]['kind']=='walk':
                        steps[-1]['kind']='portal'
                        warps=[a['position'] for a in self.actors.values() if a.get('species_id') in (45,139)]
                        if warps:
                            closest=min(warps,key=lambda p:chebyshev(p,steps[-1]['position']))
                            if chebyshev(closest,steps[-1]['position'])<=12:steps[-1]['position']=list(closest)
                    self.append(dict(kind='wait_map',map=e['map']))
                    if recorded_return and not self.recording.get('finished_at_transition'):
                        self.recording['finished_at_transition']=True
                        self.recording['arrival']=dict(map=e['map'],position=e.get('position'))
                        self.reason='Retorno confirmado; gravacao pronta para salvar mesmo fora do mapa do NPC'
                current=e['map'];self.actors.clear();self.dialog=None;self.npc=None
                self.pending=None
                if self.phase in STAGES and self.steps and self.step<len(self.steps) and source!=destination:
                    remaining=self.steps[self.step:]
                    expected=next((i for i,s in enumerate(remaining) if s['kind']=='wait_map'),None)
                    if expected is not None and PortalGuard.key(remaining[expected]['map'])==destination:
                        self.step+=expected+1;self.progress_at=now;self.last_position=None
                self.hit.clear();self.killed.clear()
            elif kind=='appearance':
                self.actors[identity]=dict(e);self.killed.discard(identity)
                if self.recording and not self.recording.get('finished_at_transition'):
                    cache=self.recording.setdefault('npc_cache',{});cache[identity]=dict(map=current,actor=dict(e))
                    if len(cache)>1000:self.recording['npc_cache']=dict(list(cache.items())[-1000:])
            elif kind=='name' and identity in self.actors:
                self.actors[identity]['name']=e.get('name','')
                if self.recording and identity in self.recording.get('npc_cache',{}):self.recording['npc_cache'][identity]['actor']['name']=e.get('name','')
            elif kind=='remove':
                if (self.phase=='hunt' and e.get('reason')==1 and identity in self.hit
                    and now-self.hit[identity]<30 and identity not in self.killed):
                    self.killed.add(identity);self.hit.pop(identity,None)
                    actor=self.actors.get(identity,{});species=actor.get('species_id')
                    if self.counts_for_quest(species,actor.get('name')):
                        self.kills+=1
                        if species:self.kill_counts[species]=self.kill_counts.get(species,0)+1
                self.actors.pop(identity,None)
            elif kind in ('normal_attack','skill_damage') and self.phase=='hunt' and e.get('damage_raw',0)>0:
                target=e.get('target_id');actor=self.actors.get(target,{})
                if e.get('source_id')!=own:self.hit.pop(target,None)
                elif self.route and actor.get('species_id') in self.route['species']:
                    self.hit[target]=now
            elif kind=='npc_dialog':
                self.dialog=dict(e)
                if self.recording and self.recording.get('npc_id')==e.get('entity_id') and e.get('options'):
                    menus=self.recording.setdefault('observed_menus',[])
                    if e['options'] not in menus and len(menus)<100:menus.append(list(e['options']))
                if e.get('text'):
                    self.last_npc_text=e['text']
                    if self.phase in STAGES:
                        self.npc_texts=(self.npc_texts+[clean(e['text'])])[-60:]
                        print('[ROTA] NPC diz: '+clean(e['text']))
                    if self.recording and self.recording.get('npc_id')==e.get('entity_id'):
                        self.recording['last_npc_text']=e['text']
                        messages=self.recording.setdefault('observed_texts',[])
                        messages.append(e['text'][:4096]);del messages[:-64]
                        option=self.recording.get('selected_mission_option')
                        if option:
                            details=self.recording.setdefault('option_details',{})
                            lines=details.setdefault(option,[])
                            if e['text'] not in lines and len(lines)<30:lines.append(e['text'][:4096])
                    if (self.phase in ('pickup','delivery') and self.npc==e.get('entity_id')
                        and self.confirmation() and text(self.confirmation()) in text(e['text'])):
                        self.stage_confirmed=True
                        if self.phase=='delivery':self.delivery_ack=True
            elif (kind=='player_move' or kind=='move' and identity==own) and self.recording and current:
                self.append(dict(kind='walk',map=current,position=list(e['destination'])))
        self.map=current or map_name
        for e in events:
            if e['kind'] in ('combat_notice','server_notice') and e['text']!=self.printed_notice:
                self.printed_notice=e['text'];print('[ROTA] Jogo: '+e['text'])
            elif (e['kind'] in ('normal_attack','skill_damage') and self.phase=='hunt' and e.get('target_id')==own
                  and not is_player_id(e.get('source_id') or 0) and self.actors.get(e.get('source_id'),{}).get('species_id')):
                # A monster that attacks during the quest hunt is fought too, quest target or not.
                self.aggressors.add(self.actors[e['source_id']]['species_id'])

    def itinerary(self,map_name):
        """Reuse directed, recorded connections; never invent a return portal."""
        from collections import deque
        key=PortalGuard.key;origin=key(map_name)
        if self.phase=='return':
            from .quest_library import return_steps
            return return_steps(self.library,self.return_board)
        if self.phase in ('pickup','delivery'):
            if self.current_mission:
                from .quest_slots import effective_steps
                original=effective_steps(self.library,self.current_mission,self.phase)
                self.dynamic_pickup=any(s['kind']=='select_free_slot' for s in original)
                self.dynamic_delivery=any(s['kind']=='select_mission_slot' for s in original)
            else:original=self.route[STAGE_FIELDS[self.phase]]
            if origin==key(original[0]['map']):return copy.deepcopy(original)
            if self.current_mission:
                choices=[]
                for path in self.library['access_paths']:
                    if path['board_id']!=self.current_mission['board_id']:continue
                    source=key(path['steps'][0]['map'])
                    if source==key(original[0]['map']):continue
                    try:prefix=self.connection(origin,source)
                    except ValueError:continue
                    choices.append(prefix+copy.deepcopy(path['steps']))
                if not choices:raise ValueError('Grave um percurso de acesso ao quadro a partir deste mapa, ou uma ligacao ate a origem de um acesso salvo.')
                return min(choices,key=len)+copy.deepcopy(original)
            return self.connection(origin,key(original[0]['map']))+copy.deepcopy(original)
        target=key(self.route['target_map'])
        if origin==target:return []
        original=self.route['steps']
        starts=[i for i,s in enumerate(original) if s['kind']!='wait_map' and key(s['map'])==origin]
        if starts:return copy.deepcopy(original[starts[0]:])
        return self.connection(origin,target)

    def connection(self,origin,target):
        from collections import deque
        key=PortalGuard.key
        if origin==target:return []
        edges={}
        for route in self.known_routes:
            if route['needs_recording']:continue
            leg=[]
            for step in route['steps']:
                if step['kind']=='wait_map':
                    if leg:
                        edges.setdefault(key(leg[0]['map']),[]).append((key(step['map']),copy.deepcopy(leg+[step])))
                    leg=[]
                else:leg.append(step)
        if self.library:
            from .quest_library import board
            for path in self.library['access_paths']:
                steps=path['steps'];b=board(self.library,path['board_id'])
                edges.setdefault(key(steps[0]['map']),[]).append((key(b['map']),copy.deepcopy(steps)))
                # Intermediate transport connections are reusable too.
                leg=[]
                for step in steps:
                    if step['kind']=='wait_map':
                        if leg:edges.setdefault(key(leg[0]['map']),[]).append((key(step['map']),copy.deepcopy(leg+[step])))
                        leg=[]
                    else:leg.append(step)
        for entry in self.map_routes:
            steps=entry['steps']
            edges.setdefault(key(steps[0]['map']),[]).append((key(entry['target_map']),copy.deepcopy(steps)))
            leg=[]
            for step in steps:
                if step['kind']=='wait_map':
                    if leg:edges.setdefault(key(leg[0]['map']),[]).append((key(step['map']),copy.deepcopy(leg+[step])))
                    leg=[]
                else:leg.append(step)
        queue=deque([(origin,[])]);seen={origin}
        while queue:
            node,path=queue.popleft()
            for destination,leg in edges.get(node,[]):
                if destination==target:return path+leg
                if destination not in seen:seen.add(destination);queue.append((destination,path+leg))
        raise ValueError('Sem conexao gravada de '+origin+' para '+target+'. Grave o trecho de ida/retorno.')

    def plan(self,map_name,position,collision,portals,now):
        if self.phase not in STAGES: return None
        if self.pending:
            if position and (chebyshev(position,self.pending['position'])==0 or now-self.sent_at>4):
                self.pending=None
            else:return None
        if not position or not map_name: return None
        self.map=map_name
        if self.steps is None:
            try:self.steps=self.itinerary(map_name)
            except ValueError as exc:
                # No recorded way from here (e.g. still on the hunting map): @voltar, then try again.
                if (self.extras or {}).get('voltar_frame') and self.voltar_fallback!=PortalGuard.key(map_name) and not self.validation:
                    self.voltar_fallback=PortalGuard.key(map_name);self.queue('voltar',now,force=True)
                    print('[ROTA] Sem caminho gravado a partir de '+map_name+': usando @voltar');return None
                self.resume=dict(phase=self.phase,mission_index=self.mission_index,map=PortalGuard.key(map_name))
                self.stop(str(exc)+' (use @voltar ou leve o personagem ate um mapa com caminho gravado: a fila continua sozinha)')
                return None
        if self.last_position!=list(position): self.last_position=list(position);self.progress_at=now
        if self.step>=len(self.steps):
            if self.phase=='return':
                if not self.return_seen:
                    if now-self.progress_at>20:self.stop('Retorno nao confirmou teletransporte')
                    return None
                if self.return_context.get('validation'):self.complete_validation()
                else:self.after_board(self.return_context['phase'],self.return_context['next_index'],now)
                return None
            if self.phase in ('pickup','delivery'):
                if not self.stage_confirmed:
                    if now-self.progress_at>20:self.stop('NPC nao confirmou '+STAGES[self.phase]+'. Confira a mensagem de sucesso.')
                    return None
                if self.validation and not self.validation.get('all_missions'):
                    if self.current_mission and not self.skip_current:
                        self.learn_targets();self.completed_missions[self.phase].append(self.current_mission['id'])
                    if self.current_mission and self.library.get('return_enabled',True):
                        self.start_return(self.current_mission['board_id'],now,dict(validation=True));return None
                    self.complete_validation();return None
                if self.current_mission:
                    self.board_done(now);return None
                if self.phase=='pickup':self.enter_stage('travel',now)
                else:self.advance(now)
                return None
            if PortalGuard.key(map_name)!=PortalGuard.key(self.route['target_map']):
                self.stop('Destino nao confirmado: '+self.route['target_map']);return None
            if self.validation:
                target=self.validation.get('target_position')
                if target and chebyshev(position,target)>3:self.stop('Personagem nao chegou ao NPC esperado');return None
                self.complete_validation();return None
            self.phase='hunt';self.last_stage=('hunt',0);self.reason='Cacando: '+self.route['name'];self.queue('gear',now);return None
        if (self.phase=='travel' and not (self.validation or {}).get('target_position')
            and PortalGuard.key(map_name)==PortalGuard.key(self.route['target_map'])
            and all(s['kind']=='walk' for s in self.steps[self.step:])):
            # On the hunting map: the hunt finds the monsters, no need to walk the recorded tail.
            self.step=len(self.steps);return self.plan(map_name,position,collision,portals,now)
        step=self.steps[self.step];kind=step['kind']
        if step.get('verify_start') and self.phase in ('pickup','delivery') and self.slot_number is not None and self.next_on_same_board():
            # Reopening the board only to look at the slots: the next mission opens the same menu.
            check_kind='verify_slot' if self.phase=='pickup' else 'verify_slot_absent'
            wanted=next((s['option'] for s in self.steps[self.step:] if s['kind']==check_kind),None)
            self.deferred_check=dict(option=wanted,slot=self.slot_number,name=self.current_mission['name'],said=self.npc_said(),
                                     done=self.already_done(),id=self.current_mission['id'],phase=self.phase,
                                     board_id=self.current_mission['board_id'],label=self.current_mission.get('rank') or self.current_mission['name'])
            self.stage_confirmed=True;self.step=len(self.steps);self.progress_at=now;return None
        if kind=='wait_transfer':
            if self.return_seen:self.step+=1;self.progress_at=now;return None
            dialog=self.dialog
            if dialog and dialog.get('action') in ('next','close') and self.extra_pages<10:
                # Retorno talking first ("Ola, Guerreiro"): pages and closing carry no choice.
                return dict(kind=dialog['action'],entity_id=dialog['entity_id'],extra=True)
            if dialog and dialog.get('action')=='menu' and self.extra_pages<10:
                # "Quer retornar para sua vila?" Sim/Nao: answering yes is what Retorno is used for.
                from .npc_labels import plain
                yes=[i+1 for i,o in enumerate(dialog.get('options',[])) if plain(o)=='sim']
                if len(yes)==1:return dict(kind='select',entity_id=dialog['entity_id'],choice=yes[0],extra=True)
            if dialog and dialog.get('action')=='menu':
                options=' / '.join(clean(o) for o in dialog.get('options',[]) if clean(o))
                self.stop('NPC Retorno pediu uma escolha ('+options+'): use Gravar retorno do quadro uma vez');return None
            if now-self.progress_at>20:self.stop('Aguardando teletransporte do NPC Retorno; grave suas opcoes se necessario')
            return None
        if kind=='walk' and collision is not None and PortalGuard.key(step['map'])==PortalGuard.key(map_name):
            jump=self.shortcut(map_name,position,collision,portals)
            if jump is not None:self.step=jump;step=self.steps[jump];kind=step['kind']
        if kind=='walk':
            portal_index=self.step
            while portal_index<len(self.steps) and self.steps[portal_index]['kind']=='walk':portal_index+=1
            if portal_index<len(self.steps) and self.steps[portal_index]['kind']=='portal':
                portal=self.steps[portal_index]
                if PortalGuard.key(portal['map'])==PortalGuard.key(map_name):
                    zones=[(p,m) for p,m in portals.portals(map_name) if chebyshev(p,portal['position'])<=m]
                    if any(chebyshev(step['position'],p)<=m for p,m in zones):
                        self.step=portal_index;step=portal;kind='portal'
        if PortalGuard.key(map_name)!=PortalGuard.key(step['map']):
            if now-self.progress_at>30:self.stop('Mapa diferente do esperado: '+step['map'])
            return None
        if kind=='wait_map': self.step+=1;self.progress_at=now;return None
        if kind in ('walk','portal','npc'):
            goal=step['position'];distance=chebyshev(position,goal)
            if distance<=(2 if kind=='npc' else 0):
                if kind!='npc': self.step+=1;self.progress_at=now;return None
                from .npc_labels import npc_name
                from .network_targets import is_player_id
                matches=[(i,a) for i,a in self.actors.items() if not is_player_id(i) and a.get('position')==goal
                         and (not step.get('name') or npc_name(a.get('name',''))==npc_name(step['name'])
                              or not a.get('name') and 46<=a.get('species_id',0)<1000)]
                if not matches and step.get('name'):
                    # Coordinates typed or recorded one cell off: the same name right next to them.
                    matches=[(i,a) for i,a in self.actors.items() if not is_player_id(i) and a.get('position')
                             and chebyshev(a['position'],goal)<=2 and npc_name(a.get('name',''))==npc_name(step['name'])]
                if len(matches)!=1:
                    if now-self.progress_at>15:self.stop('NPC ausente ou ambiguo; confira nome e coordenadas')
                    return None
                return dict(kind='npc',entity_id=matches[0][0])
            if collision is None:self.stop('Mapa sem colisao valida; rota nao executada');return None
            if kind=='portal' and sum(chebyshev(p,goal)<=m for p,m in portals.portals(map_name))>1:
                self.stop('Portal ambiguo; grave a celula central do portal');return None
            c=self.navigation(map_name,collision,portals,step)
            path=self.path_to(c,position,goal,kind!='npc',portals.links(map_name))
            if not path or len(path)<2:self.stop('Caminho bloqueado na etapa '+str(self.step+1));return None
            if now-self.progress_at>15:self.stop('Movimento sem progresso; revise a etapa');return None
            end=path[1]
            for p in path[2:9]:
                if not c.segment(position,p,max_steps=8):break
                end=p
            return dict(kind='move',position=list(end))
        dialog=self.dialog
        expected=DIALOG[kind]
        if dialog and dialog['action']=='next' and expected!='next' and self.extra_pages<10:
            # One more "Proximo" page than recorded (texts can change): no choice involved, go on.
            return dict(kind='next',entity_id=dialog['entity_id'],extra=True)
        if kind=='close' and self.extra_pages<10:
            if dialog and dialog['action']=='menu':
                from .npc_labels import plain
                yes=[i+1 for i,o in enumerate(dialog.get('options',[])) if plain(o)=='sim']
                accepted=self.step>0 and plain(self.steps[self.step-1].get('option',''))=='aceitar missao'
                if self.phase=='pickup' and accepted and len(yes)==1:
                    # "Aceitar missao" asked for a confirmation: yes is what was chosen.
                    return dict(kind='select',entity_id=dialog['entity_id'],choice=yes[0],extra=True)
                return dict(kind='cancel',entity_id=dialog['entity_id'],choice=255,extra=True)  # ends it, picks nothing
            if not dialog and self.extra_pages and now-self.sent_at>3:
                # The script ended after its last page without a close button: the conversation is over.
                self.step+=1;self.progress_at=now;return None
        # One conversation per character: after our click every dialog belongs to it, even when the
        # server answers from another id (duplicated NPCs such as "Sala Vip#2"). Replies go to that id;
        # success messages still have to come from the clicked NPC (observe).
        if dialog and dialog['action']!=expected and kind=='next':
            # "Proximo" already pressed (by hand, or one page less this time): follow the conversation.
            later=next((i for i in range(self.step,len(self.steps)) if self.steps[i]['kind']!='next'),None)
            if later is not None and DIALOG.get(self.steps[later]['kind'])==dialog['action']:
                self.step=later;self.progress_at=now;return None
        if not dialog or dialog['action']!=expected:
            if now-self.progress_at>15:
                received=f" (recebido: {dialog['action']} do NPC {dialog['entity_id']})" if dialog else ' (nenhum dialogo recebido)'
                self.stop('Aguardando dialogo esperado: '+kind+received)
            return None
        if kind in ('select_free_slot','select_mission_slot','verify_slot','verify_slot_absent'):
            from .quest_slots import slot,same_mission
            slots=[(i+1,slot(value)) for i,value in enumerate(dialog.get('options',[])) if slot(value)]
            if not slots:self.stop('O quadro nao enviou o menu de slots esperado para '+step['option']);return None
            for _,s in slots:
                if s['empty'] and self.slot_owner.pop(s['number'],None) is not None:self.slots_dirty=True
            mine=self.current_mission['id'] if self.current_mission else None
            same=[(i,s) for i,s in slots if not s['empty'] and same_mission(s['mission'],step['option'])]
            # "Rank A-1" from Kakashi and from the Sala Vip look the same in a slot: one known to hold
            # the other board's mission is not this one.
            wanted=[(i,s) for i,s in same if self.slot_owner.get(s['number']) in (None,mine)]
            own=[(i,s) for i,s in wanted if self.slot_owner.get(s['number'])==mine]
            if own:wanted=own
            if kind=='select_mission_slot' and self.deferred_check:
                check=self.deferred_check;self.deferred_check=None
                if any(not s['empty'] and s['number']==check['slot'] and same_mission(s['mission'],check['option']) for _,s in slots):
                    self.stop(f"Entrega nao confirmada: {check['name']} continua no slot {check['slot']}"+check['said']);return None
                self.daily_marks.append((check['board_id'],check['label']));self.release_slot(check['slot'])
            if kind=='select_free_slot' and self.deferred_check:
                check=self.deferred_check;self.deferred_check=None
                accepted=any(not s['empty'] and s['number']==check['slot'] and same_mission(s['mission'],check['option']) for _,s in slots)
                if not accepted and check.get('done'):
                    for done in [self.completed_missions['pickup']]+[p['picked'] for p in self.prefetched.values()]:
                        if check.get('id') in done:done.remove(check['id'])
                    self.skipped_ids.add(check.get('id'))
                    self.skipped.append(check['name']+': o quadro respondeu que ja foi completada')
                    print('[ROTA] Pulada: '+self.skipped[-1])
                elif not accepted:
                    self.stop(f"O quadro nao aceitou {check['name']} (slot {check['slot']} continua vazio)"+check['said']);return None
                else:self.own_slot(check['slot'],check['id'])
            if kind=='select_free_slot':
                if wanted:
                    self.own_slot(wanted[0][1]['number'],mine)
                    self.stage_confirmed=True;self.reason=step['option']+' ja esta ativa no slot '+str(wanted[0][1]['number'])
                    self.steps=self.steps[:self.step]+[dict(kind='cancel',map=step['map'])];self.progress_at=now;return None
                free=sorted(((i,s) for i,s in slots if s['empty']),key=lambda pair:pair[1]['number'])
                if not free:self.stop('Sem slots livres para '+step['option']+'; nenhuma missao foi abandonada');return None
                choice,chosen=free[0];self.slot_number=chosen['number']
                return dict(kind='select',entity_id=dialog['entity_id'],choice=choice)
            if kind=='select_mission_slot':
                if len(wanted)!=1:self.stop('Missao nao localizada de forma unica nos slots para entregar: '+step['option']);return None
                self.slot_number=wanted[0][1]['number']
                return dict(kind='select',entity_id=dialog['entity_id'],choice=wanted[0][0])
            if kind=='verify_slot':
                if (not wanted or not any(s['number']==self.slot_number for _,s in wanted)) and self.already_done():
                    self.skip('o quadro respondeu que ja foi completada');self.steps=self.steps[:self.step]+[dict(kind='cancel',map=step['map'])]
                    self.progress_at=now;return None
                if not any(s['number']==self.slot_number for _,s in same):
                    self.stop('O quadro nao aceitou '+step['option']+' (slot escolhido continua vazio)'+self.npc_said());return None
                self.own_slot(self.slot_number,mine)
            elif any(s['number']==self.slot_number for _,s in same):
                # Delivered = gone from its slot; no success message is needed (nor trusted).
                from .npc_labels import plain
                missing=any('precisa matar' in plain(t) for t in self.npc_texts)
                self.stop(('Missao '+step['option']+' ainda nao concluida (faltam monstros)' if missing else
                           'Entrega nao confirmada: '+step['option']+' continua no slot')+self.npc_said());return None
            else:
                self.daily_marks.append((self.current_mission['board_id'],self.current_mission.get('rank') or self.current_mission['name']))
                self.release_slot(self.slot_number)
            self.stage_confirmed=True;self.step+=1;self.progress_at=now;return None
        if kind=='select' and self.phase=='pickup' and text(step['option'])==text('Aceitar missão') and self.already_done():
            # "Status : Completa": the board would answer "Voce ja completou esta missao". Leave without accepting.
            self.skip('ja completada (o quadro mostra Status: Completa)')
            return dict(kind='cancel',entity_id=dialog['entity_id'],choice=255,extra=True)
        action=dict(kind=kind,entity_id=dialog['entity_id'])
        if kind=='cancel':action['choice']=255
        if kind=='select':
            choices=[i+1 for i,v in enumerate(dialog.get('options',[])) if text(v)==text(step['option'])]
            if len(choices)!=1:self.stop('Opcao do NPC ausente ou duplicada: '+step['option']);return None
            action['choice']=choices[0]
        return action

    def learn_targets(self):
        """The description shown while taking the mission says what to kill: keep it."""
        if self.phase!='pickup' or not self.current_mission:return
        from .quest_targets import targets
        found=targets(self.npc_texts)
        m=self.current_mission
        if not found or m.get('monster_targets')==found:return
        from .quest_library import enrich_mission
        enrich_mission(m,list(self.npc_texts))
        self.learned.append(m['id'])
        print('[ROTA] Monstros de '+m['name']+': '+', '.join(f"{t['count']} {t['name']}" for t in found))

    def shortcut(self,map_name,position,collision,portals):
        """Index to walk to instead of the current recorded point, or None.

        The recorded clicks are only a way through: when the end of this map's leg (its portal,
        NPC or last point) can be reached, go straight there. If not (map not fully known),
        resume from the recorded point closest to where the character is, which also covers a
        random teleport inside the map."""
        key=PortalGuard.key;here=key(map_name);end=self.step
        while end+1<len(self.steps) and self.steps[end]['kind']=='walk' and key(self.steps[end+1]['map'])==here and self.steps[end+1]['kind'] in ('walk','portal','npc'):
            end+=1
        if end==self.step:return None
        marker=(here,id(self.steps),end)
        if marker not in self.direct_failed:
            target=self.steps[end]
            if self.path_to(self.navigation(map_name,collision,portals,target),position,target['position'],target['kind']!='npc',
                            portals.links(map_name)):return end
            self.direct_failed.add(marker)
        points=[i for i in range(self.step,end+1) if self.steps[i].get('position')]
        nearest=min(points,key=lambda i:(chebyshev(position,self.steps[i]['position']),-i))
        return nearest if nearest>self.step else None

    def navigation(self,map_name,collision,portals,step):
        """Collision map with the portals forbidden (but the one this step enters), kept between ticks.

        Rebuilding it on every tick threw away its caches and made each path search start cold."""
        from .map_navigation import CollisionMap
        allowed=frozenset()
        if step['kind']=='portal':
            allowed=frozenset((p[0]+x,p[1]+y) for p,m in portals.portals(map_name) if chebyshev(p,step['position'])<=m
                              for x in range(-m,m+1) for y in range(-m,m+1))
        forbidden=frozenset(portals.cells(map_name))-allowed
        key=(PortalGuard.key(map_name),id(collision),forbidden)
        c=self.nav_cache.get(key)
        if c is None:
            if len(self.nav_cache)>=4:self.nav_cache.clear()
            c=CollisionMap(collision.width,collision.height,collision.cells);c.set_forbidden(forbidden);self.nav_cache[key]=c
        return c

    def path_to(self,c,position,goal,exact,links=()):
        """Path to goal, searched once and followed while the character stays on it.

        After a teleport far away the search runs once (unreachable goals are refused at once
        through the connected area), instead of on every tick, which froze the relay and the game."""
        here=tuple(position);key=(id(c),tuple(goal),exact)
        if self.path_cache and self.path_cache[0]==key:
            path=self.path_cache[1]
            if path is None and self.path_cache[2]==here:return None
            if path:
                index=min(range(len(path)),key=lambda i:chebyshev(path[i],here))
                if chebyshev(path[index],here)<=1:
                    rest=path[index:] if path[index]==here else [here]+path[index:]
                    return rest if len(rest)>1 or tuple(goal)==here else None
        area=c.reachable(here);goal=tuple(goal)
        near=[goal] if exact else [goal]+[(goal[0]+dx,goal[1]+dy) for dx in (-1,0,1) for dy in (-1,0,1)]
        if any(p in area for p in near):
            path=c.route(here,goal,exact=exact,max_nodes=300000,greed=1.2)
        else:
            # Walled off on this map (sewers): the goal lies past inner portals. Walk onto the first
            # portal of the shortest chain; after the warp the search runs again from the arrival.
            portal=self.inner_portal_towards(c,area,near,links)
            path=c.route(here,portal,exact=True,max_nodes=300000,greed=1.2) if portal else None
        self.path_cache=(key,path,here)
        return path

    @staticmethod
    def inner_portal_towards(c,area,near,links):
        """First inner portal (same-map warp) of the shortest chain from area to one of the near cells."""
        from collections import deque
        links=[(tuple(source),tuple(arrival)) for source,arrival in links]
        queue=deque([(frozenset(area),None)]);seen=[frozenset(area)]
        while queue:
            here,first=queue.popleft()
            for source,arrival in links:
                if source not in here or arrival in here:continue
                there=frozenset(c.reachable(arrival))
                if any(there==s for s in seen):continue
                if any(p in there for p in near):return first or source
                seen.append(there);queue.append((there,first or source))
        return None

    def own_slot(self,number,identity):
        if number is not None and identity and self.slot_owner.get(number)!=identity:
            self.slot_owner[number]=identity;self.slots_dirty=True

    def release_slot(self,number):
        if self.slot_owner.pop(number,None) is not None:self.slots_dirty=True

    def trip_passes(self,board_id,route=None):
        """The recorded trip to the hunting map goes through this board's map."""
        from .quest_library import board
        here=PortalGuard.key(board(self.library,board_id)['map'])
        return any(s['kind']!='wait_map' and PortalGuard.key(s['map'])==here for s in (route or self.route)['steps'])

    def pending_index(self,phase,index):
        """Next mission of this stage still to do (taken early or skipped ones are passed over)."""
        ids=self.route['mission_ids']
        while index<len(ids) and (ids[index] in self.completed_missions[phase] or ids[index] in self.skipped_ids):index+=1
        return index

    def next_route_missions(self,board_id):
        """Missions of the next route on this board, not yet taken: taken now, on the same visit."""
        following=self.index+1
        if following>=len(self.routes) or not self.library:return []
        route=self.routes[following]
        if not route['lifecycle_enabled'] or not route['mission_ids']:return []
        from .quest_library import mission
        done=self.prefetched.get(following,{})
        return [i for i in self.chain_missions(following) if mission(self.library,i)['board_id']==board_id
                and i not in done.get('picked',[]) and i not in done.get('skipped',[])]

    def next_route_ready(self):
        """Every mission of the next route is already taken: it goes straight to its trip."""
        following=self.index+1
        if following>=len(self.routes):return False
        route=self.routes[following]
        if not route['lifecycle_enabled'] or not route['mission_ids']:return True
        done=self.prefetched.get(following,{})
        return all(i in done.get('picked',[]) or i in done.get('skipped',[]) for i in self.chain_missions(following))

    def board_done(self,now):
        """A mission of this board is done: the next one here, then the next route's ones here, then leave."""
        from .quest_library import mission
        m=self.current_mission
        if self.borrow:
            b=self.borrow;store=self.prefetched.setdefault(b['route'],dict(picked=[],skipped=[],notes=[]))
            if self.skip_current:
                store['skipped'].append(m['id'])
                if self.skipped:store['notes'].append(self.skipped.pop())
            else:self.learn_targets();store['picked'].append(m['id'])
            b['pos']+=1
            if b['pos']<len(b['ids']):self.enter_stage('pickup',now);return
            phase,next_index=b['then'];self.borrow=None
            self.leave_board(phase,next_index,m['board_id'],now);return
        if not self.skip_current:self.learn_targets();self.completed_missions[self.phase].append(m['id'])
        else:self.skipped_ids.add(m['id'])
        next_index=self.pending_index(self.phase,self.mission_index+1)
        ids=self.route['mission_ids']
        if next_index<len(ids) and mission(self.library,ids[next_index])['board_id']==m['board_id']:
            self.after_board(self.phase,next_index,now);return
        if self.phase=='delivery' and not self.validation:
            early=self.next_route_missions(m['board_id'])
            if early:
                print('[ROTA] Ja pegando aqui as missoes da proxima rota: '+self.routes[self.index+1]['name'])
                self.borrow=dict(route=self.index+1,ids=early,pos=0,then=('delivery',next_index))
                self.enter_stage('pickup',now);return
        self.leave_board(self.phase,next_index,m['board_id'],now)

    def leave_board(self,phase,next_index,board_id,now):
        last=next_index>=len(self.route['mission_ids'])
        if last and not self.validation:
            # Sala Vip: its Viajante Ninja is on the way to the hunting map; Retorno would undo that.
            if phase=='pickup' and self.trip_passes(board_id):
                self.after_board(phase,next_index,now);return
            if (phase=='delivery' and self.next_route_ready()
                and self.trip_passes(board_id,self.routes[self.index+1])):
                print('[ROTA] Proxima rota segue daqui (sem Retorno): '+self.routes[self.index+1]['name'])
                self.after_board(phase,next_index,now);return
        if self.library.get('return_enabled',True):
            self.start_return(board_id,now,dict(phase=phase,next_index=next_index));return
        self.after_board(phase,next_index,now)

    def counts_for_quest(self,species,name):
        """A kill counts unless its name shows it is another monster with the same sprite."""
        from .npc_labels import plain
        targets=[t for t in (self.route or {}).get('kill_targets',[]) if species in t['species']]
        if not name or not targets:return True
        return any(plain(t['name'])==plain(name) for t in targets)

    def progress(self):
        """[{'name', 'count', 'done', 'complete'}] per counted monster (or one total line)."""
        route=self.route
        if not route:return []
        if not route['kill_targets']:
            return [dict(name='Total',count=route['kills'],done=self.kills,complete=self.kills>=route['kills'])]
        result=[]
        for t in route['kill_targets']:
            done=sum(self.kill_counts.get(s,0) for s in t['species'])
            result.append(dict(name=t['name'],count=t['count'],done=min(done,t['count']),complete=done>=t['count']))
        return result

    def hunt_complete(self):
        return all(p['complete'] for p in self.progress())

    def next_on_same_board(self):
        if not self.current_mission or self.validation and not self.validation.get('all_missions'):return False
        if self.borrow:return self.phase=='pickup' and self.borrow['pos']+1<len(self.borrow['ids'])
        from .quest_library import mission
        following=self.pending_index(self.phase,self.mission_index+1)
        return following<len(self.route['mission_ids']) and mission(self.library,self.route['mission_ids'][following])['board_id']==self.current_mission['board_id']

    def already_done(self):
        """The board said this daily mission was already done (description status or the refusal)."""
        from .npc_labels import plain
        return any(re.search(r'status\s*:\s*complet',plain(t)) or 'ja completou' in plain(t) for t in self.npc_texts)

    def skip(self,why):
        self.skipped.append(self.current_mission['name']+': '+why);self.skip_current=True
        self.daily_marks.append((self.current_mission['board_id'],self.current_mission.get('rank') or self.current_mission['name']))
        self.stage_confirmed=True;self.slot_number=None;self.steps=self.steps[:self.step]
        print('[ROTA] Pulada: '+self.skipped[-1])

    def skipped_note(self):
        return ('. Puladas: '+'; '.join(self.skipped)) if self.skipped else ''

    def npc_said(self):
        """What the NPC answered, without the "[Quadro de missoes]" speaker lines."""
        lines=[t for t in self.npc_texts if t and not (t.startswith('[') and t.endswith(']'))]
        return ('. NPC respondeu: '+' / '.join(lines[-3:])) if lines else ''

    def sent(self,action,now):
        self.sent_at=now
        if action.get('extra'):  # extra dialog page: the recorded step is still ahead
            self.extra_pages+=1;self.dialog=None;self.progress_at=now;return
        if action['kind']=='move': self.pending=dict(action);return
        if action['kind']=='npc':
            self.npc=action['entity_id']
            if self.phase=='return':self.return_sent=True
            if self.phase in ('pickup','delivery'):self.stage_confirmed=False
        self.dialog=None;self.step+=1;self.progress_at=now

    def snapshot(self):
        return dict(phase=self.phase,reason=self.reason,quest=self.route['name'] if self.route else None,
                    quest_id=self.route['id'] if self.route else None,step=self.step+1,kills=self.kills,
                    goal=self.route['kills'] if self.route else 0,recording=self.recording and self.recording['id'],
                    recording_stage=self.recording.get('stage','travel') if self.recording else None,
                    last_npc_text=self.recording.get('last_npc_text','') if self.recording else self.last_npc_text,
                    stage_confirmed=self.stage_confirmed,
                    mission=self.current_mission['name'] if self.current_mission else None,
                    mission_index=self.mission_index+1,completed_missions=copy.deepcopy(self.completed_missions),
                    skipped_missions=list(self.skipped),kill_progress=self.progress(),
                    errand=dict(kind=self.errands[0].kind,reason=self.errands[0].reason) if self.errands else None,
                    learning=self.learning['what'] if self.learning else None,
                    inventory=self.body.items(),
                    recording_scope=self.recording.get('scope','route') if self.recording else None,
                    recording_label=self.recording.get('label','') if self.recording else None,
                    recorded_menus=len(self.recording.get('observed_menus',[])) if self.recording else 0,
                    recorded_options=len({s for menu in self.recording.get('observed_menus',[]) for s in menu}) if self.recording else 0,
                    validation=copy.deepcopy(self.validation),
                    recorded_steps=len(self.recording['steps']) if self.recording else 0)
