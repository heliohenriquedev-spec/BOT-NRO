"""Quest itinerary integration: exclusive travel, guarded sends and normal combat at arrival."""
import copy
import struct
import time
from pathlib import Path
from .quest_routes import QuestRoutes, load, save, STAGE_FIELDS, text
from .packet_encoder import move, STAND
from .portals import PortalGuard
from .quest_library_relay import SharedQuestRelay
from .database_hunt import DATABASE_HUNT, database_hunt_route, goal_reached


class QuestRelay(SharedQuestRelay):
    def init_quests(self):
        self.quests=QuestRoutes();self.quest_base_settings=None;self.quest_hunt_id=None

    def quest_stop(self,reason):
        was_database_hunt = bool(self.quests.route and self.quests.route.get('id') == DATABASE_HUNT)
        if self.quests.active:print('[ROTA] Parada: '+reason)
        if self.quests.active or self.quests.phase=='done':self.save_progress(time.monotonic(),force=True)
        if reason!=self.quests.reason:self.quests.resume=None  # paused by the player: stays paused
        self.quests.stop(reason)
        if self.hunt:self.hunt.pause(reason)
        if self.quest_base_settings is not None:
            settings=self.quest_base_settings;self.quest_base_settings=None
            self.apply_settings(settings,map_overlay=was_database_hunt and bool(getattr(self,'map_behavior_base',None)))
            if was_database_hunt and getattr(self,'map_behavior_base',None):
                self.map_behavior_signature=None;self.map_behavior_effective=None;self.map_behavior_poll=0
        self.quest_hunt_id=None

    def quest_control(self,command,request,game_gate):
        self.quests.route_position=self.tracker.observer.player
        self.quests.route_position_map=self.tracker.observer.map_name
        self.quests.route_collision=self.map_repository.get if self.map_repository else None
        if command in ('quest_start','quest_resume','quest_hunt_database','quest_test_route','quest_test_stage_route',
                       'quest_map_test','quest_record','quest_map_record','quest_bg_record'):
            self.bg_attempt=None  # another task takes over: no more BG retries afterwards
        if command in ('quest_start','quest_resume','quest_hunt_database'):
            self.mob_scan.reset_failures()  # started again: @showmobs is tried again on every map
        from . import map_routes, quest_daily, quest_extras
        try:self.quests.extras=quest_extras.for_character(quest_extras.load(),(self.own_look or {}).get('name'))
        except OSError as exc:print('[ROTA] '+str(exc))  # keeps the last read
        if command=='quest_extras_equip':
            from .quest_extras import Errand
            if self.quests.active or self.quests.recording:raise ValueError('Pause a fila antes de equipar pelo painel')
            if not self.allow_commands or self.upstream is None or not game_gate():raise ValueError('Entre no personagem antes')
            if self.commands_blocked:raise ValueError('Envios parados (Parar envios): libere antes de equipar')
            what=request.get('what');extras=self.quests.extras
            if what=='mount' and not (extras.get('mount') or {}).get('item_id'):raise ValueError('Escolha a montaria primeiro')
            if what=='combat' and not extras.get('combat_items'):raise ValueError('Escolha os itens de combate primeiro')
            kind={'mount':'mount','combat':'gear'}[what]
            self.quests.errands=[Errand(kind,dict(extras,displaced=[]),time.monotonic())]
            self.quests.reason='Equipando '+('a montaria' if what=='mount' else 'os itens de combate')
            return
        if command in ('quest_extras_learn','quest_extras_learn_cancel'):
            if command=='quest_extras_learn_cancel':self.quests.learning=None;self.quests.reason='Aprendizado cancelado';return
            if self.quests.active or self.quests.recording:raise ValueError('Pause a fila e encerre a gravacao antes')
            if self.upstream is None:raise ValueError('Entre no personagem antes')
            what=request.get('what')
            if what not in ('voltar','mount'):raise ValueError('Aprendizado desconhecido')
            self.quests.learning=dict(what=what)
            self.quests.reason=('Digite @voltar no chat do jogo' if what=='voltar' else
                                'Equipe a montaria no jogo, fora de combate')
            return
        if command.startswith('quest_library_'):
            if command=='quest_library_test' and not game_gate():raise ValueError('Conexao do jogo indisponivel para testar')
            self.library_control(command,request)
            if self.quests.active:self.quests.map_routes=map_routes.adopt_inner_portals(map_routes.load(),self.portals);self.quests.slot_owner=quest_daily.load_slots()
        elif command.startswith('quest_map_'):
            self.map_route_control(command,request,game_gate)
        elif command.startswith('quest_bg_'):
            self.bg_control(command,request,game_gate)
        elif command.startswith('quest_heal_'):
            self.heal_control(command,request)
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
                if not any(s['kind'] in ('verify_slot','verify_slot_absent') for s in script) and not confirmation(data,m,stage):raise ValueError('Falta gravar a confirmacao de '+m['name'])
            ordered=sorted(route['mission_ids'],key=lambda i:library.board_rank(data,i))
            self.quests.start_validation([],route['target_map'],time.monotonic(),mode=stage,label=('Coleta: ' if stage=='pickup' else 'Entrega: ')+route['name'],library=data,mission_ids=ordered,map_routes=map_routes.adopt_inner_portals(map_routes.load(),self.portals))
            self.quests.slot_owner=quest_daily.load_slots()
            self.quests.known_routes=load()
            if self.hunt:self.hunt.pause('Executando etapa isolada da rota')
            self.quest_base_settings=copy.deepcopy(self.settings);self.commands_blocked=False
        elif command=='quest_test_route':
            if self.quests.active or self.quests.recording:raise ValueError('Pause a fila e encerre a gravacao antes de testar')
            if not self.allow_commands or self.upstream is None or not game_gate():raise ValueError('Entre no personagem antes de testar')
            if not self.tracker.observer.map_name:raise ValueError('Aguarde carregar o mapa do personagem antes de executar a viagem')
            route=next((r for r in map_routes.apply(load()) if r['id']==request.get('route_id')),None)
            if not route or route['needs_recording'] or not route['steps']:raise ValueError('Escolha o mapa de caca da rota antes de testar')
            from . import quest_library
            self.quests.start_validation(route['steps'],route['target_map'],time.monotonic(),mode='travel',label=route['name'],library=quest_library.load(),map_routes=map_routes.adopt_inner_portals(map_routes.load(),self.portals),connect_from=self.tracker.observer.map_name,known_routes=map_routes.apply(load()))
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
            from .map_routes import compact
            route[STAGE_FIELDS[stage]]=compact(recording['steps'])
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
            entries=map_routes.adopt_inner_portals(map_routes.load(),self.portals)
            self.know_quest_character()
            self.quests.start(map_routes.apply(load(),entries),time.monotonic(),map_routes=entries,replay_completed=True)
            from . import quest_daily
            self.quests.slot_owner=quest_daily.load_slots()
            self.quest_base_settings=copy.deepcopy(self.settings)
            self.commands_blocked=False
        elif command=='quest_resume':
            from . import quest_progress
            if self.quests.recording:raise ValueError('Salve ou descarte o trajeto antes de retomar a fila')
            if not self.allow_commands:raise ValueError('Relay em modo somente observacao')
            if self.upstream is None or not game_gate():raise ValueError('Entre no personagem antes de retomar a fila')
            self.know_quest_character()
            saved=quest_progress.load()
            if not saved:raise ValueError('Nenhum progresso salvo para retomar')
            character=(self.own_look or {}).get('name')
            if saved.get('character') and character and saved['character']!=character:
                raise ValueError('Progresso salvo pertence ao personagem '+saved['character'])
            self.quest_stop('Preparando para retomar')
            entries=map_routes.adopt_inner_portals(map_routes.load(),self.portals)
            self.know_quest_character()
            self.quests.resume_from(map_routes.apply(load(),entries),saved,time.monotonic(),map_routes=entries,
                                    map_name=self.tracker.observer.map_name)
            self.quests.slot_owner=quest_daily.load_slots()
            self.quest_base_settings=copy.deepcopy(self.settings);self.commands_blocked=False
            print('[ROTA] '+self.quests.reason)
        elif command=='quest_hunt_database':
            # Database -> "Cacar": travel along the recorded path to the map and hunt the chosen
            # monsters there with the combat settings; a temporary quest, never saved in the queue.
            if self.quests.recording:raise ValueError('Salve ou descarte o trajeto antes de cacar')
            if not self.allow_commands:raise ValueError('Relay em modo somente observacao')
            if self.upstream is None or not game_gate():raise ValueError('Entre no personagem antes de cacar')
            if self.group_follower():raise ValueError('Desative o modo seguidor para cacar pela database')
            from .npc_transports import as_entries
            route=database_hunt_route(request,map_routes.load()+as_entries(self.npc_transports.known),self.tracker.observer.map_name,self.portals.destinations,self.tracker.observer.player)
            self.quest_stop('Preparando caca pela database')
            entries=map_routes.adopt_inner_portals(map_routes.load(),self.portals)
            self.know_quest_character()
            self.quests.start(map_routes.apply([route],entries),time.monotonic(),map_routes=entries)
            self.quests.slot_owner=quest_daily.load_slots()
            self.quest_base_settings=copy.deepcopy(getattr(self,'map_behavior_base',None) or self.settings);self.commands_blocked=False
            print(f"[ROTA] Caca pela database: {route['target_map']} ({len(route['species'])} monstros)")
        elif command=='quest_stop':self.bg_attempt=None;self.quest_stop('Fila pausada pelo usuario')
        else:raise ValueError('Comando de rota desconhecido')
        if command in ('quest_start','quest_resume'):
            self.save_progress(time.monotonic(),force=True)

    async def quest_errand(self,now,game_gate):
        """@voltar, mount or combat equipment: kill what is around, wait out of combat, then act."""
        from .portals import chebyshev
        q=self.quests;errand=q.errands[0];o=self.tracker.observer
        # Only monsters attacking the character keep it in combat; peaceful ones around are left alone.
        # Looked up among everything seen on the map, not only the hunt targets: a monster that is
        # not (or no longer) a quest target still keeps the character in combat.
        from .network_targets import is_player_id
        near=[]
        for identity,hit_at in q.body.attackers.items():
            e=self.inventory.entities.get(identity)
            if (e and e['present_last_observation'] and not is_player_id(identity) and now-hit_at<=15 and o.player
                and chebyshev(e.get('destination') or e['position'],o.player)<=errand.config['clear_radius']*2):
                near.append((identity,e['species_id']))
        if errand.kind=='voltar' and o.player:
            # Before @voltar: any monster within the configured radius goes too, attacking yet or not,
            # hitting or missing, whatever species: nothing near may break the casting.
            from .presence_guard import monster_sprite
            listed={i for i,_ in near}
            near+=[(i,e['species_id']) for i,e in self.inventory.entities.items() if i not in listed and e['present_last_observation']
                   and not is_player_id(i) and monster_sprite(e['species_id'])
                   and chebyshev(e.get('destination') or e['position'],o.player)<=errand.config['clear_radius']]
        if not near and errand.kind!='gear' and now-errand.started>45 and now-q.body.last_combat<5 and o.player:
            # Still hit after 45 s and the attacker was not identified: clear what is right around.
            near=[(i,e['species_id']) for i,e in self.inventory.entities.items() if e['present_last_observation']
                  and not is_player_id(i) and i>=110000000 and chebyshev(e.get('destination') or e['position'],o.player)<=errand.config['clear_radius']]
        action,value=errand.step(q.body,near,now,name=(self.own_look or {}).get('name'))
        title={'voltar':'@voltar','mount':'Montaria','gear':'Equipamentos'}[errand.kind]
        q.reason=title+': '+errand.reason;q.progress_at=now
        if action=='clear':
            if self.hunt is None:self.quest_stop('Caca indisponivel para matar os monstros ao redor');return True
            key=('clear',tuple(value))
            if self.quest_hunt_id!=key:
                settings=copy.deepcopy(self.settings)
                settings.update(species=list(value),auto_map_targets=False,monster_name_choices={},pvp_enabled=False)
                self.apply_settings(settings);self.hunt.start();self.quest_hunt_id=key
            elif not self.hunt.enabled:
                self.quest_stop('Caca interrompida: '+self.hunt.reason);return True
            return False  # the normal hunt kills them
        if self.hunt and self.hunt.enabled:self.hunt.pause(q.reason)
        if isinstance(self.quest_hunt_id,tuple):self.quest_hunt_id=None
        if action=='done':
            print('[ROTA] '+q.reason);q.errand_done();return True
        if action=='fail':
            print('[ROTA] Parada: '+value);self.quest_stop(value);return True
        if action=='wait' or self.walking_now():return True
        payload=value if action=='chat' else struct.pack('<HHH',0xa9,*value)
        opcode=struct.unpack_from('<H',payload)[0]
        expected=self.native_frames.fallback().get(opcode)
        if expected not in (-1,len(payload)):
            self.quest_stop(f'Pacote {opcode:04X} nao validado para este cliente');return True
        async with self.send_lock:
            if not self.native_frames.ready or self.commands_blocked or not game_gate() or self.upstream is None:return True
            print('[ROTA] '+q.reason)
            if action=='chat':q.voltar_sent_at=now
            self.trace_map_send('bot',opcode,len(payload));self.upstream.write(payload);await self.upstream.drain()
        return True

    def map_route_control(self,command,request,game_gate):
        """Aba Mapas de caca: record a path once (portals, NPC transports) and reuse it in every route."""
        from . import map_routes
        q=self.quests;o=self.tracker.observer
        if command=='quest_map_record':
            if q.active or q.recording:raise ValueError('Pause a fila e encerre a gravacao anterior')
            if self.upstream is None or not o.player_position_valid(time.monotonic()) or not o.map_name:
                raise ValueError('Entre no personagem e aguarde a posicao antes de gravar')
            self.quest_stop('Gravando rota ate mapa de caca');q.record('map','travel')
            q.recording.update(scope='map',label='Rota ate mapa de caca',replace_id=request.get('replace_id'))
            q.map=o.map_name;q.append(dict(kind='walk',map=o.map_name,position=list(o.player)))
        elif command=='quest_map_save':
            recording=q.recording
            if not recording or recording.get('scope')!='map':raise ValueError('Nenhuma rota de mapa sendo gravada')
            if recording.get('error') or self.native_frames.error:raise ValueError(recording.get('error') or self.native_frames.error)
            if self.walking_now():raise ValueError('Aguarde o personagem parar no mapa de caca antes de salvar')
            steps=copy.deepcopy(recording['steps'])
            if not any(s['kind']=='wait_map' for s in steps):raise ValueError('Atravesse ao menos um portal/teletransporte ate o mapa de caca antes de salvar')
            if steps[-1].get('position')!=list(o.player):steps.append(dict(kind='walk',map=o.map_name,position=list(o.player)))
            full=copy.deepcopy(steps)
            steps=map_routes.compact(steps)  # NPCs, choices, each map's way out and the end; walking is computed
            entries=map_routes.adopt_inner_portals(map_routes.load(),self.portals);name=(request.get('name') or '').strip()
            # A name for each map passed, typed in the save window; an empty one keeps the old name.
            names={PortalGuard.key(m):(n or '').strip() for m,n in (request.get('names') or {}).items()}
            # Every map passed on the way gets its own route too (start -> that map), ready to be chosen.
            for index,step in enumerate(full[:-1]):
                if step['kind']!='wait_map' or PortalGuard.key(step['map'])==PortalGuard.key(o.map_name):continue
                partial=map_routes.compact(full[:index+1])
                same=next((e for e in entries if PortalGuard.key(e['target_map'])==PortalGuard.key(step['map'])
                           and PortalGuard.key(e['steps'][0]['map'])==PortalGuard.key(full[0]['map'])),None)
                inner=map_routes.inner_portals(partial,self.portals)
                label=names.get(PortalGuard.key(step['map']),'')
                if same:same['steps']=partial;same['inner_portals']=inner;same['name']=label or same['name']
                else:entries.append(dict(name=label,target_map=step['map'],steps=partial,inner_portals=inner))
            inner=map_routes.inner_portals(full,self.portals)
            entry=dict(id=recording.get('replace_id') or None,name=name,target_map=o.map_name,steps=steps,inner_portals=inner)
            old=next((e for e in entries if entry['id'] and e.get('id')==entry['id']),None) or next(
                (e for e in entries if PortalGuard.key(e['target_map'])==PortalGuard.key(o.map_name)
                 and PortalGuard.key(e['steps'][0]['map'])==PortalGuard.key(full[0]['map'])),None)
            if old:old.update(steps=steps,target_map=o.map_name,name=name or old['name'],inner_portals=inner)
            else:entry.pop('id');entries.append(entry)
            map_routes.save(entries);q.recording=None;q.reason='Rota ate '+o.map_name+' salva; escolha-a em Editar rota'
        elif command=='quest_map_test':
            if q.active or q.recording:raise ValueError('Pause a fila e encerre a gravacao antes de testar')
            if not self.allow_commands or self.upstream is None or not game_gate():raise ValueError('Entre no personagem antes de testar')
            entries=map_routes.adopt_inner_portals(map_routes.load(),self.portals);entry=next((e for e in entries if e['id']==request.get('id')),None)
            if entry is None:raise ValueError('Selecione uma rota de mapa salva')
            q.start_validation(entry['steps'],entry['target_map'],time.monotonic(),mode='travel',label='Mapa: '+entry['name'],map_routes=entries)
            if self.hunt:self.hunt.pause('Executando teste isolado')
            self.quest_base_settings=copy.deepcopy(self.settings);self.commands_blocked=False
        else:raise ValueError('Comando de rota de mapa desconhecido')

    def heal_control(self,command,request):
        """Record once the talk with the healer at the save point (Curandeira), used after a death."""
        from . import bg_entry, quest_extras
        q=self.quests;o=self.tracker.observer
        if command=='quest_heal_record':
            if q.active or q.recording:raise ValueError('Pause a fila e encerre a gravacao anterior')
            if self.upstream is None or not o.player_position_valid(time.monotonic()) or not o.map_name:
                raise ValueError('Entre no personagem e aguarde a posicao antes de gravar')
            self.quest_stop('Gravando a cura');q.record('heal','travel')
            q.recording.update(scope='heal',label='Cura na Curandeira')
            q.map=o.map_name;q.append(dict(kind='walk',map=o.map_name,position=list(o.player)))
            q.reason='Gravando a cura: va ate a Curandeira, fale com ela, passe as falas e clique em Salvar cura'
        elif command=='quest_heal_save':
            recording=q.recording
            if not recording or recording.get('scope')!='heal':raise ValueError('Nenhuma cura sendo gravada')
            if recording.get('error') or self.native_frames.error:raise ValueError(recording.get('error') or self.native_frames.error)
            entry=bg_entry.recorded_entry(recording['steps'],o.map_name,o.player)
            config=quest_extras.load();config.update(heal_steps=entry['steps'],heal_map=PortalGuard.key(o.map_name))
            quest_extras.save(config)
            q.recording=None;q.reason='Cura gravada ('+o.map_name+')'
        elif command=='quest_heal_test':
            heal=quest_extras.load().get('heal_steps') or []
            if not heal:raise ValueError('Grave a cura antes de testar')
            if q.active or q.recording:raise ValueError('Pause a fila e encerre a gravacao antes de testar')
            if self.upstream is None or not o.map_name:raise ValueError('Entre no personagem antes de testar')
            from . import map_routes
            entries=map_routes.adopt_inner_portals(map_routes.load(),self.portals)
            q.start_validation(heal,heal[-1]['map'],time.monotonic(),mode='travel',label='Teste da cura',map_routes=entries,
                               connect_from=o.map_name,known_routes=map_routes.apply(load(),entries))
            if self.hunt:self.hunt.pause('Testando a cura')
            self.quest_base_settings=copy.deepcopy(self.settings);self.commands_blocked=False
        elif command=='quest_heal_cancel':
            if q.recording and q.recording.get('scope')=='heal':q.recording=None;q.reason='Gravacao da cura descartada'
        else:raise ValueError('Comando de cura desconhecido')

    REVIVE_RETRY=8.0  # s: "return to the save point" sent again while still dead
    REVIVE_TRIES=4

    async def revive_after_death(self,now,game_gate):
        """Dead during the hunt or a trip with "Ao morrer" on: return to the save point (B2 00 00,
        the button of the death window). Returns False when the queue must stop instead."""
        q=self.quests
        try:config=self.extras_config()
        except OSError:return False
        if not config.get('revive_enabled') or q.validation or q.phase not in ('hunt','travel'):return False
        revive=getattr(self,'revive',None)
        if revive is None:
            revive=self.revive=dict(tries=0,sent_at=-1e9,phase=q.phase)
            if self.hunt:self.hunt.pause('Personagem morreu: voltando ao ponto de retorno')
            print('[ROTA] Personagem morreu: voltando ao ponto de retorno para curar e retomar')
        if now-revive['sent_at']<self.REVIVE_RETRY:return True
        if revive['tries']>=config.get('revive_attempts',self.REVIVE_TRIES):
            self.revive=None
            q.reason='Limite de tentativas de retorno apos morrer atingido'
            return False
        sent=await self.send_restart(game_gate)
        if sent is None:return False
        if not sent:return True
        revive['tries']+=1;revive['sent_at']=now
        q.reason='Personagem morreu: voltando ao ponto de retorno'
        return True

    async def send_restart(self,game_gate):
        """The death window's return to the save point (B2 00 00). None: not possible here."""
        if self.upstream is None or not game_gate():return False
        payload=bytes((0xb2,0,0))
        if self.native_frames.fallback().get(0xb2) not in (-1,len(payload)):return None
        async with self.send_lock:
            if not self.native_frames.ready or not game_gate() or self.upstream is None:return False
            self.trace_map_send('bot',0xb2,len(payload))
            self.upstream.write(payload)
            await self.upstream.drain()
        return True

    def extras_config(self):
        """quest_extras.json, read again only when the file changes: the death watch asks every tick."""
        from . import quest_extras
        try:
            info=quest_extras.FILE.stat();stamp=(str(quest_extras.FILE),info.st_mtime_ns,info.st_size)
        except OSError:
            stamp=None
        cached=getattr(self,'extras_cache',None)
        if cached is None or stamp is None or cached[0]!=stamp:
            cached=self.extras_cache=(stamp,quest_extras.load())
        return cached[1]

    async def hunt_death_watch(self,now,game_gate):
        """Hunting without the queue (Iniciar): on death, back to the save point, the healer and the map
        where it died, then the same hunt again. True while this owns the character."""
        from . import quest_extras, map_routes
        q=self.quests;o=self.tracker.observer
        pending=getattr(self,'hunt_revive',None)
        try:config=self.extras_config()
        except OSError:return False
        if pending is None:
            if q.active or q.recording or not (self.hunt and self.hunt.enabled) or o.player_alive or not o.map_name:return False
            if not config.get('revive_enabled'):return False
            pending=self.hunt_revive=dict(map=o.map_name,tries=0,sent_at=-1e9,stage='dead',settings=copy.deepcopy(self.settings))
            self.hunt.pause('Personagem morreu: voltando ao ponto de retorno')
            print('[ROTA] Personagem morreu na caca: voltando ao ponto de retorno para curar e voltar a '+o.map_name)
        if pending['stage']=='dead':
            if o.player_alive and o.player_position_valid(now):
                try:heal=quest_extras.load().get('heal_steps') or []
                except OSError:heal=[]
                entries=map_routes.adopt_inner_portals(map_routes.load(),self.portals)
                start=heal or [dict(kind='walk',map=o.map_name,position=list(o.player))]
                q.start_validation(start,pending['map'],now,mode='travel',label='Voltar a '+pending['map'],map_routes=entries,
                                   known_routes=map_routes.apply(load(),entries))
                try:
                    key=PortalGuard.key;here=key(o.map_name);steps=[]
                    if heal:
                        steps+=(q.connection(here,key(heal[0]['map'])) if here!=key(heal[0]['map']) else [])+copy.deepcopy(heal)
                        here=key(heal[-1]['map'])
                    steps+=q.connection(here,key(pending['map']))
                except ValueError as exc:
                    self.hunt_revive=None;q.stop('Revivido, mas sem caminho de volta: '+str(exc));return False
                q.steps=steps;q.reason='Revivido: '+('curando e ' if heal else '')+'voltando a '+pending['map']
                self.quest_base_settings=copy.deepcopy(pending['settings']);self.commands_blocked=False
                pending['stage']='trip';print('[ROTA] '+q.reason);return True
            if not o.player_alive and now-pending['sent_at']>=self.REVIVE_RETRY:
                if pending['tries']>=config.get('revive_attempts',self.REVIVE_TRIES):
                    self.hunt_revive=None
                    self.hunt.reason='Limite de tentativas de retorno apos morrer atingido'
                    print('[ROTA] '+self.hunt.reason)
                    return False
                sent=await self.send_restart(game_gate)
                if sent is None:self.hunt_revive=None;return False
                if sent:pending['tries']+=1;pending['sent_at']=now
            return True
        if q.active:return False  # the trip runs as a normal quest travel
        self.hunt_revive=None
        if q.phase=='done' and q.validation and q.validation.get('completed'):
            self.apply_settings(pending['settings']);self.hunt.start()
            print('[ROTA] De volta a '+pending['map']+': caca retomada')
        return False

    def resume_after_revive(self,now):
        """Alive again at the save point: the recorded healer talk, then the way back to the hunt."""
        from . import quest_extras
        q=self.quests;o=self.tracker.observer;self.revive=None
        try:heal=quest_extras.load().get('heal_steps') or []
        except OSError:heal=[]
        q.enter_stage('travel',now)
        steps=[]
        try:
            if heal:
                here,start=PortalGuard.key(o.map_name),PortalGuard.key(heal[0]['map'])
                steps+=(q.connection(here,start) if here!=start else [])+copy.deepcopy(heal)
                steps+=q.itinerary(heal[-1]['map'])
            else:
                steps+=q.itinerary(o.map_name)
        except ValueError as exc:
            self.quest_stop('Revivido, mas sem caminho de volta: '+str(exc));return
        q.steps=steps
        q.reason='Revivido: '+('curando na Curandeira e ' if heal else '')+'voltando ao mapa de caca: '+q.route['name']
        print('[ROTA] '+q.reason)

    def bg_control(self,command,request,game_gate):
        """Aba BG: record how this character joins each battleground queue, then replay it."""
        from . import bg_entry, map_routes
        q=self.quests;o=self.tracker.observer
        if command=='quest_bg_record':
            mode=bg_entry.check_mode(request.get('mode'))
            if q.active or q.recording:raise ValueError('Pause a fila e encerre a gravacao anterior')
            if self.upstream is None or not o.player_position_valid(time.monotonic()) or not o.map_name:
                raise ValueError('Entre no personagem e aguarde a posicao antes de gravar')
            self.quest_stop('Gravando entrada na BG '+mode);q.record('bg','travel')
            q.recording.update(scope='bg',label='Entrada na BG '+mode,bg_mode=mode)
            q.map=o.map_name;q.append(dict(kind='walk',map=o.map_name,position=list(o.player)))
            q.reason='Gravando entrada na BG '+mode+': selecione a entrada manualmente no jogo; pode repetir a conversa. Ao finalizar, clique em Salvar gravacao (fica a ultima tentativa).'
        elif command=='quest_bg_save':
            recording=q.recording
            if not recording or recording.get('scope')!='bg':raise ValueError('Nenhuma entrada de BG sendo gravada')
            if recording.get('error') or self.native_frames.error:raise ValueError(recording.get('error') or self.native_frames.error)
            entry=bg_entry.recorded_entry(recording['steps'],o.map_name,o.player)
            bg_entry.save_entry(recording['bg_mode'],entry,bg_entry.npc_lines(recording.get('observed_texts',[])))
            q.recording=None;q.reason='NPC da BG '+recording['bg_mode']+' salvo'
        elif command=='quest_bg_capture':
            which=request.get('which')
            if which not in ('error','queue'):raise ValueError('Mensagem desconhecida')
            self.bg_capture=dict(which=which,until=time.monotonic()+bg_entry.CAPTURE_SECONDS)
            q.reason=('Gravando mensagem de '+('erro' if which=='error' else 'sucesso')+': fale com o NPC da BG no jogo '
                      +('quando ele nao deixar se inscrever' if which=='error' else 'e se inscreva'))
        elif command=='quest_bg_cancel':
            if q.recording and q.recording.get('scope')=='bg':q.recording=None;q.reason='Gravacao da BG descartada'
        elif command=='quest_bg_enter':
            if getattr(self,'bg_attempt',None) is not None:
                raise ValueError('Ja existe uma tentativa de BG em andamento; use Parar tentativas antes de iniciar outra')
            modes=[bg_entry.check_mode(m) for m in (request.get('modes') or [request.get('mode')])]
            modes=list(dict.fromkeys(modes))
            missing=[m for m in modes if bg_entry.load().get(m) is None]
            if missing:raise ValueError('Grave antes o NPC da BG '+', '.join(missing))
            config=bg_entry.messages()
            if not (config['error'] or config['queue']):raise ValueError('Grave a mensagem de erro ou a de sucesso na aba BG')
            if q.active or q.recording:raise ValueError('Pause a fila e encerre a gravacao antes de entrar na BG')
            if not self.allow_commands or self.upstream is None or not game_gate():raise ValueError('Entre no personagem antes')
            if not o.map_name:raise ValueError('Aguarde carregar o mapa do personagem')
            self.bg_attempt=dict(pending=modes,registered=[],index=0,config=config,stop_all=request.get('stop_all',True) is not False,
                                 tries={m:0 for m in modes},next_at=None,queued=False,refused=False,answered=False)
            self.bg_try(time.monotonic())
        else:raise ValueError('Comando de BG desconhecido')

    def bg_mode(self,attempt):
        return attempt['pending'][attempt['index']%len(attempt['pending'])]

    def bg_try(self,now):
        """One attempt at the current BG's NPC: walk there and make the recorded choices."""
        from . import bg_entry, map_routes
        attempt=self.bg_attempt;mode=self.bg_mode(attempt);entry=bg_entry.load().get(mode)
        if self.quests.active:
            return  # a trip/dialogue is still running; do not start a second registration
        if entry is None:self.bg_attempt=None;raise ValueError('NPC da BG '+mode+' removido')
        q=self.quests;o=self.tracker.observer
        entries=map_routes.adopt_inner_portals(map_routes.load(),self.portals)
        steps=entry['steps'];target_map=entry['target_map']
        stationary=attempt['config'].get('stationary',False)
        if stationary:
            last=max(i for i,s in enumerate(steps) if s['kind']=='npc')
            npc=steps[last]
            if PortalGuard.key(npc['map'])!=PortalGuard.key(o.map_name):
                self.bg_attempt=None
                raise ValueError('BG sem caminhada: entre no mapa do NPC antes de tentar')
            steps=[copy.deepcopy(npc)]+[copy.deepcopy(s) for s in steps[last+1:] if s['kind'] in ('select','next','close')]
            target_map=npc['map']
        attempt['tries'][mode]+=1
        attempt.update(next_at=None,queued=False,refused=False,answered=False,next_poll=0,response_wait_at=None)
        q.start_validation(steps,target_map,now,mode='travel',label='BG '+mode,
                           map_routes=entries,connect_from=None if stationary else o.map_name,known_routes=map_routes.apply(load(),entries))
        if stationary:q.validation['stationary_npc']=True
        q.errands=[errand for errand in q.errands if errand.kind!='mount']
        q.reason=f"Inscrevendo na BG {mode} (tentativa {attempt['tries'][mode]})"
        if len(attempt['pending'])>1:q.reason+=' • na fila de tentativas: '+', '.join(attempt['pending'])
        if self.hunt:self.hunt.pause('Entrando na BG '+mode)
        self.quest_base_settings=copy.deepcopy(self.settings);self.commands_blocked=False
        print('[ROTA] '+q.reason)

    def bg_observe(self,events):
        """The NPC's answer to this attempt: queue message, error message or something else.
        Also takes the line asked by "Gravar mensagem de erro/sucesso"."""
        from .bg_entry import answer, message_line, save_message, messages, registered_mode
        capture=getattr(self,'bg_capture',None)
        if capture and time.monotonic()>capture['until']:
            self.bg_capture=capture=None;self.quests.reason='Gravacao da mensagem da BG expirou; clique de novo'
        if capture:
            for e in events:
                line=message_line(e.get('text')) if e['kind']=='npc_dialog' else ''
                if line:
                    self.bg_capture=None
                    saved=save_message(capture['which'],line)
                    self.quests.reason=('Mensagem de '+('erro' if capture['which']=='error' else 'sucesso')+' gravada: '+saved)
                    print('[ROTA] '+self.quests.reason);break
        attempt=getattr(self,'bg_attempt',None)
        recording=self.quests.recording or {}
        recording_bg=recording.get('scope')=='bg'
        if not attempt and not recording_bg:return
        config=attempt['config'] if attempt else messages()
        for e in events:
            if e['kind']=='npc_dialog' and e.get('text'):
                if recording_bg and e.get('entity_id')!=recording.get('npc_id'):continue
                kind=answer(e['text'],config)
                reported_mode=registered_mode(e['text']) if kind=='registered_mode' else None
                if reported_mode:
                    kind='other_queue' if attempt and reported_mode!=self.bg_mode(attempt) else 'queue'
                if attempt:
                    attempt['answered']=True
                    attempt['next_poll']=0  # process new evidence on the next relay tick
                    if kind=='queue':attempt['queued']=True
                    elif kind=='error':attempt['refused']=True
                    elif kind=='other_queue':attempt['other_queue']=reported_mode
                if kind in ('queue','error','other_queue') and e.get('entity_id') and not getattr(self,'bg_dialog_close',None):
                    self.bg_dialog_close=dict(entity_id=e['entity_id'],map=self.tracker.observer.map_name,
                                              deadline=time.monotonic()+3,result=kind,registered_mode=reported_mode)

    async def close_bg_result_dialog(self,game_gate):
        """Close a success/refusal dialogue without choosing 'cancel registration'."""
        pending=getattr(self,'bg_dialog_close',None)
        if not pending:return
        async with self.send_lock:
            observer=self.tracker.observer;dialog=self.quests.dialog
            if (observer.map_name!=pending['map'] or time.monotonic()>pending['deadline']
                or self.commands_blocked or not self.allow_commands):
                self.bg_dialog_close=None;return
            if not game_gate() or self.upstream is None or not self.native_frames.ready:return
            if not dialog:return
            if dialog.get('entity_id')!=pending['entity_id']:
                self.bg_dialog_close=None;return
            action=dialog.get('action')
            if action not in ('menu','next','close'):return
            opcode=0xb8 if action=='menu' else 0x146
            payload=(struct.pack('<HIB',opcode,pending['entity_id'],255) if action=='menu'
                     else struct.pack('<HI',opcode,pending['entity_id']))
            if self.native_frames.fallback().get(opcode)!=len(payload):
                self.bg_dialog_close=None;return
            self.bg_dialog_close=None  # at most one close, even when the connection fails
            self.quests.dialog=None
            self.trace_map_send('bot',opcode,len(payload))
            self.upstream.write(payload);await self.upstream.drain()
            attempt=getattr(self,'bg_attempt',None)
            if pending.get('result')=='error' and not (attempt and attempt['queued']):
                if attempt and self.quests.active:self.quest_stop('NPC da BG recusou a inscricao; dialogo encerrado')
                if attempt:self.quests.reason='BG: evento indisponivel; tentativas continuam ate confirmar a inscricao'
                print('[ROTA] NPC da BG recusou a inscricao; dialogo fechado, aguardando a proxima tentativa.')
            elif pending.get('result')=='other_queue':
                print('[ROTA] NPC informa inscricao na BG '+pending['registered_mode']+'; dialogo encerrado sem cancelar o registro.')
            else:
                print('[ROTA] Inscricao na BG confirmada; dialogo encerrado sem cancelar o registro.')

    def bg_registered(self,attempt):
        """Only an explicit positive registration reply confirms success."""
        return attempt['queued']

    def bg_tick(self,now):
        """Tries the marked BGs' NPCs one after the other until registered. A BG that succeeds
        leaves the list; with "parar tudo" the first success ends every attempt. Only the
        player (Parar) or another task stops it before that."""
        attempt=getattr(self,'bg_attempt',None)
        if not attempt:return
        from .bg_entry import POLL_SECONDS, RESPONSE_TIMEOUT
        if now<attempt.get('next_poll',0):return
        attempt['next_poll']=now+POLL_SECONDS
        q=self.quests;mode=self.bg_mode(attempt)
        if attempt.get('other_queue'):
            reason='NPC informou inscricao existente na BG '+attempt['other_queue']+' ao tentar BG '+mode+'; tentativas encerradas, registro preservado'
            if q.active:self.quest_stop(reason)
            q.reason=reason;self.bg_attempt=None
            print('[ROTA] '+reason)
            return
        if attempt['queued'] or (not q.active and attempt['next_at'] is None and self.bg_registered(attempt)):
            if q.active:self.quest_stop('Inscrito na BG '+mode)
            attempt['registered'].append(mode);attempt['pending'].remove(mode)
            print(f"[ROTA] Inscrito na BG {mode} (tentativa {attempt['tries'][mode]})")
            if attempt['stop_all'] or not attempt['pending']:
                self.bg_attempt=None
                q.reason='Inscrito na BG '+', '.join(attempt['registered'])+' • tentativas encerradas';return
            attempt['index']%=len(attempt['pending'])
            attempt.update(next_at=now+min(1,attempt['config']['retry_seconds']),queued=False,refused=False,answered=False)
            q.reason='Inscrito na BG '+mode+'; continuando: '+', '.join(attempt['pending']);return
        if q.active:return
        if not attempt['answered'] and attempt['next_at'] is None:
            if attempt.get('response_wait_at') is None:attempt['response_wait_at']=now
            if now-attempt['response_wait_at']>=RESPONSE_TIMEOUT:
                self.bg_attempt=None
                q.reason='BG sem resposta do NPC: tentativas paradas para nao duplicar a inscricao; confira no jogo antes de tentar novamente'
                print('[ROTA] '+q.reason)
            else:
                q.reason='BG aguardando resposta do NPC; nenhuma nova inscricao sera enviada'
            return
        if attempt['next_at'] is None:
            why='o NPC recusou' if attempt['refused'] else 'inscricao nao confirmada'
            attempt['index']=(attempt['index']+1)%len(attempt['pending'])
            # Next NPC right away; a full round of refusals waits the configured interval.
            wait=attempt['config']['retry_seconds'] if attempt['index']==0 else min(1,attempt['config']['retry_seconds'])
            attempt['next_at']=now+wait
            q.reason=f"BG {mode}: {why}; proxima tentativa: BG {self.bg_mode(attempt)} em {wait} s"
            print('[ROTA] '+q.reason)
        elif now>=attempt['next_at']:
            if self.upstream is None:return  # reconnecting: try again when the character is back
            if self.commands_blocked or not self.allow_commands:
                self.bg_attempt=None;q.reason='Tentativas da BG paradas: envios bloqueados';return
            self.bg_try(now)

    def flush_daily(self):
        """Missions found done today (skipped or delivered) are remembered for the panel."""
        from . import quest_daily
        from . import quest_progress
        from .quest_board_observer import update_progress
        self.know_quest_character()
        while self.quests.external_updates:
            mission,operation=self.quests.external_updates.pop(0)
            if operation!='delivery':
                try:quest_daily.unmark(mission['board_id'],mission.get('rank') or mission['name'])
                except OSError as exc:print('[ROTA] Nao foi possivel atualizar o estado diario da missao: '+str(exc))
            saved=quest_progress.load()
            character=(self.own_look or {}).get('name')
            if saved and (not saved.get('character') or saved.get('character')==character) and update_progress(saved,mission,operation):
                try:quest_progress.save(saved)
                except OSError as exc:print('[ROTA] Nao foi possivel sincronizar a missao manual: '+str(exc))
        if self.quests.learned_extras:
            from . import quest_extras
            try:
                config=quest_extras.load();config.update(self.quests.learned_extras)
                if 'voltar_frame' in self.quests.learned_extras:config['voltar_name']=(self.own_look or {}).get('name') or ''
                quest_extras.save(config);print('[ROTA] '+self.quests.reason)
            except OSError as exc:print('[ROTA] Nao foi possivel salvar o aprendizado: '+str(exc))
            self.quests.learned_extras=None
        if self.quests.slots_dirty:
            try:quest_daily.save_slots(self.quests.slot_owner);self.quests.slots_dirty=False
            except OSError as exc:print('[ROTA] Nao foi possivel salvar os slots: '+str(exc))
        if self.quests.learned:
            from . import quest_library as lib
            try:
                data=lib.load()
                for identity in self.quests.learned:
                    learned=next((m for m in self.quests.library['missions'] if m['id']==identity),None)
                    saved=next((m for m in data['missions'] if m['id']==identity),None)
                    if learned and saved:
                        for field in ('description','monster_targets','monster_names','monster_ids'):
                            if field in learned and not (field=='monster_ids' and saved.get('monster_ids_manual')):saved[field]=copy.deepcopy(learned[field])
                lib.save(data)
            except (OSError,ValueError) as exc:print('[ROTA] Nao foi possivel salvar os monstros aprendidos: '+str(exc))
            self.quests.learned.clear()
        self.know_quest_character()
        while self.quests.daily_marks:
            board_id,label=self.quests.daily_marks.pop(0)
            try:quest_daily.mark(board_id,label)
            except OSError as exc:print('[ROTA] Nao foi possivel salvar missao concluida: '+str(exc))

    def know_quest_character(self):
        """Missions done today are kept per character: the one logged in now."""
        from . import quest_daily
        name=(getattr(self,'own_look',None) or {}).get('name')
        if name:quest_daily.CHARACTER=name

    def quest_targets_open(self,q):
        """Counted monsters still hunted: all of them, or only the unfinished with "ignorar"."""
        targets=q.route.get('kill_targets',[])
        if not q.route.get('ignore_finished'):return list(targets)
        return [t for t,progress in zip(targets,q.progress()) if not progress['complete']]

    def quest_name_choices(self,q):
        """One sprite, several NRO monsters: on the hunting map only the names the missions ask for
        are attacked (e.g. Shinobi Ladrao, not Abelha Macho with the same sprite). A finished one's
        names are left out with "ignorar": they brought its sprite back as a target (2026-11-05)."""
        from .monster_db import names_for_map,monster_choice_key
        from .npc_labels import plain
        seen=names_for_map(q.route['target_map']);choices={}
        for target in self.quest_targets_open(q):
            for species in target['species']:
                names=seen.get(species,set())
                if any(plain(n)==plain(target['name']) for n in names):
                    for name in names:
                        choices[monster_choice_key(q.route['target_map'],species,name)]=plain(name)==plain(target['name'])
                    # The exact name the server sends: also when this PC saw it spelled another way.
                    choices[monster_choice_key(q.route['target_map'],species,target['name'])]=True
        return choices

    def quest_species(self,q):
        """Monsters to attack in the quest hunt.

        Normal: every counted monster (finished ones too) and whoever attacks. With "ignorar":
        only monsters still missing kills, plus the ones marked to always attack."""
        route=q.route
        if route.get('id')==DATABASE_HUNT and q.phase=='hunt':
            combat=self.active_map_combat()
            if combat:
                species=sorted(combat.ranks)
                # The database still owns route/showmobs settings; this map profile owns combat.
                route['species']=sorted(set(route['species'])|set(species))
                return species
        hunted=set(route.get('always_attack',[]))|set(route['species']);always=set(route.get('always_attack',[]))|self.attacker_species(time.monotonic(),hunted)
        if route.get('ignore_finished') and route['kill_targets']:
            missing=set()
            for target,progress in zip(route['kill_targets'],q.progress()):
                if not progress['complete']:missing|=set(target['species'])
            return sorted(missing|always) if missing else []
        return sorted(set(route['species'])|always)

    def save_progress(self,now,force=False):
        """Persist every changed counter/stage; unchanged packet batches do no disk writes."""
        from . import quest_progress
        q=self.quests
        if any(r.get('id')==DATABASE_HUNT for r in q.routes or []):return  # keeps the queue's resume point
        state=q.progress_state()
        if state:state['character']=(self.own_look or {}).get('name')
        if not force and state==getattr(self,'progress_saved_state',None):return
        try:
            if state:quest_progress.save(state)
            elif q.phase=='done' and not q.validation:quest_progress.clear()
            self.progress_saved_state=copy.deepcopy(state)
            self.progress_saved_at=now
        except OSError as exc:print('[ROTA] Nao foi possivel salvar o progresso: '+str(exc))
        self.note_quest_progress()

    def note_quest_progress(self):
        """Append-only history, retained across midnight and bot restarts."""
        from .quest_progress_log import QuestProgressLog,describe
        if getattr(self,'progress_log',None) is None:self.progress_log=QuestProgressLog(self.progress_log_path())
        q=self.quests
        if q.validation or q.recording:return
        try:self.progress_log.note(describe(q.snapshot(),self.tracker.observer.map_name))
        except OSError:pass

    def progress_log_path(self):
        folder=Path(self.folder)
        return (folder.parent.parent if folder.parent.name=='relay' else folder)/'progresso_quests.log'

    def quest_events(self,events,now):
        """After every packet batch: save what was learned and trace the answers to @voltar."""
        q=self.quests
        if q.active or q.phase=='done':self.save_progress(now)
        if now-getattr(self,'progress_log_pruned',-1e9)>300:
            self.progress_log_pruned=now
            from .quest_progress_log import QuestProgressLog
            try:QuestProgressLog(self.progress_log_path()).prune()
            except OSError:pass
        if q.learned_extras or q.slots_dirty or q.learned or q.daily_marks or q.external_updates:self.flush_daily()
        if now-q.voltar_sent_at<15 and events:
            import json
            from datetime import datetime
            keep=('opcode','kind','skill_id','source_id','target_id','damage_raw','cause_raw','duration_ms','text','state','seconds','map','effect_id')
            try:
                with (self.folder/'respostas_voltar.jsonl').open('a',encoding='utf-8') as log:
                    for e in events:
                        if e['kind'] in ('appearance','move','name','remove','player_move','position','other') and not e.get('text'):continue
                        log.write(json.dumps(dict(at=datetime.now().isoformat(),seconds_after=round(now-q.voltar_sent_at,2),
                                                  event={k:e[k] for k in keep if k in e}),ensure_ascii=False)+'\n')
            except OSError:pass

    async def quest_tick(self,game_gate):
        q=self.quests
        await self.close_bg_result_dialog(game_gate)
        self.bg_tick(time.monotonic())
        if getattr(self,'bg_dialog_close',None):return True
        if await self.hunt_death_watch(time.monotonic(),game_gate):return True
        if not q.active and q.resume and self.tracker.observer.map_name and q.resume_after_move(self.tracker.observer.map_name,time.monotonic()):
            self.quest_base_settings=copy.deepcopy(self.settings);self.commands_blocked=False
        if not q.active:
            if not q.errands:return False
            # Buttons "Equipar montaria" / "Equipar itens de combate" outside the queue.
            if self.commands_blocked or self.upstream is None or not game_gate():
                q.errands=[];q.reason='Envios bloqueados: equipamento nao enviado';return False
            return await self.quest_errand(time.monotonic(),game_gate)
        if self.commands_blocked or not self.allow_commands:
            self.quest_stop('Envios bloqueados (Parar envios)');return False
        if self.native_frames.error:
            self.quest_stop(self.native_frames.error);return False
        now=time.monotonic();observer=self.tracker.observer
        if self.upstream is None or not game_gate() or not observer.player_position_valid(now):
            # A moment without position (own character left the view, repositioned) is not a stop:
            # only 30 s in a row is. Measured from the last valid position, hunting included.
            lost=getattr(q,'position_lost_at',None)
            if lost is None:q.position_lost_at=lost=now
            if not observer.player_alive:
                if await self.revive_after_death(now,game_gate):return True
                self.quest_stop('Personagem morreu; a fila foi pausada');return True
            if now-lost>30:self.quest_stop('Conexao ou posicao indisponivel ha 30 s; reinicie a fila quando conectado')
            return True
        q.position_lost_at=None
        if getattr(self,'revive',None) is not None and observer.player_alive:
            self.resume_after_revive(now);return True
        if self.manual_control(now):
            q.progress_at=now;return True
        if q.phase=='hunt' and not q.errands:
            # Players around only matter while fighting; trips, mount and equipment switches carry on.
            if await self.update_presence_hold():
                q.progress_at=now;return True
        elif self.presence_hold is not None:
            if self.sitting and await self.send_body_action(STAND):self.sitting=False
            self.presence_hold=None
        if q.errands:return await self.quest_errand(now,game_gate)
        if q.phase=='hunt':
            if observer.map_name and PortalGuard.key(q.route['target_map'])!=PortalGuard.key(observer.map_name):
                # Pushed off the hunting map (a portal, a warp): back by the recorded routes.
                q.enter_stage('travel',now);q.reason='Voltando ao mapa de caca: '+q.route['name']
                print('[ROTA] '+q.reason);return True
            species=self.quest_species(q)
            if not species:
                self.hunt.pause('Todos os monstros da quest concluidos');q.finish_hunt(now);self.quest_hunt_id=None;return True
            key=(q.route['id'],tuple(species),tuple(t['name'] for t in self.quest_targets_open(q)))
            if self.quest_hunt_id!=key:
                if isinstance(self.quest_hunt_id,tuple) and self.quest_hunt_id[0]==q.route['id']:
                    print('[ROTA] Monstros atacados agora: '+', '.join(map(str,species)))
                settings=copy.deepcopy(self.settings)
                settings.update(species=species,auto_map_targets=False,monster_name_choices=self.quest_name_choices(q),pvp_enabled=False,patrol=True)
                map_combat=self.active_map_combat() if q.route['id']==DATABASE_HUNT else None
                self.apply_settings(settings,map_overlay=map_combat is not None);self.hunt.start();self.quest_hunt_id=key
                priorities=map_combat.ranks if map_combat else (q.route.get('attack_priority') or {})
                self.hunt.target_priority={int(k):v for k,v in priorities.items()}
            elif not self.hunt.enabled:
                self.quest_stop('Caca interrompida: '+self.hunt.reason);return True
            goal=None
            if q.route['id']==DATABASE_HUNT and now-getattr(self,'goal_checked_at',-1e9)>=.5:
                self.goal_checked_at=now  # the inventory scan twice a second is plenty for a goal
                goal=goal_reached(q.route,q.body.items(),now)
            if goal:print('[ROTA] Meta da caca concluida: '+goal)
            if goal or q.hunt_complete():
                self.hunt.pause('Meta da caca concluida: '+goal if goal else 'Objetivo da quest concluido');q.finish_hunt(now);self.quest_hunt_id=None
                if q.phase=='done':
                    reason=q.reason;self.quest_stop(reason);q.phase='done'
                return True
            return False
        # Only this executor may move while traveling. Combat resumes after destination confirmation.
        if self.hunt.enabled:self.hunt.pause('Percorrendo rota de quest')
        if self.walking_now():return True
        positions=observer.combat_positions(now)
        position=positions[0] if positions else observer.player
        collision=self.collision_map()
        q.route_collision=self.map_repository.get if self.map_repository else None
        action=q.plan(observer.map_name,position,collision,self.portals,now)
        self.flush_daily()
        if q.phase=='paused':
            print('[ROTA] Parada: '+q.reason);self.quest_stop(q.reason);return True
        if q.phase=='done':
            reason=q.reason;self.quest_stop(reason);q.phase='done';return True
        if action is None:return True
        planned=(observer.map_name,q.phase,q.step,q.index)
        async with self.send_lock:
            if (not q.active or planned!=(observer.map_name,q.phase,q.step,q.index)
                or not self.native_frames.ready or self.commands_blocked or not game_gate() or self.upstream is None):return True
            if action['kind']=='move':
                hazards=getattr(self,'toxic_ground',None)
                crosses=getattr(self,'crosses_ground_hazard',None)
                if hazards and crosses and crosses(position,action['position'],time.monotonic()):
                    q.path_cache=None;q.pending=None;q.reason='Nevoa toxica no caminho; recalculando'
                    return True
                payload=move(*action['position'])
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
