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
        self.killed=set();self.hit={};self.kills=0;self.actors={};self.map=None;self.progress_at=0;self.last_position=None
        self.known_routes=[];self.steps=None
        self.stage_confirmed=False;self.last_npc_text=''
        self.library=None;self.mission_index=0;self.completed_missions={'pickup':[],'delivery':[]}
        self.validation=None
        self.return_context=None;self.return_board=None;self.return_seen=None;self.return_sent=False
        self.extra_pages=0;self.deferred_check=None;self.npc_texts=[];self.skipped=[];self.skip_current=False
        self.dynamic_pickup=False;self.dynamic_delivery=False;self.slot_number=None;self.delivery_ack=False

    @property
    def active(self): return self.phase in ('pickup','travel','hunt','delivery','return')
    @property
    def route(self): return self.routes[self.index] if self.index<len(self.routes) else None

    @property
    def current_mission(self):
        if not self.route or self.phase not in ('pickup','delivery') or not self.route['mission_ids']:return None
        from .quest_library import mission
        return mission(self.library,self.route['mission_ids'][self.mission_index])

    def confirmation(self):
        if self.current_mission:
            if self.dynamic_pickup:return ''
            from .quest_slots import confirmation
            return confirmation(self.library,self.current_mission,self.phase)
        return (self.current_mission or self.route)[self.phase+'_confirmation']

    def start(self,routes,now,library=None):
        self.validation=None
        self.known_routes=validate_routes(routes)
        self.routes=[copy.deepcopy(r) for r in self.known_routes if r['enabled']]
        if not self.routes: raise ValueError('Marque ao menos uma quest')
        self.library=None
        if any(r['mission_ids'] for r in self.routes):
            from .quest_library import load,validate,ready_mission
            self.library=validate(library) if library is not None else load()
            for r in self.routes:
                for identity in r['mission_ids']:ready_mission(self.library,identity)
        for r in self.routes:
            if r['needs_recording']:raise ValueError('Grave o percurso completo antes de executar: '+r['name'])
            if not r['steps'] or not r['target_map'] or not r['species']: raise ValueError('Complete rota, mapa e monstros da quest '+r['name'])
            if r['lifecycle_enabled'] and not r['mission_ids']:
                for phase in ('pickup','delivery'):
                    if (not r[STAGE_FIELDS[phase]] or not text(r[phase+'_confirmation'])
                        or not any(s['kind']=='npc' for s in r[STAGE_FIELDS[phase]])):
                        raise ValueError('Configure o trecho e a confirmacao de '+STAGES[phase]+': '+r['name'])
        self.index=0;self.recording=None;self.begin(now)

    def start_validation(self,steps,target_map,now,*,mode,label,library=None,mission_id=None,target_position=None,return_board=None,mission_ids=None):
        if self.active or self.recording:raise ValueError('Pause a fila e encerre a gravacao antes de testar')
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
        self.kills=0;self.killed.clear();self.hit.clear()
        self.completed_missions={'pickup':[],'delivery':[]};self.deferred_check=None;self.skipped=[]
        self.enter_stage('pickup' if self.route['lifecycle_enabled'] else 'travel',now)

    def enter_stage(self,phase,now,mission_index=0):
        self.step=0;self.phase=phase
        self.pending=None;self.dialog=None;self.npc=None;self.progress_at=now;self.last_position=None
        self.steps=None
        self.stage_confirmed=False;self.last_npc_text=''
        self.dynamic_pickup=False;self.dynamic_delivery=False;self.slot_number=None;self.delivery_ack=False
        self.return_seen=None;self.return_sent=False
        self.extra_pages=0;self.npc_texts=[];self.skip_current=False
        self.mission_index=mission_index
        self.reason=STAGES.get(phase,phase)+': '+self.route['name']
        if self.current_mission:self.reason+=' / '+self.current_mission['name']

    def start_return(self,board_id,now,context):
        self.return_context=context;self.return_board=board_id;self.enter_stage('return',now)

    def after_board(self,phase,next_index,now):
        if next_index<len(self.route['mission_ids']):self.enter_stage(phase,now,next_index)
        elif self.validation and self.validation.get('all_missions'):self.complete_validation()
        elif phase=='pickup':self.enter_stage('travel',now)
        else:self.advance(now)

    def finish_hunt(self,now):
        if self.route['lifecycle_enabled']:self.enter_stage('delivery',now)
        else:self.advance(now)

    def stop(self,reason='Fila pausada'):
        self.phase='paused';self.pending=None;self.reason=reason

    def advance(self,now):
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

    def observe(self,events,own,map_name,now):
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
                    self.killed.add(identity);self.kills+=1;self.hit.pop(identity,None)
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
                        self.npc_texts=(self.npc_texts+[clean(e['text'])])[-12:]
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
            except ValueError as exc:self.stop(str(exc));return None
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
                    if self.current_mission and not self.skip_current:self.completed_missions[self.phase].append(self.current_mission['id'])
                    if self.current_mission and self.library.get('return_enabled',True):
                        self.start_return(self.current_mission['board_id'],now,dict(validation=True));return None
                    self.complete_validation();return None
                if self.current_mission:
                    if not self.skip_current:self.completed_missions[self.phase].append(self.current_mission['id'])
                    from .quest_library import mission
                    next_index=self.mission_index+1
                    same_board=next_index<len(self.route['mission_ids']) and mission(self.library,self.route['mission_ids'][next_index])['board_id']==self.current_mission['board_id']
                    if self.library.get('return_enabled',True) and not same_board:
                        self.start_return(self.current_mission['board_id'],now,dict(phase=self.phase,next_index=next_index));return None
                    self.after_board(self.phase,next_index,now);return None
                if self.phase=='pickup':self.enter_stage('travel',now)
                else:self.advance(now)
                return None
            if PortalGuard.key(map_name)!=PortalGuard.key(self.route['target_map']):
                self.stop('Destino nao confirmado: '+self.route['target_map']);return None
            if self.validation:
                target=self.validation.get('target_position')
                if target and chebyshev(position,target)>3:self.stop('Personagem nao chegou ao NPC esperado');return None
                self.complete_validation();return None
            self.phase='hunt';self.reason='Cacando: '+self.route['name'];return None
        step=self.steps[self.step];kind=step['kind']
        if step.get('verify_start') and self.phase=='pickup' and self.slot_number is not None and self.next_on_same_board():
            # Reopening the board only to look at the slots: the next mission opens the same menu.
            wanted=next((s['option'] for s in self.steps[self.step:] if s['kind']=='verify_slot'),None)
            self.deferred_check=dict(option=wanted,slot=self.slot_number,name=self.current_mission['name'],said=self.npc_said(),
                                     done=self.already_done(),id=self.current_mission['id'])
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
            from .map_navigation import CollisionMap
            c=CollisionMap(collision.width,collision.height,collision.cells)
            allowed=set()
            if kind=='portal':
                matching=[(p,m) for p,m in portals.portals(map_name) if chebyshev(p,goal)<=m]
                if len(matching)>1:self.stop('Portal ambiguo; grave a celula central do portal');return None
                if matching:
                    p,m=matching[0];allowed={(p[0]+x,p[1]+y) for x in range(-m,m+1) for y in range(-m,m+1)}
            c.set_forbidden(portals.cells(map_name)-allowed)
            path=c.route(position,goal,exact=kind!='npc',max_nodes=50000)
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
            wanted=[(i,s) for i,s in slots if not s['empty'] and same_mission(s['mission'],step['option'])]
            if kind=='select_free_slot' and self.deferred_check:
                check=self.deferred_check;self.deferred_check=None
                accepted=any(not s['empty'] and s['number']==check['slot'] and same_mission(s['mission'],check['option']) for _,s in slots)
                if not accepted and check.get('done'):
                    done=self.completed_missions['pickup']
                    if check.get('id') in done:done.remove(check['id'])
                    self.skipped.append(check['name']+': o quadro respondeu que ja foi completada')
                    print('[ROTA] Pulada: '+self.skipped[-1])
                elif not accepted:
                    self.stop(f"O quadro nao aceitou {check['name']} (slot {check['slot']} continua vazio)"+check['said']);return None
            if kind=='select_free_slot':
                if wanted:
                    self.stage_confirmed=True;self.reason=step['option']+' ja esta ativa no slot '+str(wanted[0][1]['number'])
                    self.steps=self.steps[:self.step]+[dict(kind='cancel',map=step['map'])];self.progress_at=now;return None
                free=sorted(((i,s) for i,s in slots if s['empty']),key=lambda pair:pair[1]['number'])
                if not free:self.stop('Sem slots livres para '+step['option']+'; nenhuma missao foi abandonada');return None
                choice,chosen=free[0];self.slot_number=chosen['number']
                return dict(kind='select',entity_id=dialog['entity_id'],choice=choice)
            if kind=='select_mission_slot':
                if len(wanted)!=1:self.stop('Missao nao localizada de forma unica nos slots para entregar: '+step['option']);return None
                return dict(kind='select',entity_id=dialog['entity_id'],choice=wanted[0][0])
            if kind=='verify_slot':
                if (not wanted or not any(s['number']==self.slot_number for _,s in wanted)) and self.already_done():
                    self.skip('o quadro respondeu que ja foi completada');self.steps=self.steps[:self.step]+[dict(kind='cancel',map=step['map'])]
                    self.progress_at=now;return None
                if not wanted or not any(s['number']==self.slot_number for _,s in wanted):
                    self.stop('O quadro nao aceitou '+step['option']+' (slot escolhido continua vazio)'+self.npc_said());return None
            elif not self.delivery_ack or wanted:
                self.stop('Entrega nao confirmada no quadro para '+step['option']);return None
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

    def next_on_same_board(self):
        if not self.current_mission or self.validation and not self.validation.get('all_missions'):return False
        from .quest_library import mission
        following=self.mission_index+1
        return following<len(self.route['mission_ids']) and mission(self.library,self.route['mission_ids'][following])['board_id']==self.current_mission['board_id']

    def already_done(self):
        """The board said this daily mission was already done (description status or the refusal)."""
        from .npc_labels import plain
        return any(re.search(r'status\s*:\s*complet',plain(t)) or 'ja completou' in plain(t) for t in self.npc_texts)

    def skip(self,why):
        self.skipped.append(self.current_mission['name']+': '+why);self.skip_current=True
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
                    skipped_missions=list(self.skipped),
                    recording_scope=self.recording.get('scope','route') if self.recording else None,
                    recording_label=self.recording.get('label','') if self.recording else None,
                    recorded_menus=len(self.recording.get('observed_menus',[])) if self.recording else 0,
                    recorded_options=len({s for menu in self.recording.get('observed_menus',[]) for s in menu}) if self.recording else 0,
                    validation=copy.deepcopy(self.validation),
                    recorded_steps=len(self.recording['steps']) if self.recording else 0)
