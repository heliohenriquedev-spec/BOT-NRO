"""Record shared access paths and mission options without modifying quest routes."""
import uuid
import time
import copy
from . import quest_library as lib
from .quest_routes import text
from .portals import PortalGuard,chebyshev


class SharedQuestRelay:
    def library_control(self,command,request):
        q=self.quests;data=lib.load()
        if command=='quest_library_record':
            if self.upstream is None:raise ValueError('Entre no personagem antes de gravar')
            if not self.tracker.observer.player_position_valid(time.monotonic()) or not self.tracker.observer.map_name:
                raise ValueError('Aguarde o mapa e a posicao do personagem serem recebidos')
            if q.recording:raise ValueError('Salve ou descarte a gravacao anterior')
            scope=request.get('scope');stage=request.get('stage','travel')
            if scope in ('access','return'):
                b=lib.board(data,request['board_id']);identity=b['id'];stage='travel'
                if scope=='return' and PortalGuard.key(self.tracker.observer.map_name)!=b['map']:
                    raise ValueError('Comece o retorno dentro de '+b['map'])
            elif scope in ('mission','menus') and (scope=='menus' or stage in ('pickup','delivery')):
                if scope=='mission':
                    m=lib.mission(data,request['mission_id']);b=lib.board(data,m['board_id']);identity=m['id']
                else:
                    b=lib.board(data,request['board_id']);identity=b['id'];stage='travel'
                o=self.tracker.observer
                if PortalGuard.key(o.map_name)!=PortalGuard.key(b['map']) or not o.player or chebyshev(o.player,b['position'])>2:
                    raise ValueError('Para gravar opcoes, fique ao lado do '+b['name'])
                if self.walking_now():raise ValueError('Pare ao lado do quadro antes de gravar as opcoes')
            else:raise ValueError('Tipo de gravacao desconhecido')
            self.quest_stop('Gravando cadastro compartilhado');q.record(identity,stage)
            q.recording.update(scope=scope,board_id=b['id'],label=m['name'] if scope=='mission' else b['name'],
                               board_map=b['map'],board_position=b['position'])
            if scope=='return':
                q.recording['label']='Retorno: '+b['name'];q.recording['return_npc']=copy.deepcopy(b['return_npc'])
            q.map=self.tracker.observer.map_name
            for cached in q.recording.get('npc_cache',{}).values():
                if not cached['map']:cached['map']=q.map
            if scope in ('access','return'):
                q.append(dict(kind='walk',map=q.map,position=list(self.tracker.observer.player)))
        elif command=='quest_library_save':
            recording=q.recording
            if not recording or recording.get('scope') not in ('access','return','mission','menus'):raise ValueError('Nenhum cadastro sendo gravado')
            if recording.get('error') or self.native_frames.error:raise ValueError(recording.get('error') or self.native_frames.error)
            if self.walking_now() and not recording.get('arrival'):raise ValueError('Aguarde o personagem terminar de caminhar antes de salvar')
            b=lib.board(data,recording['board_id']);o=self.tracker.observer
            if recording['scope']=='return':
                steps=copy.deepcopy(recording['steps'])
                if not steps or not any(s['kind']=='wait_map' for s in steps):raise ValueError('Use Retorno e aguarde chegar ao destino antes de salvar')
                arrival=recording.get('arrival') or dict(map=o.map_name,position=o.player)
                if not arrival.get('position'):raise ValueError('Aguarde a posicao de chegada do retorno')
                if steps[-1].get('position')!=list(arrival['position']):steps.append(dict(kind='walk',map=arrival['map'],position=list(arrival['position'])))
                data['return_paths'][b['id']]=dict(steps=steps)
            elif recording['scope']=='menus':
                if not recording.get('observed_menus'):raise ValueError('Abra o quadro e seus menus para receber as opcoes antes de salvar')
                lib.validate_conversation(recording['steps'],b)
            elif recording['scope']=='access':
                steps=lib.validate_access(recording['steps'],b,o.map_name,o.player)
                if steps[-1].get('position')!=list(o.player):steps.append(dict(kind='walk',map=o.map_name,position=list(o.player)))
                from .map_routes import compact
                steps=compact(steps)  # the walk to each NPC/portal is computed, not replayed
                data['access_paths'].append(dict(id=uuid.uuid4().hex,board_id=b['id'],
                    name=steps[0]['map']+' → '+b['name'],steps=steps))
            else:
                m=lib.mission(data,recording['id']);stage=recording['stage']
                steps=lib.validate_conversation(recording['steps'],b)
                confirmation=request.get('confirmation','').strip()
                if not text(confirmation) or not any(text(confirmation) in text(s) for s in recording.get('observed_texts',[])):
                    raise ValueError('Informe um trecho de sucesso realmente recebido deste quadro na gravacao')
                m[stage+'_steps']=steps;m[stage+'_confirmation']=confirmation
                from .npc_labels import rank
                selected={rank(s.get('option','')) for s in steps if s['kind']=='select' and not s.get('option','').lstrip().startswith('#')}-{''}
                wanted=m.get('rank') or rank(m['name'])
                if not wanted or not selected or selected=={wanted}:lib.enrich_mission(m,recording.get('observed_texts',[]))
                from .quest_slots import template
                if template(steps,stage):data['board_templates'].setdefault(b['id'],{})[stage]=dict(steps=copy.deepcopy(steps),confirmation=confirmation)
            if recording['scope'] in ('menus','mission'):
                menus=data['menus'].setdefault(b['id'],[])
                for menu in recording.get('observed_menus',[]):
                    if menu not in menus and len(menus)<100:menus.append(menu)
                details=data['option_details'].setdefault(b['id'],{})
                for option,lines in recording.get('option_details',{}).items():
                    existing=details.setdefault(option,[])
                    for line in lines:
                        if line not in existing and len(existing)<30:existing.append(line)
            lib.save(data);q.recording=None;q.reason='Cadastro compartilhado salvo; disponivel para todas as rotas'
        elif command=='quest_library_test':
            if q.active or q.recording:raise ValueError('Pause a fila e encerre a gravacao antes de testar')
            if not self.allow_commands or self.upstream is None:raise ValueError('Entre no personagem pelo bot para executar o teste')
            if not self.tracker.observer.player_position_valid(time.monotonic()):raise ValueError('Posicao do personagem ainda nao recebida')
            mode=request.get('mode');o=self.tracker.observer
            if mode=='return':
                b=lib.board(data,request['board_id'])
                if PortalGuard.key(o.map_name)!=b['map']:raise ValueError('Comece o teste de Retorno em '+b['map'])
                q.start_validation([],b['map'],time.monotonic(),mode='return',label='Retorno: '+b['name'],library=data,return_board=b['id'])
            elif mode=='access':
                path=next((p for p in data['access_paths'] if p['id']==request.get('path_id')),None)
                if path is None:raise ValueError('Selecione um percurso salvo')
                if PortalGuard.key(o.map_name)!=PortalGuard.key(path['steps'][0]['map']):
                    raise ValueError('Para validar este percurso, comece no mapa '+path['steps'][0]['map'])
                b=lib.board(data,path['board_id'])
                q.start_validation(path['steps'],b['map'],time.monotonic(),mode=mode,label=path['name'],target_position=b['position'])
            elif mode in ('pickup','delivery'):
                from .quest_slots import effective_steps,confirmation
                identities=request.get('mission_ids') or [request['mission_id']]
                if len(set(identities))!=len(identities):raise ValueError('Missao repetida na selecao')
                # Missions of the same board are taken in one visit; Retorno only when leaving the board.
                identities=sorted(identities,key=lambda i:lib.board_rank(data,i))
                for identity in identities:
                    m=lib.mission(data,identity);b=lib.board(data,m['board_id'])
                    steps=effective_steps(data,m,mode);lib.validate_conversation(steps,b)
                    if not any(s['kind'] in ('verify_slot','verify_slot_absent') for s in steps) and not text(confirmation(data,m,mode)):
                        raise ValueError('Grave antes as opcoes e a confirmacao de '+('pegar' if mode=='pickup' else 'entregar')+': '+m['name'])
                m=lib.mission(data,identities[0]);b=lib.board(data,m['board_id'])
                names=', '.join(lib.mission(data,i)['name'] for i in identities)
                label=('Pegar: ' if mode=='pickup' else 'Entregar: ')+names
                if len(identities)==1:
                    q.start_validation([],b['map'],time.monotonic(),mode=mode,label=label,library=data,mission_id=m['id'])
                else:
                    q.start_validation([],b['map'],time.monotonic(),mode=mode,label=label,library=data,mission_ids=identities)
            else:raise ValueError('Tipo de teste desconhecido')
            if self.hunt:self.hunt.pause('Executando teste isolado')
            self.quest_base_settings=copy.deepcopy(self.settings);self.commands_blocked=False
        else:raise ValueError('Comando do cadastro desconhecido')
