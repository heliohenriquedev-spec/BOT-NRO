"""Quest itinerary integration: exclusive travel, guarded sends and normal combat at arrival."""
import copy
import struct
import time
from pathlib import Path
from .quest_routes import QuestRoutes, load, save, STAGE_FIELDS, text
from .packet_encoder import move, STAND
from .portals import PortalGuard
from .quest_library_relay import SharedQuestRelay


class QuestRelay(SharedQuestRelay):
    def init_quests(self):
        self.quests=QuestRoutes();self.quest_base_settings=None;self.quest_hunt_id=None

    def quest_stop(self,reason):
        if self.quests.active:print('[ROTA] Parada: '+reason)
        if self.quests.active or self.quests.phase=='done':self.save_progress(time.monotonic(),force=True)
        if reason!=self.quests.reason:self.quests.resume=None  # paused by the player: stays paused
        self.quests.stop(reason)
        if self.hunt:self.hunt.pause(reason)
        if self.quest_base_settings is not None:
            settings=self.quest_base_settings;self.quest_base_settings=None
            self.apply_settings(settings)
        self.quest_hunt_id=None

    def quest_control(self,command,request,game_gate):
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
            route=next((r for r in map_routes.apply(load()) if r['id']==request.get('route_id')),None)
            if not route or route['needs_recording'] or not route['steps']:raise ValueError('Escolha o mapa de caca da rota antes de testar')
            self.quests.start_validation(route['steps'],route['target_map'],time.monotonic(),mode='travel',label=route['name'],map_routes=map_routes.adopt_inner_portals(map_routes.load(),self.portals))
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
            self.quests.start(map_routes.apply(load(),entries),time.monotonic(),map_routes=entries)
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
        elif command=='quest_stop':self.quest_stop('Fila pausada pelo usuario')
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

    def flush_daily(self):
        """Missions found done today (skipped or delivered) are remembered for the panel."""
        from . import quest_daily
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
        route=q.route;always=set(route.get('always_attack',[]))|self.attacker_species(time.monotonic())
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
        if q.learned_extras or q.slots_dirty or q.learned or q.daily_marks:self.flush_daily()
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
                self.quest_stop('Personagem morreu; a fila foi pausada');return True
            if now-lost>30:self.quest_stop('Conexao ou posicao indisponivel ha 30 s; reinicie a fila quando conectado')
            return True
        q.position_lost_at=None
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
                settings.update(species=species,auto_map_targets=False,monster_name_choices=self.quest_name_choices(q),pvp_enabled=False)
                self.apply_settings(settings);self.hunt.start();self.quest_hunt_id=key
                self.hunt.target_priority={int(k):v for k,v in (q.route.get('attack_priority') or {}).items()}
            elif not self.hunt.enabled:
                self.quest_stop('Caca interrompida: '+self.hunt.reason);return True
            if q.hunt_complete():
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
