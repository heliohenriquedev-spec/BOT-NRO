"""Quest itinerary integration: exclusive travel, guarded sends and normal combat at arrival."""
import copy
import struct
import time
from .quest_routes import QuestRoutes, load, save, STAGE_FIELDS, text
from .packet_encoder import move
from .portals import PortalGuard
from .quest_library_relay import SharedQuestRelay


class QuestRelay(SharedQuestRelay):
    def init_quests(self):
        self.quests=QuestRoutes();self.quest_base_settings=None;self.quest_hunt_id=None

    def quest_stop(self,reason):
        if self.quests.active:print('[ROTA] Parada: '+reason)
        self.quests.stop(reason)
        if self.hunt:self.hunt.pause(reason)
        if self.quest_base_settings is not None:
            settings=self.quest_base_settings;self.quest_base_settings=None
            self.apply_settings(settings)
        self.quest_hunt_id=None

    def quest_control(self,command,request,game_gate):
        if command.startswith('quest_library_'):
            if command=='quest_library_test' and not game_gate():raise ValueError('Conexao do jogo indisponivel para testar')
            self.library_control(command,request)
        elif command=='quest_test_stage_route':
            if self.quests.active or self.quests.recording:raise ValueError('Pause a fila e encerre a gravacao antes de testar')
            if not self.allow_commands or self.upstream is None or not game_gate():raise ValueError('Entre no personagem antes de testar')
            route=next((r for r in load() if r['id']==request.get('route_id')),None);stage=request.get('stage')
            if not route or stage not in ('pickup','delivery') or not route['mission_ids']:raise ValueError('Selecione uma rota com missoes compartilhadas')
            from . import quest_library as library
            from .quest_slots import effective_steps,confirmation
            data=library.load()
            for identity in route['mission_ids']:
                m=library.mission(data,identity);script=effective_steps(data,m,stage)
                library.validate_conversation(script,library.board(data,m['board_id']))
                if not any(s['kind']=='verify_slot' for s in script) and not confirmation(data,m,stage):raise ValueError('Falta gravar a confirmacao de '+m['name'])
            self.quests.start_validation([],route['target_map'],time.monotonic(),mode=stage,label=('Coleta: ' if stage=='pickup' else 'Entrega: ')+route['name'],library=data,mission_ids=route['mission_ids'])
            self.quests.known_routes=load()
            if self.hunt:self.hunt.pause('Executando etapa isolada da rota')
            self.quest_base_settings=copy.deepcopy(self.settings);self.commands_blocked=False
        elif command=='quest_test_route':
            if self.quests.active or self.quests.recording:raise ValueError('Pause a fila e encerre a gravacao antes de testar')
            if not self.allow_commands or self.upstream is None or not game_gate():raise ValueError('Entre no personagem antes de testar')
            route=next((r for r in load() if r['id']==request.get('route_id')),None)
            if not route or route['needs_recording'] or not route['steps']:raise ValueError('Grave e selecione uma rota completa antes de testar')
            if PortalGuard.key(self.tracker.observer.map_name)!=PortalGuard.key(route['steps'][0]['map']):
                raise ValueError('Comece no mapa '+route['steps'][0]['map']+' para validar esta viagem')
            self.quests.start_validation(route['steps'],route['target_map'],time.monotonic(),mode='travel',label=route['name'])
            if self.hunt:self.hunt.pause('Executando teste isolado')
            self.quest_base_settings=copy.deepcopy(self.settings);self.commands_blocked=False
        elif command=='quest_record':
            if request.get('stage','travel') not in STAGE_FIELDS:raise ValueError('Grave Retorno pelo cadastro compartilhado do quadro')
            if self.upstream is None:raise ValueError('Entre no personagem para gravar')
            if not any(r['id']==request['route_id'] for r in load()):raise ValueError('Selecione uma quest salva')
            self.quest_stop('Gravacao manual');self.quests.record(request['route_id'],request.get('stage','travel'))
            self.quests.map=self.tracker.observer.map_name
        elif command=='quest_record_save':
            recording=self.quests.recording
            if not recording:raise ValueError('Nenhuma gravacao em andamento')
            if self.native_frames.error:raise ValueError('Gravacao incompleta: '+self.native_frames.error)
            if recording.get('error'):raise ValueError(recording['error'])
            routes=load();route=next((r for r in routes if r['id']==recording['id']),None)
            if route is None:raise ValueError('Quest removida durante a gravacao')
            stage=recording.get('stage','travel')
            if stage in ('pickup','delivery'):
                confirmation=request.get('confirmation','').strip()
                if not confirmation:raise ValueError('Informe o trecho da mensagem de sucesso recebida do NPC')
                if not any(text(confirmation) in text(message) for message in recording.get('observed_texts',[])):
                    raise ValueError('A confirmacao informada nao apareceu nas respostas do NPC durante esta gravacao')
                route[stage+'_confirmation']=confirmation;route['lifecycle_enabled']=True
            route[STAGE_FIELDS[stage]]=recording['steps']
            if stage=='travel':
                route['target_map']=self.tracker.observer.map_name or '';route['needs_recording']=False
            route['notes']='Trechos gravados no jogo; revise coleta, viagem, entrega, confirmacoes e meta antes de executar.'
            save(routes);self.quests.recording=None;self.quests.reason='Trajeto salvo; confira as etapas antes de executar'
        elif command=='quest_record_cancel':
            self.quests.recording=None;self.quests.reason='Gravacao descartada'
        elif command=='quest_start':
            if self.quests.recording:raise ValueError('Salve ou descarte o trajeto antes de executar a fila')
            if not self.allow_commands:raise ValueError('Relay em modo somente observacao')
            if self.upstream is None or not game_gate():raise ValueError('Entre no personagem antes de executar a fila')
            if self.group_follower():raise ValueError('Desative o modo seguidor para executar rotas')
            self.quest_stop('Preparando fila')
            self.quests.start(load(),time.monotonic());self.quest_base_settings=copy.deepcopy(self.settings)
            self.commands_blocked=False
        elif command=='quest_stop':self.quest_stop('Fila pausada pelo usuario')
        else:raise ValueError('Comando de rota desconhecido')

    async def quest_tick(self,game_gate):
        q=self.quests
        if not q.active:return False
        if self.commands_blocked or not self.allow_commands:
            self.quest_stop('Envios bloqueados (F12/Parar)');return False
        if self.native_frames.error:
            self.quest_stop(self.native_frames.error);return False
        now=time.monotonic();observer=self.tracker.observer
        if self.upstream is None or not game_gate() or not observer.player_position_valid(now):
            if now-q.progress_at>30:self.quest_stop('Conexao ou posicao indisponivel; reinicie a fila quando conectado')
            return True
        if self.manual_control(now) or await self.update_presence_hold():
            q.progress_at=now;return True
        if q.phase=='hunt':
            if observer.map_name and PortalGuard.key(q.route['target_map'])!=PortalGuard.key(observer.map_name):
                self.quest_stop('Mapa mudou durante a quest');return True
            if self.quest_hunt_id!=q.route['id']:
                settings=copy.deepcopy(self.settings)
                settings.update(species=q.route['species'],auto_map_targets=False,monster_name_choices={},pvp_enabled=False)
                self.apply_settings(settings);self.hunt.start();self.quest_hunt_id=q.route['id']
            elif not self.hunt.enabled:
                self.quest_stop('Caca interrompida: '+self.hunt.reason);return True
            if q.kills>=q.route['kills']:
                self.hunt.pause('Objetivo da quest concluido');q.finish_hunt(now);self.quest_hunt_id=None
                if q.phase=='done':
                    reason=q.reason;self.quest_stop(reason);q.phase='done'
                return True
            return False
        # Only this executor may move while traveling. Combat resumes after destination confirmation.
        if self.hunt.enabled:self.hunt.pause('Percorrendo rota de quest')
        if self.walking_now():return True
        positions=observer.combat_positions(now)
        position=positions[0] if positions else observer.player
        action=q.plan(observer.map_name,position,self.collision_map(),self.portals,now)
        if q.phase=='paused':
            print('[ROTA] Parada: '+q.reason);self.quest_stop(q.reason);return True
        if q.phase=='done':
            reason=q.reason;self.quest_stop(reason);q.phase='done';return True
        if action is None:return True
        planned=(observer.map_name,q.phase,q.step,q.index)
        async with self.send_lock:
            if (not q.active or planned!=(observer.map_name,q.phase,q.step,q.index)
                or not self.native_frames.ready or self.commands_blocked or not game_gate() or self.upstream is None):return True
            if action['kind']=='move':payload=move(*action['position'])
            elif action['kind']=='npc':payload=struct.pack('<HIB',0x90,action['entity_id'],1)
            elif action['kind'] in ('select','cancel'):payload=struct.pack('<HIB',0xb8,action['entity_id'],action['choice'])
            else:payload=struct.pack('<HI',0xb9 if action['kind']=='next' else 0x146,action['entity_id'])
            opcode=struct.unpack_from('<H',payload)[0]
            if action['kind']!='move' and self.native_frames.fallback().get(opcode)!=len(payload):
                self.quest_stop(f'Comando de NPC {opcode:04X} nao validado para este cliente');return True
            if action['kind']!='move':
                step=q.steps[q.step] if q.steps and q.step<len(q.steps) else {}
                detail=step.get('option') or step.get('name') or ''
                if action.get('extra'):detail={'select':'Sim (confirmacao do NPC)','cancel':'(encerrando menu nao gravado)'}.get(action['kind'],'(pagina extra do dialogo)')
                print(f"[ROTA] {q.reason} • etapa {q.step+1}: {action['kind']} {detail} (NPC {action['entity_id']})".rstrip())
            q.sent(action,now)
            self.trace_map_send('bot',opcode,len(payload));self.upstream.write(payload);await self.upstream.drain()
        return True
