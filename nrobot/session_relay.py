"""Relay de sessão local. Encaminha login; não persiste tráfego de autenticação.

Formato inicial clássico 0069/006B/0071. Compatibilidade real deve ser testada
no cliente NRO; não há tentativa de contornar rejeições do cliente/servidor.
"""
from __future__ import annotations

import argparse
from collections import deque
import asyncio
import re
from datetime import datetime
import json
import math
from pathlib import Path
import socket
import struct
import time

from .continuous_observer import ContinuousTracker
from .packet_encoder import attack, skill, move, body_action, SIT, STAND
from .packet_reader import position
from .entity_inventory import EntityInventory
from .quest_relay import QuestRelay


from .gm_signs import staff_name  # noqa: E402  (GM/staff tags in names)


class HuntTargetChanged(ValueError):
    """A stale target/route can be discarded without stopping the whole hunt."""


class HandshakeFrames:
    def __init__(self, stage, account=None):
        self.stage, self.account = stage, account
        self.prefix_checked = stage != 'char' or account is None
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)

    def pop(self):
        if not self.prefix_checked:
            if len(self.buffer) < 4:
                return None
            self.prefix_checked = True
            if self.buffer[:4] == self.account:
                result = bytes(self.buffer[:4])
                del self.buffer[:4]
                return ('account_prefix', result)
        if len(self.buffer) < 2:
            return None
        op = struct.unpack_from('<H', self.buffer)[0]
        variable = {0x69, 0x6b}
        fixed = {0x6a: 23, 0x6c: 3, 0x6e: 3, 0x70: 3, 0x71: 28, 0x81: 3}
        if op in variable:
            if len(self.buffer) < 4:
                return None
            size = struct.unpack_from('<H', self.buffer, 2)[0]
            minimum = 47 if op == 0x69 else 4
            if not minimum <= size <= 32768:
                raise ValueError(f'Comprimento de login inválido: {op:04X}')
        elif op in fixed:
            size = fixed[op]
        else:
            raise ValueError(f'Login usa mensagem ainda não suportada: {op:04X}')
        if len(self.buffer) < size:
            return None
        result = bytes(self.buffer[:size])
        del self.buffer[:size]
        return (op, result)


async def rewrite_endpoints(op, packet, register):
    result = bytearray(packet)
    if op == 0x69:
        if len(packet) < 79 or (len(packet)-47) % 32:
            raise ValueError('Lista de servidores incompatível com a variante clássica')
        offsets, stage = range(47, len(packet), 32), 'char'
    elif op == 0x71:
        offsets, stage = [22], 'map'
    else:
        return packet
    for offset in offsets:
        host = socket.inet_ntoa(packet[offset:offset+4])
        port = struct.unpack_from('<H', packet, offset+4)[0]
        if port == 0:
            raise ValueError('Servidor informou porta inválida')
        local_port = await register(stage, host, port)
        result[offset:offset+4] = socket.inet_aton('127.0.0.1')
        struct.pack_into('<H', result, offset+4, local_port)
    return bytes(result)


class SessionRelay(QuestRelay):
    def __init__(self, remote_host, remote_port=6900, local_port=16900, *, folder,
                 species=None, allow_commands=False):
        self.remote_host, self.remote_port, self.local_port = remote_host, remote_port, local_port
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.listeners = {}
        self.tasks = set()
        self.character_id = None
        self.account = None
        self.upstream = None
        self.send_lock = asyncio.Lock()
        self.init_quests()
        self.allow_commands = allow_commands
        self.tracker = ContinuousTracker(species or {1051}, player_ttl=None, idle_timeout=None, entity_ttl=None)
        self.tracker.observer.collision_provider = self.collision_map
        self.mirror = bytearray()
        self.mirror_ready = False
        self.mirror_sequence = 0
        self.stage = 'starting'
        self.error = None
        self.last_saved = 0
        self.last_inventory_map = None
        self.last_inventory_written = 0
        self.last_status_written = 0
        self.game_peer = self.game_local = None
        self.commands_blocked = False
        self.single_attack_used = False
        self.last_test = None
        self.test_deadline = None
        self.hunt = None
        self.map_repository = None
        from .ammo import AmmoInventory
        self.ammo = AmmoInventory()
        from .presence_guard import PresenceGuard
        self.presence = PresenceGuard()
        self.presence_hold = None
        self.sit_on_players = False
        self.last_combat_packet = None  # 'skill' / 'attack': basic attacks alternate with skills
        self.hunt_key, self.hunt_key_name = 0x24, 'Home'
        self.sitting = False  # REDE-82: the bot sat down while a player is near
        self.capture_armed_until = 0
        self.captured_player = None
        # REDE-72: other characters' server paths.
        self.player_tracks = {}
        self.pvp_registered = set()
        from .group_hunt import GroupHunt
        self.group = GroupHunt()
        self.player_names = {}  # REDE-76: names of characters (0195 replies to the client's 008C)
        self.player_first_seen = {}
        self.own_option = 0  # REDE-73: own hide/cloak/@hide bits, for the in-game shadow
        self.own_look = {}  # class, sex and hairstyle for the shadow's real sprite
        from .portals import PortalGuard
        self.portals = PortalGuard()  # warps are never walked into
        from .player_registry import PlayerRegistry
        self.registry = PlayerRegistry()  # aba Jogadores: everyone ever seen
        self.registry_saved = 0
        # Lista de observação / @hide: stop everything until the user starts again.
        self.watch_entries, self.watch_stamp = [], None
        self.emergency = None  # {'id', 'reason', 'detections', 'at'} of the last stop
        self.emergency_current = set()  # (id, kind) found now; only a new one stops again
        self.char_list = b''
        self.manual_until = 0  # REDE-76: the bot yields while the player walks by hand
        self.manual_active = False
        self.trails = {}  # REDE-76: walked cells per map, for the minimap
        from .monster_db import load_captured
        self.monsters_seen = load_captured()  # REDE-79: what the game showed about each monster
        self.monsters_dirty = False
        self.monsters_written = 0
        self.sprite_state = {}  # species -> 'exists' / 'grf' / 'captured' / None (needs a capture)
        self.minimap_ground_written = None
        self.last_route_written = 0
        self.next_map = None
        self.reported_maps = set()
        mapping_path = Path(__file__).resolve().parents[1]/'data/rede/especies_nro.json'
        mapping = json.loads(mapping_path.read_text(encoding='utf-8'))['species'] if mapping_path.is_file() else {}
        self.inventory = EntityInventory({key: value['name'] for key, value in mapping.items()})
        self.skill_trace_count = 0
        self.control_result = None
        self.settings = None
        self.navigation_stationary = False
        self.rotation = None
        self.buff_probe_request = None
        self.map_validation = None
        self.buff_candidates = {}
        self.buff_learning_result = None
        from .map_search import MapSearch
        self.map_search = MapSearch()
        self.discovered_monsters = {}
        self.recent_map_sends = deque(maxlen=32)
        from .client_frame_guard import ClientFrameGuard
        self.native_frames = ClientFrameGuard()
        from .manual_skill_diagnostic import ManualSkillDiagnostic
        self.manual_skill_diagnostic = ManualSkillDiagnostic()
        self.manual_skill_pending = None
        self.manual_kunai_trace = None

    def inspect_manual_skill(self, data):
        observer = self.tracker.observer
        if not observer.player_position_valid(time.monotonic()) or not observer.skills:
            self.manual_skill_diagnostic.tail = b''
            return
        for event in self.manual_skill_diagnostic.feed(data, observer.skills):
            self.manual_skill_pending = {**event, 'deadline': time.monotonic()+8,
                                         'effects_before': [identity for identity, active in observer.effects.items() if active]}
            self.skill_trace_count = 0
            self.record_hunt({'kind': 'manual_skill_candidate', **event})
            print(f"Habilidade manual registrada: ID {event['skill_id']}, nível {event['level']}, alvo {event['target_id']}.")

    def apply_settings(self, settings):
        from .packet_settings import validate
        from .packet_patrol import PacketPatrol
        from .network_targets import Entity
        settings = validate(settings)
        if self.settings is not None and any(self.settings[k] != settings[k] for k in ('group_enabled','group_role','group_leader')):
            self.group.target_id = None
            self.group.target_at = 0
            if self.hunt is not None:
                self.hunt.priority_target = None
        if self.hunt is None:
            raise ValueError('Modo de caça não está disponível')
        self.hunt.pause('configuração aplicada; iniciar para retomar')
        self.hunt.SEARCH_RADIUS = settings['radius']
        for attribute, key in (('SKILL_INTERVAL', 'skill_interval'), ('SKILL_RESPONSE_TIMEOUT', 'skill_timeout'),
                               ('SKILL_ATTEMPTS', 'skill_attempts'), ('TARGET_DEFER', 'target_defer'),
                               ('SWITCH_DISTANCE', 'switch_distance'), ('SWITCH_SAVING', 'switch_saving')):
            setattr(self.hunt, attribute, settings[key])
        self.hunt.SWITCH_RATIO = settings['switch_ratio_percent']/100
        # REDE-82: failure rules can be switched off.
        if not settings['limit_target_failures']:
            self.hunt.SKILL_ATTEMPTS = 10**9
        if not settings['defer_failed_targets']:
            self.hunt.TARGET_DEFER = 0
        self.hunt.use_skills = settings['skills']
        self.hunt.auto_attacks = settings['auto_attacks']
        self.tracker.observer.free_cast_movement = True
        from .combat_rotation import CombatRotation
        previous_rotation = self.rotation
        if previous_rotation is not None:
            self.saved_summon_queue = previous_rotation.summons
        self.rotation = CombatRotation(settings['skill_profiles'], response_timeout=settings['skill_timeout'],
            attempts=settings['skill_attempts'], defer=settings['target_defer'], interval=settings['skill_interval'], global_delay=settings['skill_global_delay'],
            priority=settings['skill_priority'], fast=settings['fast_offensives'],
            burst=settings['skill_burst'], burst_interval=settings['skill_burst_interval'], ignore_animation=True) if settings['skills'] and settings['advanced_combat'] else None
        if self.rotation is not None:
            if not settings['limit_target_failures']:
                self.rotation.attempts = 10**9
            if not settings['defer_failed_targets']:
                self.rotation.defer = .3
        if self.rotation is not None and previous_rotation is not None:
            # Saving a setting must not forget what was learned about the server's timing.
            self.rotation.ready = dict(previous_rotation.ready)
            self.rotation.learned_min_interval = dict(previous_rotation.learned_min_interval)
            self.rotation.after_skill_delay = previous_rotation.after_skill_delay
            self.rotation.last_throw = previous_rotation.last_throw
            self.rotation.learned_min_interval = dict(previous_rotation.learned_min_interval)
            self.rotation.pending = dict(previous_rotation.pending)
            self.rotation.next_send = previous_rotation.next_send
            self.rotation.confirmed = previous_rotation.confirmed
            self.rotation.buff_confirmed = previous_rotation.buff_confirmed
            self.rotation.summons = previous_rotation.summons
        if self.rotation is not None and getattr(self, 'saved_summon_queue', None) is not None:
            self.rotation.summons = self.saved_summon_queue
        if self.rotation is not None and previous_rotation is None and getattr(self, 'saved_summon_queue', None) is None:
            try:
                cache = json.loads((Path(__file__).resolve().parents[1]/'data/rede/invocacoes_aprendidas.json').read_text(encoding='utf-8'))
                from .summon_queue import validated_learning
                self.rotation.summons.learned = validated_learning(cache)
            except (OSError, ValueError):
                pass
        if self.rotation is not None:
            self.rotation.summons.mode = settings['summon_queue_mode']
            self.hunt.use_skills = False
        self.manual_movement = settings.get('manual_movement', False)
        self.hunt.auto_movement = settings['auto_movement'] and not self.manual_movement and not self.navigation_stationary
        if not self.hunt.auto_movement and self.hunt.pending and self.hunt.pending['kind'] == 'move':
            self.hunt.pending = None
        if settings['patrol'] and settings['auto_movement'] and not self.manual_movement:
            layout = dict(spacing=settings['patrol_spacing'], coverage=settings['patrol_coverage']/100,
                          wall_margin=settings['patrol_wall_margin'] if settings['patrol_avoid_walls'] else 1,
                          avoid_walls=settings['patrol_avoid_walls'])
            if self.hunt.patrol is None:
                self.hunt.patrol = PacketPatrol(settings['patrol_step'], **layout)
            else:
                self.hunt.patrol.configure(**layout)
                self.hunt.patrol.max_step = settings['patrol_step']
            self.hunt.patrol.GOAL_TIMEOUT = settings['patrol_give_up']
        else:
            self.hunt.patrol = None
        observer = self.tracker.observer
        observer.species = set(settings['species'])
        existing = dict(observer.registry.entities)
        observer.registry.clear()
        now = time.monotonic()
        for e in self.inventory.entities.values():
            if (e['species_id'] in observer.species and e['present_last_observation']
                and (observer.registry.ttl is None or now-e['last_seen'] <= observer.registry.ttl)):
                entity = existing.get(e['entity_id']) or Entity(e['entity_id'], e['species_id'], *e['position'], e['last_seen'], 'monster',
                    destination=tuple(e['destination']) if e.get('destination') else None, walk_speed_ms=e.get('walk_speed_ms'))
                observer.registry.update(entity)
        self.settings = settings
        if not settings['pvp_enabled']:
            self.release_player()
            self.capture_armed_until = 0
        self.sync_pvp_targets()
        self.presence.hold_players = settings['pause_on_players']
        self.presence.hold_disguised = settings['pause_on_disguised']
        self.presence.hold_hidden = settings['pause_on_hidden']
        self.presence.resume_delay = settings['resume_delay']
        group_names = [settings['group_leader'], *settings['group_members']] if settings['group_enabled'] else []
        self.presence.allowed_names = {n.casefold() for n in [*settings['allowed_players'], *group_names] if n}
        self.sync_presence_names()
        from .packet_settings import HOTKEYS
        self.hunt_key, self.hunt_key_name = HOTKEYS[settings['hotkey_hunt']], settings['hotkey_hunt']
        self.sit_on_players = settings['sit_on_players']
        self.register_captured()
        self.sync_map_monsters()

    def defer_until_manual_walk_finishes(self):
        motion = self.tracker.observer.player_motion
        if motion is not None:
            self.hunt.ready_at = max(self.hunt.ready_at, motion['at']+motion['duration'])

    OVERLAY_CLICKS = (0xa7, 0x89, 0x90)  # walk, attack/target click, NPC click

    def drop_clicks_under_overlay(self, data):
        """Clicks the game sends while the cursor is over the bot's minimap/counter are dropped."""
        frames = self.native_frames.frames
        if not frames or not any(op in self.OVERLAY_CLICKS for op, _ in frames) or self.native_frames.buffer:
            return data
        flag = self.folder/'cursor_sobre_janela'
        try:
            if time.time()-flag.stat().st_mtime > 120:  # stale flag (panel closed mid-hover)
                return data
        except OSError:
            return data
        if b''.join(frame for _, frame in frames) != bytes(data):
            return data  # not exactly whole frames: forward untouched
        kept = b''.join(frame for op, frame in frames if op not in self.OVERLAY_CLICKS)
        if 0xa7 in (op for op, _ in frames):
            self.manual_active = False  # it was the drag, not the player walking
        return kept

    def inspect_native_frames(self, data):
        """REDE-55: called under send_lock before forwarding native client bytes."""
        completed = self.native_frames.feed(data)
        for opcode in completed:
            self.trace_map_send('client', opcode, self.native_frames.sizes[opcode])
        if 0x89 in completed:
            self.tracker.observer.clock.request_sent(time.monotonic())  # answered by 007F
        for opcode, frame in self.native_frames.frames:
            self.quests.native(opcode,frame,self.tracker.observer.map_name)
            if opcode == 0x8c and len(frame) == 11:
                self.capture_monster_sprite(struct.unpack_from('<I', frame, 7)[0])
        if time.monotonic() < self.capture_armed_until:
            for opcode, frame in self.native_frames.frames:
                target = self.CAPTURE_TARGET_OFFSETS.get((opcode, len(frame)))
                if target is not None:
                    identity = struct.unpack_from('<I', frame, target)[0]
                    if opcode == 0x8c and time.monotonic()-self.player_first_seen.get(identity, 0) < self.AUTO_NAME_WINDOW:
                        continue  # the client asks names of characters entering the view by itself
                    origin = 'mouse no jogo' if opcode == 0x8c else 'clique no jogo'
                    if self.capture_player(identity, origin):
                        break
        if self.hunt is not None and 0xa7 in completed and not getattr(self, 'manual_movement', False):
            # REDE-76: a click on the ground hands control to the player for a moment only.
            if not self.manual_active:
                self.record_hunt({'kind': 'manual_movement_override'})
                print(f'Controle manual: bot aguardando; retoma sozinho {self.MANUAL_YIELD:.0f} s após o último clique.')
            self.manual_active = True
            self.manual_until = time.monotonic()+self.MANUAL_YIELD
            self.hunt.pending = None
            self.hunt.target = None
        return completed

    # REDE-67: native action request (0190, click/attack) and targeted skill (0072);
    # REDE-76: name request (008C) the client sends when the mouse rests on a character.
    CAPTURE_TARGET_OFFSETS = {(0x190, 19): 5, (0x72, 25): 21, (0x8c, 11): 7}
    AUTO_NAME_WINDOW = 1.0
    MANUAL_YIELD = 3.0

    def manual_control(self, now):
        """True while the player is walking by hand; afterwards the hunt resumes by itself."""
        if not self.manual_active:
            return False
        if now < self.manual_until:
            if self.hunt is not None:
                self.hunt.reason = 'controle manual: retoma sozinho em %.0f s' % (self.manual_until-now)
            return True
        self.manual_active = False
        if self.hunt is not None:
            self.hunt.reason = ''
            self.defer_until_manual_walk_finishes()
        self.record_hunt({'kind': 'manual_movement_released'})
        print('Controle manual encerrado; caça retomada.')
        return False

    def capture_player(self, identity, origin):
        from .network_targets import Entity, is_player_id
        observer = self.tracker.observer
        if (not is_player_id(identity) or identity == observer.player_id
                or self.settings and not self.settings.get('pvp_enabled')):
            return False
        self.release_player()
        self.capture_armed_until = 0
        known = self.inventory.entities.get(identity, {})
        self.captured_player = {'entity_id': identity, 'name': self.player_names.get(identity) or known.get('name'),
                                'origin': origin}
        observer.pinned.add(identity)
        self.presence.allowed.add(identity)
        if self.hunt is not None:
            self.hunt.priority_target = identity
        self.register_captured()
        self.record_hunt({'kind': 'player_captured', **self.captured_player})
        print(f"Jogador capturado como alvo: {self.captured_player['name'] or identity} (ID {identity}, por {origin}).")
        return True

    def register_captured(self):
        from .network_targets import Entity
        if self.captured_player is None:
            return
        identity = self.captured_player['entity_id']
        known = self.inventory.entities.get(identity, {})
        position = self.presence.positions.get(identity) or known.get('position')
        if identity in self.presence.players and position is not None:
            self.tracker.observer.registry.update(Entity(identity, known.get('species_id', 0), *position,
                                                         time.monotonic(), 'player', walk_speed_ms=known.get('walk_speed_ms')))

    def release_player(self):
        if self.captured_player is None:
            return
        identity = self.captured_player['entity_id']
        observer = self.tracker.observer
        observer.pinned.discard(identity)
        self.presence.allowed.discard(identity)
        entity = observer.registry.entities.get(identity)
        if entity is not None and entity.kind == 'player':
            observer.registry.remove(identity)
        if self.hunt is not None:
            if self.hunt.priority_target == identity:
                self.hunt.priority_target = None
            if self.hunt.engaged == identity:
                self.hunt.engaged = None
            if self.hunt.target == identity:
                self.hunt.target = self.hunt.pending = None
        self.record_hunt({'kind': 'player_released', 'entity_id': identity})
        self.captured_player = None

    def group_follower(self):
        return bool(self.settings and self.settings['group_enabled'] and self.settings['group_role']=='follower')

    def group_leader_id(self):
        visible = {i:e for i,e in self.player_tracks.items() if i not in self.presence.hidden}
        return self.group.leader(self.settings or {}, self.player_names, visible)

    def group_combat_allowed(self, target_id=None):
        if not self.group_follower():
            return True
        if self.settings['group_follow_only'] or self.group_leader_id() is None:
            return False
        self.group.observe([],self.group_leader_id(),time.monotonic())
        target_id = self.group.target_id if target_id is None else target_id
        target=self.tracker.observer.registry.entities.get(target_id)
        leader=self.player_tracks[self.group_leader_id()].combat_bounds(time.monotonic())[0][0]
        own=self.tracker.observer.player
        return bool(target_id==self.group.target_id and target is not None and target.kind=='monster'
                    and own is not None and math.dist(own,leader)<=12)

    def sync_pvp_targets(self):
        observer = self.tracker.observer
        settings = self.settings or {}
        eligible = set()
        if settings.get('pvp_enabled') and not self.group_follower():
            eligible = set(self.player_tracks) & self.presence.players
            eligible.difference_update(self.presence.hidden)
            eligible.discard(observer.player_id)
            if not settings.get('pvp_all'):
                eligible.intersection_update(settings.get('pvp_targets', ()))
        for identity in self.pvp_registered - eligible:
            if identity not in observer.pinned:
                observer.registry.remove(identity)
                self.presence.allowed.discard(identity)
        for identity in eligible:
            observer.registry.update(self.player_tracks[identity])
        self.presence.allowed.update(eligible)
        self.pvp_registered = eligible

    def player_target_allowed(self, identity):
        observer = self.tracker.observer
        if self.settings is None:
            return identity in observer.pinned
        return (self.settings.get('pvp_enabled') and identity in self.presence.players
                and identity in self.player_tracks and identity not in self.presence.hidden
                and (identity in self.pvp_registered or identity in observer.pinned))

    def prioritize_pvp(self, state):
        candidates = state['recent_entities']
        players = self.pvp_registered
        preferred = [row for row in candidates if
                     (row['entity_id'] in players) == self.settings['pvp_first']
                     and self.hunt.excluded_until.get(row['entity_id'], 0) <= time.monotonic()
                     and math.dist(state['player_position'], row['position']) <= self.hunt.SEARCH_RADIUS]
        return {**state, 'recent_entities': preferred} if preferred else state

    def attacker_species(self, now):
        """Species of the monsters attacking the character, when more than the configured number do."""
        from .network_targets import is_player_id
        from .presence_guard import monster_sprite
        if self.hunt is None:
            return set()
        attackers = {}
        for identity, at in list(self.hunt.aggressors.items()):
            entity = self.inventory.entities.get(identity)
            if (now-at <= 10 and entity and entity['present_last_observation'] and not is_player_id(identity)
                    and monster_sprite(entity['species_id'])):
                attackers[identity] = entity['species_id']
        limit = (self.settings or {}).get('ignore_attackers', 0)
        return set(attackers.values()) if len(attackers) > limit else set()

    def include_attackers(self, now):
        """Monsters attacking (above the ignore limit) become targets, whatever their species, until
        they stop; the configured targets stay as they are."""
        from .network_targets import Entity
        observer = self.tracker.observer
        if not self.settings:
            return
        wanted = set(self.settings['species']) | self.attacker_species(now)
        if wanted == observer.species:
            return
        added = wanted-observer.species
        observer.species = wanted
        for e in self.inventory.entities.values():
            if (e['species_id'] in added and e['present_last_observation']
                    and (observer.registry.ttl is None or now-e['last_seen'] <= observer.registry.ttl)):
                observer.registry.update(Entity(e['entity_id'], e['species_id'], *e['position'], e['last_seen'], 'monster',
                    destination=tuple(e['destination']) if e.get('destination') else None, walk_speed_ms=e.get('walk_speed_ms')))
        if added:
            self.record_hunt({'kind': 'attackers_targeted', 'species': sorted(added)})

    def plan_group_or_hunt(self, state, now, speed, collision):
        self.include_attackers(now)
        if not self.group_follower():
            return self.hunt.plan(state,now,speed,collision=collision)
        leader_id=self.group_leader_id()
        leader=self.player_tracks[leader_id].combat_bounds(now)[0][0] if leader_id is not None else None
        self.group.observe([],leader_id,now)
        target=self.group.target_id
        combat=self.group_combat_allowed(target) and any(e['entity_id']==target for e in state['recent_entities'])
        old_patrol=self.hunt.patrol
        self.hunt.patrol=None  # followers never launch independent exploration
        try:
            filtered={**state,'recent_entities':[e for e in state['recent_entities'] if combat and e['entity_id']==target]}
            self.hunt.priority_target=target if combat else None
            if not combat:
                self.hunt.target=self.hunt.engaged=None
            action=self.hunt.plan(filtered,now,speed,collision=collision)
            if combat:
                self.group.reason=f'alvo observado do lider: {target}'
                return action
            if not self.hunt.auto_movement or self.hunt.pending is not None or now < self.hunt.ready_at:
                return None
            blocked={p for p,t in self.hunt.blocked_until.items() if t>now}
            action=self.group.plan_follow(state,leader,self.settings,collision,blocked,speed)
            self.hunt.reason=self.group.reason
            return action
        finally:
            self.hunt.patrol=old_patrol

    def sync_presence_names(self):
        from .network_targets import is_player_id
        names = {i: e['name'] for i, e in self.inventory.entities.items() if is_player_id(i) and e.get('name')}
        names.update(self.player_names)
        self.presence.remember_names(names)

    def announce_presence(self):
        """Known allowed characters get an informational notice, never a pause alert."""
        self.sync_presence_names()
        player = self.tracker.observer.player
        for alert in self.presence.drain_alerts():
            identity = alert['entity_id']
            name = self.player_names.get(identity) or self.inventory.entities.get(identity, {}).get('name') or 'nome ainda não recebido'
            position = self.presence.positions.get(identity)
            where = f", {round(math.dist(player, position))} células" if player and position else ''
            text = {'player': f'Jogador por perto: {name} (ID {identity}{where})',
                    'disguised': f"Jogador disfarçado de monstro: {name} (ID {identity}, sprite {alert.get('species_id')}{where})",
                    'hidden': f"Jogador {'em @hide' if alert.get('option', 0) & 0x40 else 'escondido'}: {name} (ID {identity}{where})",
                    'ghost': f"Jogador INVISIVEL ao seu lado: {name} (ID {identity}) {alert.get('signal')} sem aparecer na tela"}[alert['kind']]
            allowed = self.presence.ignored(identity)
            self.record_hunt({'kind': 'presence_alert', **alert, 'name': name, 'allowed': allowed})
            print(('[PERMITIDO] ' if allowed else '[ALERTA] ')+text+(' (whitelist; nao pausa)' if allowed else ''))

    def own_motion(self):
        observer = self.tracker.observer
        motion = observer.player_motion
        if motion is None:
            return {'position': observer.player} if observer.player is not None else None
        return {'position': motion['origin'], 'destination': motion['destination'], 'at': motion['at'],
                'path': [list(cell) for cell in motion['path']] if motion.get('path') else None,
                'speed_ms': observer.walk_speed_ms}

    # -- monsters seen in the game (REDE-79) ----------------------------------------------
    def learn_monsters(self, events):
        from .monster_db import record
        from .map_monsters import is_confirmed_monster

        observer = self.tracker.observer
        map_name = self.inventory.map_name or observer.map_name
        if not map_name:
            return
        last_transition = max((i for i, event in enumerate(events)
                               if event['kind'] in ('map_change', 'map_transfer')), default=-1)
        for event in events[last_transition+1:]:
            if event['kind'] != 'name' or not event.get('max_hp'):
                continue
            entity = self.inventory.entities.get(event.get('entity_id'))
            if not entity or not entity.get('present_last_observation') or not is_confirmed_monster(entity, observer.player_id):
                continue
            self.monsters_dirty |= record(self.monsters_seen, entity['species_id'], map_name,
                                          name=entity['name'], max_hp=entity['max_hp'],
                                          walk_speed_ms=entity.get('walk_speed_ms'))

    def write_monsters(self):
        if not self.monsters_dirty or time.monotonic()-self.monsters_written < 5:
            return
        from .monster_db import save_captured
        try:
            save_captured(self.monsters_seen)
        except OSError:
            return
        self.monsters_dirty = False
        self.monsters_written = time.monotonic()

    def capture_monster_sprite(self, identity):
        """The mouse rests on a monster (client name request): save its sprite if it has none."""
        from .monster_db import ensure_sprite, sprite_path
        from .presence_guard import monster_sprite
        species = (self.inventory.entities.get(identity) or {}).get('species_id')
        if species is None or not monster_sprite(species) or self.sprite_state.get(species):
            return
        grfs = self.map_repository.grfs if self.map_repository is not None else None
        name = (self.monsters_seen.get(species) or {}).get('name')
        state = ensure_sprite(grfs, species, observed_name=name) if name else ensure_sprite(grfs, species)
        if state is None:
            from .screen_capture import capture_under_cursor
            path = sprite_path(species)
            path.parent.mkdir(parents=True, exist_ok=True)
            if capture_under_cursor(path):
                state = 'captured'
                entry = self.monsters_seen.setdefault(species, {'species_id': species, 'maps': {}, 'first_seen': None})
                entry['captured_sprite'] = True
                self.monsters_dirty = True
                print(f'Sprite do monstro {species} capturado do jogo (não existe nos arquivos do cliente).')
        self.sprite_state[species] = state

    def record_trail(self):
        name, player = self.tracker.observer.map_name, self.tracker.observer.player
        if not name or player is None:
            return
        trail = self.trails.setdefault(name, [])
        if not trail or max(abs(trail[-1][i]-player[i]) for i in (0, 1)) >= 2:
            trail.append([int(player[0]), int(player[1])])
            del trail[:-20000]

    def write_minimap(self):
        """REDE-76: ground once per map and the walked/planned route, read by the minimap."""
        import base64
        import zlib
        self.record_trail()
        name = self.tracker.observer.map_name
        collision = self.collision_map() if name else None
        if collision is not None and self.minimap_ground_written != name:
            ground = {'map': name, 'width': collision.width, 'height': collision.height,
                      'cells': base64.b64encode(zlib.compress(collision.cells)).decode('ascii')}
            temp = self.folder/'minimapa_chao.tmp'
            temp.write_text(json.dumps(ground), encoding='utf-8')
            temp.replace(self.folder/'minimapa_chao.json')
            self.minimap_ground_written = name
        if time.monotonic()-self.last_route_written < 1:
            return
        patrol = self.hunt.patrol if self.hunt is not None else None
        route = None
        if patrol is not None and patrol.route_cache and patrol.goal is not None:
            route = [list(cell) for cell in patrol.route_cache]
        data = {'map': name, 'trail': self.trails.get(name, []),
                'coverage': patrol.coverage() if patrol is not None and patrol.tour is not None
                and patrol.tour.collision is collision else None,
                'goal': list(patrol.goal) if patrol is not None and patrol.goal is not None else None,
                'route': route}
        temp = self.folder/'minimapa_rota.tmp'
        temp.write_text(json.dumps(data), encoding='utf-8')
        temp.replace(self.folder/'minimapa_rota.json')
        self.last_route_written = time.monotonic()

    def track_players(self, events):
        """Server walk paths of other characters, for drawing their real cells in the game."""
        from .network_targets import Entity, is_player_id
        observer = self.tracker.observer
        now = time.monotonic()
        for event in events:
            kind, identity = event['kind'], event.get('entity_id')
            if kind in ('map_change', 'map_transfer'):
                self.release_player()
                self.player_tracks.clear()
                self.player_first_seen.clear()
                continue
            if identity is None or identity == observer.player_id or not is_player_id(identity):
                continue
            if kind == 'name' and event.get('name'):
                self.player_names[identity] = event['name']
                if self.captured_player and self.captured_player['entity_id'] == identity:
                    self.captured_player['name'] = event['name']
                continue
            if kind == 'appearance' and identity not in self.player_tracks:
                self.player_first_seen[identity] = now
            old = self.player_tracks.get(identity)
            if kind == 'remove':
                self.player_tracks.pop(identity, None)
                self.player_first_seen.pop(identity, None)
                continue
            if kind != 'appearance' and old is None:
                continue
            if kind not in ('appearance', 'move', 'position'):
                continue
            speed = event.get('walk_speed_ms') or (old.walk_speed_ms if old else None) or 150
            x, y = event['position']
            destination = tuple(event['destination']) if event.get('destination') else None
            path = started = None
            if destination is not None and destination != (x, y):
                path = observer.walk_path((x, y), destination)
                started = observer.clock.to_local(event['server_tick'], now) if 'server_tick' in event else now
            species = event.get('species_id', old.species_id if old else 0)
            self.player_tracks[identity] = Entity(identity, species, x, y, now, 'player', destination=destination,
                                                  walk_speed_ms=speed, path=path, walk_started=started)

    def players_nearby(self):
        player = self.tracker.observer.player
        rows = []
        for identity in sorted(self.presence.players & self.player_tracks.keys()):
            position = self.presence.positions.get(identity)
            known = self.inventory.entities.get(identity, {})
            track = self.player_tracks.get(identity)
            if track is not None:
                position = track.position_bounds(time.monotonic())[0][0]
            rows.append({'entity_id': identity, 'name': self.player_names.get(identity) or known.get('name'), 'position': position,
                         'path': [list(cell) for cell in track.path] if track and track.path else None,
                         'walk_started': track.walk_started if track else None,
                         'speed_ms': track.walk_speed_ms if track else None,
                         'distance': round(math.dist(player, position), 1) if player and position else None,
                         'captured': bool(self.captured_player and self.captured_player['entity_id'] == identity)})
        return rows

    def sync_map_monsters(self):
        from .map_monsters import confirmed_types
        from .network_targets import Entity
        observer = self.tracker.observer
        self.discovered_monsters = confirmed_types(self.inventory, observer.player_id)
        selected = set((self.settings or {}).get('species', observer.species))
        if self.settings and self.settings['auto_map_targets']:
            selected.update(self.discovered_monsters)
        from .monster_db import map_key
        current_map = map_key(observer.map_name)
        for key, enabled in (self.settings or {}).get('monster_name_choices', {}).items():
            map_id, _, rest = key.partition(':')
            species, _, name = rest.partition(':')
            if enabled and map_id == current_map and species.isascii() and species.isdecimal() and name:
                selected.add(int(species))
        if selected != observer.species:
            observer.species = selected
            for identity, actor in list(observer.registry.entities.items()):
                if actor.species_id not in selected:
                    observer.registry.remove(identity)
            for entity in self.inventory.entities.values():
                if (entity['species_id'] in selected and entity['present_last_observation']
                    and entity.get('hp', 1) > 0 and entity['entity_id'] != observer.player_id
                    and entity['entity_id'] not in observer.registry.entities):
                    observer.registry.update(Entity(entity['entity_id'], entity['species_id'], *entity['position'],
                        entity['last_seen'], 'monster', destination=tuple(entity['destination']) if entity.get('destination') else None,
                        walk_speed_ms=entity.get('walk_speed_ms')))

    def monster_name_allowed(self, identity, species):
        from .monster_db import monster_choice_key

        settings = self.settings or {}
        choices = settings.get('monster_name_choices', {})
        if not choices:
            return True
        prefix = monster_choice_key(self.tracker.observer.map_name, species, '')
        if not any(key.startswith(prefix) for key in choices):
            return True
        entity = self.inventory.entities.get(identity)
        from .map_monsters import is_confirmed_monster
        if not entity or not is_confirmed_monster(entity, self.tracker.observer.player_id):
            return False
        name = entity['name']
        if prefix+name in choices:
            return choices[prefix+name]
        return settings.get('auto_map_targets', False) or species in settings.get('species', ())

    def trace_map_send(self, source, opcode, size):
        self.recent_map_sends.append({'time': datetime.now().isoformat(), 'source': source,
                                     'opcode': f'{opcode:04X}', 'size': size})

    def validate_navigation_start(self):
        if self.native_frames.error:
            raise ValueError(self.native_frames.error+'; reconecte para sincronizar novamente')
        self.navigation_stationary = False
        if not self.settings:
            return
        self.hunt.auto_movement = self.settings['auto_movement']
        if not self.hunt.auto_movement or not self.settings['require_collision']:
            return
        collision = self.collision_map()
        position = self.tracker.observer.player
        name = self.tracker.observer.map_name
        if collision is None:
            self.navigation_stationary = True
            self.hunt.auto_movement = False
            self.map_validation = None
            print(f'Mapa de colisão indisponível para {name or "o mapa atual"}; caça em modo estacionário.')
            return
        if position is None:
            raise ValueError('Aguardando posição própria confirmada para iniciar a navegação')
        reachable = collision.reachable(position)
        if not reachable:
            source = self.map_repository.sources.get((name or '').lower()) if self.map_repository else None
            raise ValueError(f'Posição própria não corresponde a uma célula livre do mapa; posição {position}, mapa '
                             f'{name or "atual"}; confira o recurso GAT ({source or "origem indisponível"})')
        self.map_validation = {'map': self.tracker.observer.map_name, 'width': collision.width,
                               'height': collision.height, 'reachable_cells': len(reachable), 'origin': list(position)}
        self.record_hunt({'kind': 'map_validated', **self.map_validation})
        print(f"Mapa validado: {collision.width}x{collision.height}, {len(reachable)} células alcançáveis a partir de {position}.")

    def process_control(self, game_gate):
        path = self.folder/'comando.json'
        if not path.is_file():
            return
        identity = None
        try:
            request = json.loads(path.read_text(encoding='utf-8'))
            identity = request['id']
            if self.control_result and identity == self.control_result['id']:
                return
            command = request['command']
            if command.startswith('quest_'):
                self.quest_control(command,request,game_gate)
            elif command == 'apply':
                self.apply_settings(request['settings'])
            elif command == 'pause':
                if self.quests.active:self.quest_stop('Fila pausada pelo painel')
                self.hunt.pause('pausada pelo painel')
            elif command == 'stop':
                if self.quests.active:self.quest_stop('Envios parados pelo painel')
                self.commands_blocked = True
                self.hunt.pause('parada pelo painel')
            elif command == 'start':
                if self.quests.recording:raise ValueError('Salve ou descarte a gravacao antes de iniciar a caca')
                if self.quests.active:self.quest_stop('Controle transferido para caca manual')
                if not game_gate() or self.upstream is None:
                    raise ValueError('Entre no personagem pelo perfil local antes de iniciar; libere os envios')
                self.validate_navigation_start()
                self.commands_blocked = False
                self.hunt.start()
                self.defer_until_manual_walk_finishes()
                if self.emergency is not None:
                    self.emergency['released'] = True
            elif command == 'capture_player':
                if self.settings and not self.settings.get('pvp_enabled'):
                    raise ValueError('Ative PvP para selecionar um jogador')
                self.capture_armed_until = time.monotonic()+20
            elif command == 'set_player_target':
                if not self.capture_player(int(request['entity_id']), 'painel'):
                    raise ValueError('Selecione um jogador visível (não o próprio personagem)')
            elif command == 'release_player':
                self.capture_armed_until = 0
                self.release_player()
            elif command == 'summon_finished':
                if self.rotation is None or self.rotation.summons.active is None:
                    raise ValueError('Nenhuma invocacao acompanhada para confirmar termino')
                active = self.rotation.summons.active
                if active['effect_id'] and self.tracker.observer.effects.get(active['effect_id']):
                    raise ValueError('O servidor ainda informa o efeito ativo; aguarde o termino real')
                self.rotation.summons.finish(time.monotonic(), 'user_observed_end')
                self.flush_rotation_diagnostics()
            elif command == 'probe_buff':
                if self.hunt.enabled:
                    raise ValueError('Pause a caça antes de testar um buff')
                if self.buff_probe_request is not None:
                    raise ValueError('Já existe um teste de buff aguardando envio')
                self.buff_probe_request = {'id': identity, 'skill_id': request['skill_id'], 'level': request['level']}
            else:
                raise ValueError('Comando de painel desconhecido')
            self.control_result = {'id': identity, 'ok': True, 'message': 'Comando aplicado: '+command}
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self.control_result = {'id': identity, 'ok': False, 'message': str(exc)}
        finally:
            path.unlink(missing_ok=True)
        self.status()

    def schedule_character_choice(self, char_list, upstream):
        """Login automatico: the character named in the panel is picked from the server's list."""
        from . import auto_login
        config = auto_login.load()
        if not config['enabled'] or not config['character']:
            return
        slot = auto_login.character_slot(char_list, config['character'])
        if slot is None:
            print(f"Login automatico: personagem {config['character']} nao esta na lista; escolha-o no jogo.")
            return

        async def choose():
            await asyncio.sleep(1.5)  # the character screen is drawn first
            upstream.write(auto_login.select_packet(slot))
            await upstream.drain()
            print(f"Login automatico: personagem {config['character']} (slot {slot}) escolhido.")
        asyncio.get_running_loop().create_task(choose())

    def collision_map(self):
        if self.map_repository is None:
            return None
        name = self.tracker.observer.map_name
        collision = self.map_repository.get(name)
        if collision is not None:
            collision.set_forbidden(self.portals.cells(name))
            collision.links = tuple(self.portals.links(name))
        if name not in self.reported_maps:
            self.reported_maps.add(name)
            result = {'kind': 'map_collision', 'map': name, 'available': collision is not None,
                      'source': self.map_repository.sources.get((name or '').lower()),
                      'error': self.map_repository.errors.get((name or '').lower())}
            self.record_hunt(result)
            fallback = 'indisponível; movimentos serão bloqueados' if self.settings and self.settings['require_collision'] else 'indisponível; aproximação anterior mantida'
            print(f"Colisão do mapa {name}: " + ('carregada' if collision else fallback))
            if result['error']:
                print(f"Motivo da colisão indisponível: {result['error']}")
        return collision

    def record_hunt(self, event):
        with (self.folder/'caca_eventos.jsonl').open('a', encoding='utf-8') as log:
            log.write(json.dumps({'time': datetime.now().isoformat(), **event}, ensure_ascii=False)+'\n')

    def flush_hunt_diagnostics(self):
        if self.hunt is not None:
            for event in self.hunt.drain_diagnostics():
                self.record_hunt(event)
                if event['kind'] == 'skill_confirmed':
                    print(f"Kunai CONFIRMADA: alvo {event['target_id']}, dano {event.get('damage_raw')}.")
                elif event['kind'] == 'skill_retry':
                    print(f"Kunai no alvo {event['target_id']}: {event['reason']} ({event['failures']}/{self.hunt.SKILL_ATTEMPTS}); reavaliando alcance e SP.")
                elif event['kind'] == 'target_switched':
                    print(f"Prioridade ao alvo mais próximo {event['target_id']}; alvo {event['previous_target']} fica disponível para depois.")

    def flush_rotation_diagnostics(self):
        if self.rotation is None:
            return
        summons = self.rotation.summons
        self.rotation.log.extend(summons.log)
        summons.log.clear()
        if summons.dirty:
            try:
                path = Path(__file__).resolve().parents[1]/'data/rede/invocacoes_aprendidas.json'
                temporary = path.with_suffix('.tmp')
                temporary.write_text(json.dumps(summons.learned, ensure_ascii=False, indent=2), encoding='utf-8')
                temporary.replace(path)
                summons.dirty = False
            except OSError:
                pass
        for event in self.rotation.log:
            self.record_hunt(event)
            if event['kind'] == 'rotation_skill_confirmed':
                print(f"Habilidade {event['skill_id']} CONFIRMADA: alvo {event['target_id']}, dano {event['damage_raw']}.")
            elif event['kind'] == 'rotation_buff_confirmed':
                print(f"Buff {event['skill_id']} confirmado pelo efeito {event['effect_id']}.")
            elif event['kind'] == 'rotation_cooldown_notice':
                print(f"Recarga recusada para habilidade {event['skill_id']}; aguardando {event['retry_seconds']} s antes da proxima tentativa.")
            elif event['kind'] in ('summon_started', 'summon_ended', 'summon_effect_linked'):
                print(f"Invocacao {event['skill_id']}: {event['kind']} ({event.get('evidence', 'efeito vinculado')}).")
            elif event['kind'] == 'rotation_failed':
                print(f"Habilidade {event['skill_id']}: {event['reason']} (falhas: {event['failures']}).")
        self.rotation.log.clear()

    def finish_buff_learning(self, now):
        """REDE-47: collect across TCP reads before accepting a unique own effect."""
        manual = self.manual_skill_pending
        if not manual or manual.get('origin') != 'probe':
            return
        ack_at = manual.get('ack_at')
        if ack_at is None or now < ack_at+.5:
            return
        effects = manual.get('observed_effects', set())
        if len(effects) != 1:
            if now >= manual['deadline'] or len(effects) > 1:
                self.manual_skill_pending = None
                self.record_hunt({'kind': 'buff_learning_failed', 'skill_id': manual['skill_id']})
                print('Buff nao identificado: resposta ausente ou efeitos ambiguos; nenhum vinculo salvo.')
            return
        effect = next(iter(effects))
        if not self.tracker.observer.effects.get(effect):
            self.manual_skill_pending = None
            return
        if self.settings is None:
            return
        from .packet_settings import save
        settings = dict(self.settings)
        profiles = [dict(p) for p in settings['skill_profiles']]
        profile = next((p for p in profiles if p['skill_id'] == manual['skill_id']), None)
        if profile is None:
            profile = {'skill_id': manual['skill_id'], 'interval': .5}
            profiles.append(profile)
        profile.update(enabled=True, role='buff', level=manual['level'], effect_id=effect)
        settings['skill_profiles'] = profiles
        try:
            save(settings)
            self.apply_settings(settings)
        except (OSError, ValueError) as exc:
            self.manual_skill_pending = None
            print(f'Nao foi possivel salvar o buff: {exc}')
            return
        self.buff_candidates[manual['skill_id']] = effect
        self.buff_learning_result = {'id': str(time.monotonic_ns()), 'profile': dict(profile)}
        self.manual_skill_pending = None
        self.record_hunt({'kind': 'buff_learned_saved', 'skill_id': manual['skill_id'], 'effect_id': effect})
        print(f"Buff {manual['skill_id']} aprendido, habilitado e salvo; renovacao acompanha o efeito {effect}.")

    async def send_buff_probe(self, request, *, game_gate):
        async with self.send_lock:
            observer = self.tracker.observer
            identity, level = request['skill_id'], request['level']
            if type(identity) is not int or type(level) is not int:
                raise ValueError('ID e nível do teste devem ser inteiros')
            metadata = observer.skills.get(identity)
            if (not self.allow_commands or self.commands_blocked or self.hunt.enabled or not game_gate()
                or self.upstream is None or not self.native_frames.ready or not observer.player_position_valid(time.monotonic())):
                raise ValueError('Teste exige personagem conectado, caça pausada e envios liberados')
            if (type(identity) is not int or type(level) is not int or metadata is None
                or not 1 <= level <= metadata['level'] or metadata.get('target_flags') not in (4, 16)):
                raise ValueError('Nível ou habilidade de uso em si/suporte não confirmado')
            now = time.monotonic()
            if now < max(observer.cast_until, observer.skill_cooldowns.get(identity, 0)):
                raise ValueError('Aguarde a conjuração/intervalo indicado pelo servidor')
            if self.manual_skill_pending and self.manual_skill_pending['deadline'] > now:
                raise ValueError('Aguarde terminar a observação da habilidade anterior')
            if observer.player_id is None or observer.sp is None or observer.sp < metadata['sp_cost']:
                raise ValueError('Identidade ou SP insuficiente/não confirmado')
            self.manual_skill_pending = {'skill_id': identity, 'level': level, 'target_id': observer.player_id,
                'deadline': now+8, 'origin': 'probe', 'effects_before': [effect for effect, active in observer.effects.items() if active]}
            self.skill_trace_count = 0
            payload = skill(observer.player_id, identity, level)
            self.trace_map_send('bot', 0x72, len(payload))
            self.upstream.write(payload)
            await self.upstream.drain()
            self.record_hunt({'kind': 'buff_probe_sent', 'skill_id': identity, 'level': level, 'target_id': observer.player_id})
            print(f'Teste único do buff {identity} enviado para o próprio personagem; aguardando efeito.')
    async def send_rotation_action(self, action, *, game_gate):
        async with self.send_lock:
            if (not self.allow_commands or self.commands_blocked or self.hunt is None or not self.hunt.enabled
                or self.rotation is None or not game_gate() or self.upstream is None):
                raise ValueError('Rotação bloqueada, sessão ou personagem indisponível')
            if not self.native_frames.ready:
                return False
            if (self.hunt.pending is not None and self.hunt.pending['kind'] == 'move'
                and not self.hunt.pending.get('movement_acknowledged')):
                return False
            now = time.monotonic()
            state = self.status()
            if self.rotation.plan(state, now, self.hunt.target) != action:
                return False
            observer = self.tracker.observer
            if not observer.player_alive or observer.player_id is None:
                return False
            collision = self.collision_map()
            if self.settings and self.hunt.auto_movement and self.settings['require_collision'] and collision is None:
                raise ValueError('Mapa de colisão deixou de estar disponível')
            if self.group_follower() and (not self.group_combat_allowed() or action['role'] in ('offensive','summon') and not self.group_combat_allowed(action.get('combat_target_id',action['target_id']))):
                return False
            if action['role'] in ('offensive', 'summon'):
                entity = observer.registry.entities.get(action.get('combat_target_id', action['target_id']))
                if (entity is None or not entity.alive or not observer.registry.current(entity, now)
                    or (entity.kind == 'player' and not self.player_target_allowed(entity.entity_id))
                    or (entity.kind == 'monster' and (entity.species_id not in observer.species
                    or not self.monster_name_allowed(entity.entity_id, entity.species_id)))):
                    return False
                if action['role'] == 'summon' and (entity.kind != 'monster' or max(math.dist(own, p) for own in observer.combat_positions(now) for p in entity.combat_bounds(now)[0]) > 12):
                    return False
                if collision is not None and action['role'] == 'offensive':
                    bounds, _ = entity.combat_bounds(now)
                    if (entity.destination is not None and not entity.position_bounds(now)[1]
                        and not collision.line_clear([entity.x, entity.y], entity.destination)):
                        self.rotation.reason = 'movimento estimado contorna obstaculo; aguardando posicao segura'
                        return False
                    if not all(collision.line_clear(own, point) for own in observer.combat_positions(now) for point in bounds):
                        self.rotation.reason = 'linha de ataque bloqueada; aproximando por rota livre'
                        return False
            elif action['target_id'] != observer.player_id:
                raise ValueError('Buff só pode ser enviado para o próprio personagem')
            if action['kind'] == 'equip':
                from .packet_encoder import equip_ammo
                payload = equip_ammo(action['inventory_index'])
                self.ammo.sent(action['inventory_index'], now)
                self.record_hunt({'kind':'ammo_equip_sent','skill_id':action['skill_id'],'index':action['inventory_index']})
            else:
                if action.get('cast_mode') == 'ground':
                    from .packet_encoder import ground_skill
                    if collision is None:
                        self.rotation.reason = 'invocacao aguardando mapa de colisao'
                        return False
                    origin = action['ground_origin']
                    candidates = [(origin[0]+dx, origin[1]+dy) for dx, dy in ((1,0),(0,1),(-1,0),(0,-1),(0,0))]
                    point = next((p for p in candidates if collision.walkable(p)
                                  and all(math.dist(own, p) <= action['cast_range'] for own in observer.combat_positions(now))
                                  and collision.line_clear(origin, p)), None)
                    if point is None:
                        self.rotation.reason = 'nenhuma celula valida para invocacao proxima'
                        return False
                    payload = ground_skill(*point, action['skill_id'], action['level'])
                    action = {**action, 'ground_position': list(point)}
                else:
                    payload = skill(action['target_id'], action['skill_id'], action['level'])
                self.rotation.sent(action, now)
            try:
                self.trace_map_send('bot', struct.unpack_from('<H', payload)[0], len(payload))
                self.upstream.write(payload)
                await self.upstream.drain()
            except OSError:
                self.hunt.pause('envio de rotação falhou ou ficou incerto')
                raise
            self.flush_rotation_diagnostics()
            return True

    def record_test(self):
        if self.last_test is not None:
            (self.folder/'teste_ataque.json').write_text(json.dumps(self.last_test, ensure_ascii=False, indent=2), encoding='utf-8')

    def status(self):
        if time.monotonic()-self.registry_saved > 3:
            self.registry_saved = time.monotonic()
            try:
                self.portals.save()
                self.registry.save()
            except OSError as error:
                print(f'Registro de jogadores nao salvo: {error}')
        if self.last_test is not None and self.last_test['status'] == 'sent_waiting_response' and time.monotonic() >= self.test_deadline:
            self.last_test['status'] = 'no_confirmation'
            self.record_test()
            print('O ataque de teste foi enviado, mas não houve confirmação de dano no prazo. Não repetirei automaticamente.')
        state = self.tracker.snapshot(time.monotonic())
        if (self.settings or {}).get('monster_name_choices'):
            state['recent_entities'] = [entity for entity in state['recent_entities']
                                        if entity.get('kind') == 'player' or self.monster_name_allowed(
                                            entity['entity_id'], entity.get('species_id'))]
        from .map_monsters import confirmed_types
        observer = self.tracker.observer
        state['character_sync'] = {'identity_received': observer.player_id is not None,
            'skills_received': observer.skills_received, 'sp_received': observer.sp is not None,
            'learned_count': sum(s.get('level',0) > 0 for s in observer.skills.values())}
        state['group'] = {'enabled':bool(self.settings and self.settings['group_enabled']),
            'leader_id':self.group_leader_id() if self.group_follower() else None, 'target_id':self.group.target_id,
            'reason':self.group.reason, 'follow_only':bool(self.settings and self.settings['group_follow_only'])}
        state.update(stage=self.stage, relay_error=self.error, ammo=self.ammo.snapshot(time.monotonic()),
                     quests=self.quests.snapshot(),
                     presence=self.presence.snapshot(self.tracker.observer.player, time.monotonic()),
                     players_nearby=self.players_nearby(), captured_player=self.captured_player,
                     capture_armed=time.monotonic() < self.capture_armed_until,
                     own_motion=self.own_motion(), clock_now=time.monotonic(),
                     own_look=self.own_look or None,
                     emergency_stop=self.emergency,
                     portals=[{'position': list(cell), 'margin': margin} for cell, margin in self.portals.portals(self.tracker.observer.map_name)],
                     own_hidden=({'option': self.own_option & 0x4046, 'gm_invisible': bool(self.own_option & 0x40)}
                                 if self.own_option & 0x4046 else None),
                     native_frame_error=self.native_frames.error,
                     map_monsters=list(self.discovered_monsters.values()),
                     map_monster_names=list(confirmed_types(self.inventory, observer.player_id, by_name=True).values()),
                     buff_candidates=dict(self.buff_candidates), buff_learning_result=self.buff_learning_result,
                     map_validation=self.map_validation,
                     control_result=self.control_result, settings=self.settings,
                     map_name=self.tracker.observer.map_name,
                     command_sending_enabled=self.allow_commands and not self.commands_blocked and not self.single_attack_used,
                     last_attack_test=self.last_test,
                     upstream_connected=self.upstream is not None,
                     updated_at=datetime.now().isoformat())
        if self.hunt is not None:
            goal = self.map_search.plan(self.inventory, state.get('player_position'), self.tracker.observer.species,
                                        time.monotonic(), self.collision_map()) if self.hunt.patrol is not None else None
            state['search_goal'] = goal
            state['map_search'] = self.map_search.summary
            state['hunt'] = self.hunt.snapshot()
            if self.rotation is not None:
                state['rotation'] = self.rotation.snapshot()
                state['hunt']['skills_enabled'] = True
                state['hunt']['skill_reason'] = self.rotation.reason
                state['hunt']['confirmed_skills'] += self.rotation.confirmed
                state['hunt']['confirmed_attacks'] += self.rotation.confirmed
            entity = self.tracker.observer.registry.entities.get(self.hunt.target)
            player = self.tracker.observer.player
            state['combat_target'] = None
            if entity is not None and player is not None:
                bounds, estimated = entity.combat_bounds(time.monotonic())
                state['combat_target'] = {'entity_id': entity.entity_id,
                    'name': self.inventory.names.get(str(entity.species_id), str(entity.species_id)),
                    'position': bounds[0], 'distance': round(math.dist(self.tracker.observer.combat_positions(time.monotonic())[0], bounds[0]), 2),
                    'last_received_position': [entity.x, entity.y],
                    'announced_destination': list(entity.destination) if entity.destination is not None else None,
                    'position_estimated': entity.destination is not None,
                    'motion_uncertain': entity.motion_uncertain,
                    'arrival_estimated': estimated}
            state['command_sending_enabled'] = self.allow_commands and not self.commands_blocked and self.hunt.enabled
        # The control loop reads state frequently; disk persistence is telemetry only.
        if time.monotonic()-self.last_status_written >= .1 or self.stage == 'stopped':
            try:
                temp = self.folder/'estado.tmp'
                temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
                temp.replace(self.folder/'estado.json')
                # The overlay needs fast status updates; the complete historical
                # inventory does not need to serialize and rewrite ten times/sec.
                if time.monotonic()-self.last_inventory_written >= 1 or self.stage == 'stopped' or self.inventory.map_name != self.last_inventory_map:
                    inventory_file = self.folder/'entidades_mapa.tmp'
                    inventory_file.write_text(json.dumps(self.inventory.snapshot(time.monotonic()), ensure_ascii=False, indent=2), encoding='utf-8')
                    inventory_file.replace(self.folder/'entidades_mapa.json')
                    self.last_inventory_written = time.monotonic()
                    self.last_inventory_map = self.inventory.map_name
                self.write_minimap()
                self.write_monsters()

            except PermissionError:
                # Windows readers can temporarily deny replacement. Telemetry
                # is retried on the next heartbeat; never stop the game loop.
                pass
            self.last_status_written = time.monotonic()
        return state

    async def register(self, stage, host, port):
        # Advertised endpoints must belong to the same server in this first version.
        if host not in (self.remote_host, '127.0.0.1', '0.0.0.0'):
            raise ValueError(f'Servidor anunciou outro endereço ({host}); validar antes de encaminhar')
        host = self.remote_host
        key = (stage, host, port)
        if key not in self.listeners:
            def accepted(reader, writer):
                task = asyncio.create_task(self.bridge(stage, host, port, reader, writer))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
            port_wanted = self.local_port if stage == 'login' else 0
            try:
                listener = await asyncio.start_server(accepted, '127.0.0.1', port_wanted)
            except OSError as exc:
                if not port_wanted or not port_busy(exc):
                    raise
                listener = await self.listen_on_free_port(accepted, port_wanted)
            self.listeners[key] = listener
        return self.listeners[key].sockets[0].getsockname()[1]

    async def listen_on_free_port(self, accepted, port):
        """REDE-77: the game port is taken. An old relay of the bot is ended; any other
        program keeps its port and the game's NRO - BOT LOCAL entry moves to a free one."""
        from .port_guard import free
        freed, message = free(port)
        if freed:
            print(message[:1].upper()+message[1:]+'.')
            for _ in range(10):
                await asyncio.sleep(.5)
                try:
                    return await asyncio.start_server(accepted, '127.0.0.1', port)
                except OSError as exc:
                    if not port_busy(exc):
                        raise
        from . import relay_profile
        message = message or 'programa não identificado'
        for candidate in range(port+1, port+100):
            try:
                listener = await asyncio.start_server(accepted, '127.0.0.1', candidate)
            except OSError:
                continue
            try:
                relay_profile.change_local_port(candidate)
            except ValueError as exc:
                listener.close()
                raise OSError(f'porta {port} ocupada ({message}); e não foi possível mudar a porta do jogo: {exc}') from exc
            self.local_port = candidate
            print(f'[ALERTA] A porta {port} está ocupada por outro programa ({message}).')
            print(f'[ALERTA] O bot passou a usar a porta {candidate} e já atualizou o jogo: FECHE E ABRA O JOGO '
                  'DE NOVO e entre por NRO - BOT LOCAL.')
            return listener
        raise OSError(f'nenhuma porta livre entre {port} e {port+99}')

    def mirror_map(self, data):
        if self.tracker.failed:
            return
        try:
            if not self.mirror_ready:
                self.mirror.extend(data)
                if len(self.mirror) < 4:
                    return
                if self.account is not None and self.mirror[:4] == self.account:
                    del self.mirror[:4]
                self.mirror_ready = True
                data = bytes(self.mirror)
                self.mirror.clear()
            events = self.tracker.feed(self.mirror_sequence, data, time.monotonic())
            self.quests.observe(events,self.tracker.observer.player_id,self.tracker.observer.map_name,time.monotonic())
            self.quest_events(events,time.monotonic())
            for transition in events:
                if transition['kind'] in ('map_change','map_transfer') and transition.get('map'):
                    self.next_map=transition['map']
            self.mirror_sequence += len(data)
            self.inventory.observe(events, time.monotonic())
            self.learn_monsters(events)
            self.ammo.observe(events, time.monotonic())
            self.presence.observe(events, self.tracker.observer.player_id, time.monotonic(),
                                  own_position=self.tracker.observer.player)
            self.track_players(events)
            if not hasattr(self, 'gm_signs'):
                from .gm_signs import GmSigns
                self.gm_signs = GmSigns()
            self.gm_signs.observe(events, self.tracker.observer.player, time.monotonic())
            self.halt_on_presence()
            if self.portals.observe(events, self.tracker.observer.map_name, self.tracker.observer.player):
                self.collision_map()  # apply the new portal area right away
            self.registry.observe(events, self.tracker.observer.player_id,
                                  self.inventory.map_name or self.tracker.observer.map_name)
            self.sync_pvp_targets()
            if self.group_follower():
                self.group.observe(events, self.group_leader_id(), time.monotonic())
            self.sync_presence_names()
            own = self.tracker.observer.player_id
            for event in events:
                if event['kind'] in ('option_change', 'appearance') and event.get('entity_id') == own and own is not None:
                    self.own_option = event.get('option', 0)
                if event['kind'] == 'look_change' and event['entity_id'] == own and own is not None and event['look_type'] in (0, 1):
                    self.own_look['job' if event['look_type'] == 0 else 'hair'] = event['value']
            self.announce_presence()
            self.check_emergency()
            for event in events:
                if event['kind'] == 'stream_resync':
                    self.record_hunt(event)
                    print(f"Mensagem do servidor nao reconhecida ({event['opcode']}, {event['dropped']} bytes); leitura ressincronizada sem pausar.")
            if any(e['kind'] in ('appearance', 'name', 'remove', 'map_change', 'map_transfer') for e in events):
                self.sync_map_monsters()
            for event in events:
                if event['kind'] == 'server_disconnect':
                    self.error = f"Servidor enviou desconexao, codigo {event['reason_raw']}"
                    self.record_hunt(event)
                    print(self.error)
                if event['kind'] == 'hotkeys_info':
                    binding = next((entry for entry in event['hotkeys'] if entry['slot'] == 1), None)
                    self.record_hunt({'kind': 'f2_binding', 'binding': binding})
                    print(f'Atalho F2 recebido do servidor: {binding}. Bot configurado para habilidade 524, nível 10.')
            if self.hunt is not None:
                if (not self.tracker.observer.free_cast_movement and self.hunt.pending is not None and self.hunt.pending['kind'] == 'move'
                    and any(e['kind'] == 'skill_cast' and e.get('source_id') == self.tracker.observer.player_id for e in events)):
                    if self.hunt.patrol is not None and self.tracker.observer.player is not None:
                        self.hunt.patrol.reached(self.tracker.observer.player, self.hunt.pending.get('origin'))
                    self.hunt.pending = None
                if self.rotation is not None:
                    self.rotation.observe(events, self.tracker.observer.player_id, time.monotonic())
                    self.flush_rotation_diagnostics()
                elif getattr(self, 'saved_summon_queue', None) is not None:
                    self.saved_summon_queue.observe(events, self.tracker.observer.player_id, time.monotonic())
                manual = self.manual_skill_pending
                if manual is not None and time.monotonic() >= manual['deadline']:
                    self.manual_skill_pending = manual = None
                bot_skill = self.hunt.pending if self.hunt.pending is not None and self.hunt.pending['kind'] == 'skill' else None
                trace_request = bot_skill or manual
                if trace_request is not None:
                    for event in events:
                        if self.skill_trace_count >= 200:
                            break
                        if event['kind'] == 'player_stat' and event.get('stat_type') != 7:
                            continue
                        allowed = ('opcode', 'kind', 'skill_id', 'level', 'source_id', 'target_id', 'entity_id', 'position', 'destination', 'reason',
                                   'damage_raw', 'cause_raw', 'flag_raw', 'stat_type', 'value', 'effect_id', 'active', 'success', 'duration_ms')
                        trace = {key: event[key] for key in allowed if key in event}
                        with (self.folder/'respostas_habilidade.jsonl').open('a', encoding='utf-8') as log:
                            log.write(json.dumps({'received_at': datetime.now().isoformat(),
                                                  'requested_target': trace_request['target_id'],
                                                  'request_source': 'bot' if bot_skill else manual.get('origin', 'manual'),
                                                  'event': trace}, ensure_ascii=False)+'\n')
                        self.skill_trace_count += 1
                if self.manual_kunai_trace is not None:
                    target, deadline = self.manual_kunai_trace
                    if time.monotonic() >= deadline or any(
                            e['kind'] in ('map_change', 'map_transfer') for e in events):
                        self.manual_kunai_trace = None
                if manual is not None:
                    if manual['target_id'] == self.tracker.observer.player_id:
                        ack = any(e['kind'] == 'skill_no_damage' and e['skill_id'] == manual['skill_id']
                                  and e['source_id'] == manual['target_id'] and e['target_id'] == manual['target_id']
                                  and e['success'] for e in events)
                        if ack:
                            manual['ack_at'] = time.monotonic()
                        candidates = {e['effect_id'] for e in events if e['kind'] == 'status_effect'
                                      and e['entity_id'] == manual['target_id'] and e['active']
                                      and (manual.get('origin') == 'probe' or e['effect_id'] not in manual['effects_before'])}
                        if manual.get('origin') == 'probe':
                            manual.setdefault('observed_effects', set()).update(candidates)
                        if manual.get('origin') != 'probe' and len(candidates) == 1 and time.monotonic()-manual.get('ack_at', -1000) <= .5:
                            effect_id = next(iter(candidates))
                            self.buff_candidates[manual['skill_id']] = effect_id
                            self.record_hunt({'kind': 'buff_link_candidate', 'skill_id': manual['skill_id'], 'effect_id': effect_id})
                            print(f"Vínculo candidato de buff: habilidade {manual['skill_id']} / efeito {effect_id}. Confira na aba Habilidades.")
                    for event in events:
                        if (event['kind'] == 'skill_damage' and event['source_id'] == self.tracker.observer.player_id
                            and all(event[key] == manual[key] for key in ('skill_id', 'level', 'target_id'))):
                            self.record_hunt({**event, 'kind': 'manual_skill_confirmed'})
                            if event['skill_id'] == 524:
                                self.manual_kunai_trace = (event['target_id'], time.monotonic()+8)
                            self.manual_skill_pending = None
                            print('Dano da habilidade manual confirmado e registrado para comparação.')
                            break
                if self.manual_kunai_trace is not None:
                    target, _ = self.manual_kunai_trace
                    for event in events:
                        if event['kind'] == 'remove' and event.get('entity_id') == target and event.get('reason') == 1:
                            self.record_hunt({'kind': 'manual_kunai_target_death', 'target_id': target,
                                              'map': self.tracker.observer.map_name, 'opcode': event.get('opcode')})
                            self.manual_kunai_trace = None
                            break
                if any(e['kind'] in ('map_change', 'map_transfer') for e in events):
                    self.map_validation = None
                    if self.hunt.enabled:
                        self.hunt.pause(f'mapa alterado; {self.hunt_key_name} retoma no novo mapa')
                    self.hunt.blocked_until.clear()
                    if self.hunt.patrol is not None:
                        self.hunt.patrol.reset()
                before = self.hunt.confirmed_attacks
                self.hunt.observe(events, self.tracker.observer.player_id, time.monotonic(),
                                  movement_motion=self.tracker.observer.player_motion)
                self.flush_hunt_diagnostics()
                if self.hunt.confirmed_attacks != before:
                    self.record_hunt({'kind': 'attack_confirmed', 'count': self.hunt.confirmed_attacks,
                                      'target_id': self.hunt.target})
            if self.last_test is not None and self.last_test['status'] == 'sent_waiting_response':
                for event in events:
                    if (event['kind'] == 'normal_attack' and event['source_id'] == self.last_test['player_id']
                        and event['target_id'] == self.last_test['target_id']):
                        self.last_test.update(status='confirmed_response', damage_raw=event['damage_raw'],
                                             response_delay_ms=round((time.monotonic()-self.test_deadline+5)*1000, 2))
                        self.record_test()
                        print(f"Ataque por pacote confirmado: alvo {event['target_id']}, dano recebido {event['damage_raw']}.")
                        break
        except ValueError as exc:
            self.tracker.fail(exc)
            if self.hunt is not None:
                self.hunt.pause('leitura interrompida')
            # Map-server traffic only, capped for diagnosing framing; login
            # and character authentication streams are never written here.
            (self.folder/'mapa-diagnostico.bin').write_bytes(data[:262144])
            print(f'Leitura dos alvos suspensa: {exc}. O encaminhamento do jogo continua.')

    def select_character(self, identity):
        if self.character_id != identity:
            self.tracker.observer.clear()
            self.own_option = 0
        self.character_id = identity

    def begin_map_observation(self):
        self.release_player()
        self.player_tracks.clear()
        self.player_first_seen.clear()
        self.presence.reset()
        self.sync_pvp_targets()
        self.discovered_monsters.clear()
        old = self.tracker.observer
        kept, pinned = old.keep_character(), old.pinned
        identity = int.from_bytes(self.account, 'little') if self.account else old.player_id
        self.tracker = ContinuousTracker(old.species, player_ttl=None, idle_timeout=None, entity_ttl=None)
        observer = self.tracker.observer
        observer.restore_character(kept)
        observer.player_id = identity
        observer.free_cast_movement = True
        observer.collision_provider = self.collision_map
        observer.pinned = pinned
        observer.map_name = self.next_map

    async def bridge(self, stage, host, port, client_reader, client_writer):
        upstream = None
        jobs = []
        try:
            remote_reader, upstream = await asyncio.open_connection(host, port)
            self.error = None
            self.stage = stage
            if stage == 'login':
                self.account = None
                self.character_id = None
                self.tracker.observer.clear()
                self.own_option = 0
            if stage == 'map':
                if self.upstream is not None:
                    raise ValueError('Já existe conexão de mapa neste relay')
                self.upstream = upstream
                self.begin_map_observation()
                self.last_inventory_written = 0
                self.inventory.reset(self.next_map)
                self.ammo.reset()
                self.map_validation = None
                if self.rotation is not None:
                    self.rotation.reset_session(self.next_map)
                if self.hunt is not None and self.hunt.patrol is not None:
                    self.hunt.patrol.reset()
                self.game_peer = client_writer.get_extra_info('peername')
                self.game_local = client_writer.get_extra_info('sockname')
                self.mirror_sequence, self.mirror_ready = 0, False
                self.mirror.clear()
                self.manual_skill_diagnostic.tail = b''
                self.manual_skill_pending = None
                from .client_frame_guard import ClientFrameGuard
                self.native_frames = ClientFrameGuard()
                self.recent_map_sends.clear()
                self.error = None
            self.status()
            print(f'Conexão {stage} encaminhada.')

            async def client_to_server():
                while data := await client_reader.read(65536):
                    async with self.send_lock:
                        if stage == 'map':
                            if self.tracker.observer.player_position_valid(time.monotonic()):
                                previous_error = self.native_frames.error
                                self.inspect_native_frames(data)
                                if self.native_frames.error and not previous_error:
                                    if self.hunt is not None:
                                        self.hunt.pause(self.native_frames.error)
                                    self.record_hunt({'kind': 'native_frame_unrecognized', 'reason': self.native_frames.error})
                                    print(self.native_frames.error)
                            self.inspect_manual_skill(data)
                            data = self.drop_clicks_under_overlay(data)
                        if data:
                            upstream.write(data)
                        await upstream.drain()
                if stage == 'map':
                    self.record_hunt({'kind': 'connection_eof', 'source': 'game_client', 'recent_map_sends': list(self.recent_map_sends)})

            async def server_to_client():
                frames = HandshakeFrames(stage, self.account)
                removal = None
                if stage == 'map' and (Path(__file__).resolve().parents[1]/'perfis'/'remocao_visual_imediata').is_file():
                    from .immediate_monster_removal import ImmediateMonsterRemoval
                    from .map_monsters import is_confirmed_monster

                    def confirmed_monster(entity_id):
                        entity = self.inventory.entities.get(entity_id)
                        if entity is None or not is_confirmed_monster(entity, self.tracker.observer.player_id):
                            return False
                        self.record_hunt({'kind': 'immediate_monster_removal', 'target_id': entity_id,
                                          'map': self.tracker.observer.map_name})
                        return True

                    removal = ImmediateMonsterRemoval(self.account, confirmed_monster)
                while data := await remote_reader.read(65536):
                    if stage == 'map':
                        visible = removal.feed(data) if removal is not None else data
                        if visible:
                            client_writer.write(visible)
                            await client_writer.drain()
                        self.mirror_map(data)
                    else:
                        frames.feed(data)
                        while (frame := frames.pop()) is not None:
                            op, packet = frame
                            if op == 0x69:
                                self.account = packet[8:12]  # in memory only
                                self.own_look = {'sex': packet[46]} if len(packet) > 46 else {}
                            elif op == 0x6b:
                                self.char_list = packet
                                self.schedule_character_choice(packet, upstream)
                            elif op == 0x71:
                                self.select_character(struct.unpack_from('<I', packet, 2)[0])
                                from .packet_reader import character_look
                                self.own_look.update(character_look(self.char_list, self.character_id) or {})
                                self.next_map = packet[6:22].split(b'\0')[0].decode('cp1252', 'replace')
                            packet = await rewrite_endpoints(op, packet, self.register)
                            client_writer.write(packet)
                            await client_writer.drain()
                    if time.monotonic()-self.last_saved > .5:
                        self.last_saved = time.monotonic()
                        self.status()
                if removal is not None and (remaining := removal.flush()):
                    client_writer.write(remaining)
                    await client_writer.drain()
                if stage == 'map':
                    self.record_hunt({'kind': 'connection_eof', 'source': 'remote_server', 'recent_map_sends': list(self.recent_map_sends)})
            jobs = [asyncio.create_task(client_to_server()), asyncio.create_task(server_to_client())]
            done, pending = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (OSError, ValueError, asyncio.IncompleteReadError) as exc:
            self.error = str(exc)
            print(f'Conexão {stage} interrompida: {exc}')
        finally:
            for task in jobs:
                task.cancel()
            if jobs:
                await asyncio.gather(*jobs, return_exceptions=True)
            if self.upstream is upstream:
                self.upstream = None
                self.game_peer = self.game_local = None
                kept = self.tracker.observer.keep_character()  # REDE-83: a map-server switch reconnects
                self.tracker.observer.clear()
                self.tracker.observer.restore_character(kept)
                self.inventory.reset()
                self.stage = 'map_disconnected'
                if self.hunt is not None:
                    self.hunt.pause('conexão de mapa encerrada')
            for writer in (client_writer, upstream):
                if writer is not None:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except OSError:
                        pass
            self.status()

    async def send_attack(self, target_id, *, game_gate):
        if not self.allow_commands:
            raise RuntimeError('Primeira fase do relay é somente conexão/observação')
        async with self.send_lock:
            if not self.native_frames.ready:
                raise ValueError('Aguardando término do comando nativo')
            if self.commands_blocked or self.single_attack_used:
                raise RuntimeError('Envio bloqueado: envios parados ou teste único já realizado')
            state = self.status()
            if not game_gate() or self.upstream is None or state['candidate'] is None or state['candidate']['entity_id'] != target_id:
                raise ValueError('Sessão, foco ou alvo recente não confirmado')
            observer = self.tracker.observer
            if observer.player_id is None or not observer.player_alive:
                raise ValueError('Identidade ou vida do personagem não confirmada')
            if math.dist(observer.player, state['candidate']['position']) > 3:
                raise ValueError('Aproxime-se do Bikouchuu: o teste exige distância de até três células')
            if time.monotonic()-observer.registry.entities[target_id].seen_at > 5:
                raise ValueError('O teste único exige posição recebida há até cinco segundos')
            payload = attack(target_id)
            self.single_attack_used = True
            self.test_deadline = time.monotonic()+5
            self.last_test = {'status': 'sent_waiting_response', 'target_id': target_id,
                              'player_id': observer.player_id, 'opcode': '0190',
                              'packet_length': len(payload), 'sent_at': datetime.now().isoformat()}
            self.record_test()
            try:
                self.trace_map_send('bot', struct.unpack_from('<H', payload)[0], len(payload))
                self.upstream.write(payload)
                await self.upstream.drain()
            except OSError:
                self.last_test['status'] = 'send_failed_or_uncertain'
                self.record_test()
                raise
            print(f'Ataque único enviado por pacote ao ID {target_id}; aguardando resposta do servidor.')

    async def close(self):
        self.allow_commands = False
        if self.hunt is not None:
            self.hunt.pause('relay encerrado')
        for server in self.listeners.values():
            server.close()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        # Python 3.12 Server.wait_closed also waits for accepted connections.
        # Cancel/close bridges first, otherwise shutdown can deadlock.
        await asyncio.gather(*(server.wait_closed() for server in self.listeners.values()))
        self.account = None
        self.stage = 'stopped'
        self.status()

    def load_watchlist(self):
        from . import watchlist
        try:
            info = watchlist.FILE.stat()
            stamp = (info.st_mtime_ns, info.st_size)
        except OSError:
            stamp = None
        if stamp != self.watch_stamp:
            self.watch_stamp, self.watch_entries = stamp, watchlist.load()
        return self.watch_entries

    def gm_signs_found(self, now):
        """[(row, reasons)] of visible characters that look like GM/staff."""
        from .gm_signs import GmSigns
        if not hasattr(self, 'gm_signs'):
            self.gm_signs = GmSigns()
        result = []
        for row in self.players_nearby():
            if self.presence.ignored(row['entity_id']):
                continue
            entry = self.registry.players.get(str(row['entity_id']))
            speed = self.gm_signs.speeds.get(row['entity_id'])
            why = self.gm_signs.reasons(row, entry, speed, now)
            if why:
                result.append((row, why))
        return result

    def emergency_detections(self):
        """Watched characters found (any way, @hide included) and anyone in @hide / invisible."""
        from . import watchlist
        from .presence_guard import OPTION_INVISIBLE
        now = time.monotonic()
        entries = self.load_watchlist()
        hidden_gm = any(h['option'] & OPTION_INVISIBLE for h in self.presence.hidden.values())
        self.sync_presence_names()
        signs = self.gm_signs_found(now)
        if not entries and not self.presence.ghosts and not hidden_gm and not signs:
            return []
        state = {'presence': self.presence.snapshot(self.tracker.observer.player, now),
                 'players_nearby': self.players_nearby()}
        found = {d['entity_id']: {**d, 'watched': True} for d in watchlist.detections(entries, state, self.registry.players)}
        # Not on the list: a character in @hide is enough, seen switching it on or acting invisible.
        everyone = watchlist.detections(['*'], state, self.registry.players, match_all=True)
        for d in everyone:
            # Only a confirmed @hide (option 0x40) stops everything; common hide/cloak and
            # characters acting unseen only pause the hunt.
            if d['kind'] == 'gm_hide' and d['entity_id'] not in found and not self.presence.ignored(d['entity_id']):
                found[d['entity_id']] = {**d, 'watched': False}
        for row, why in signs:  # a GM/staff character on screen
            if row['entity_id'] not in found:
                found[row['entity_id']] = dict(entity_id=row['entity_id'], name=row.get('name'), kind='gm',
                                               text='GM/staff na tela: '+', '.join(why), detail=f"{row.get('distance')} celulas",
                                               position=row.get('position'), entry='GM', watched=False)
        return list(found.values())

    def check_emergency(self):
        found = self.emergency_detections()
        current = {(d['entity_id'], d['kind']) for d in found}
        new = [d for d in found if (d['entity_id'], d['kind']) not in self.emergency_current]
        self.emergency_current = current  # someone who left stops the bot again on return
        if not new:
            return
        first = new[0]
        who = first['name'] or f"ID {first['entity_id']}"
        reason = ('jogador da lista de observacao' if first['watched'] else 'GM/staff' if first['kind'] == 'gm' else 'personagem em @hide')+f": {who} {first['text']}"
        self.emergency = {'id': (self.emergency or {}).get('id', 0)+1, 'reason': reason,
                          'detections': found, 'at': datetime.now().isoformat(timespec='seconds')}
        self.record_hunt({'kind': 'emergency_stop', 'reason': reason, 'detections': found})
        print(f'[PARADA] Bot parado ate voce iniciar novamente: {reason}.')
        self.commands_blocked = True
        if self.hunt is not None:
            self.hunt.pause(f'PARADO: {reason}; inicie novamente pelo painel')
        try:
            asyncio.get_running_loop().create_task(self.stop_walking())
        except RuntimeError:
            pass

    def halt_on_presence(self):
        """A player just showed up while hunting: stop at once, not at the next hunt tick, so no
        walking is seen when they arrive."""
        hunting = self.hunt is not None and self.hunt.enabled or getattr(self.quests, 'phase', None) == 'hunt'
        if (not hunting or self.presence_hold is not None or self.commands_blocked or not self.allow_commands
                or not self.walking_now()):
            return
        if self.presence.reason(self.tracker.observer.player, time.monotonic()) is None:
            return
        if self.hunt is not None:
            self.hunt.pending = None
        try:
            asyncio.get_running_loop().create_task(self.stop_walking())
        except RuntimeError:
            pass

    async def stop_walking(self):
        """A walk already sent would carry on for a few cells: stop on the current cell."""
        positions = self.tracker.observer.combat_positions(time.monotonic())
        player = positions[0] if positions else self.tracker.observer.player
        if player is None or self.upstream is None or not self.native_frames.ready or not self.walking_now():
            return
        async with self.send_lock:
            payload = move(*player)
            self.trace_map_send('bot', struct.unpack_from('<H', payload)[0], len(payload))
            self.upstream.write(payload)
            await self.upstream.drain()

    async def update_presence_hold(self):
        """REDE-61: True while the bot must stay still; stops an in-flight walk once."""
        self.sync_presence_names()
        reason = self.presence.reason(self.tracker.observer.player, time.monotonic())
        if reason is None:
            if self.presence_hold is not None:
                if self.sitting:
                    if not await self.send_body_action(STAND):
                        self.presence_hold = 'aguardando conexao pronta para levantar e retomar'
                        return True
                    self.sitting = False
                    if self.hunt is not None:
                        self.hunt.ready_at = max(self.hunt.ready_at, time.monotonic()+.6)  # time to stand up
                self.record_hunt({'kind': 'presence_hold_released', 'reason': self.presence_hold})
                print('Presenca suspeita saiu do campo de visao; caca retomada.')
                self.presence_hold = None
                if self.hunt is not None:
                    self.hunt.reason = ''
            return False
        if self.presence_hold is None:
            self.record_hunt({'kind': 'presence_hold', 'reason': reason})
            print(f'Caca suspensa: {reason}.')
            player = self.tracker.observer.player
            walking = self.hunt is not None and self.hunt.pending is not None and self.hunt.pending['kind'] == 'move'
            if walking and player is not None and self.upstream is not None:
                async with self.send_lock:
                    if self.native_frames.ready:
                        payload = move(*player)
                        self.trace_map_send('bot', struct.unpack_from('<H', payload)[0], len(payload))
                        self.upstream.write(payload)
                        await self.upstream.drain()
        self.presence_hold = reason
        if self.sit_on_players and not self.sitting and not self.walking_now():
            if await self.send_body_action(SIT):
                self.sitting = True
                self.record_hunt({'kind': 'sat_down', 'reason': reason})
                print('Sentado enquanto o jogador estiver por perto.')
        if self.hunt is not None:
            self.hunt.pending = None
            self.hunt.target = None
            self.hunt.reason = 'suspensa: '+reason+(' • sentado' if self.sitting else '')
        return True

    def after_rotation_action(self, action, *, skill_sent=False, attack_turn=False, now=None, summon_maintenance=False, hold_movement=False):
        if action is None:
            return None
        if action['kind'] == 'move':
            return None if hold_movement else action
        if summon_maintenance:
            return None
        if skill_sent:
            return None
        now = time.monotonic() if now is None else now
        if not attack_turn and now < max(self.rotation.next_send, self.tracker.observer.cast_until):
            return None
        return action

    def attack_turn(self, action):
        """A basic attack may take the next packet (basic attacks on, target in reach)."""
        return (action is not None and action['kind'] == 'attack' and self.rotation is not None
                and bool(self.settings and self.settings['auto_attacks']))

    def walking_now(self):
        motion = self.tracker.observer.player_motion
        return motion is not None and time.monotonic() < motion['at']+motion['duration']

    async def send_body_action(self, action):
        """Sit or stand up; False when the connection or the native stream is not ready."""
        if self.upstream is None or not self.allow_commands or self.commands_blocked:
            return False
        async with self.send_lock:
            if not self.native_frames.ready:
                return False
            payload = body_action(action)
            self.trace_map_send('bot', struct.unpack_from('<H', payload)[0], len(payload))
            self.upstream.write(payload)
            await self.upstream.drain()
        return True

    async def send_hunt_action(self, action, *, game_gate):
        async with self.send_lock:
            if not self.allow_commands or self.commands_blocked or self.hunt is None or not self.hunt.enabled:
                raise ValueError('Caça inativa ou bloqueada')
            if not self.native_frames.ready:
                raise HuntTargetChanged('Aguardando término do comando nativo antes de enviar')
            if self.hunt.pending is not None or time.monotonic() < self.hunt.ready_at:
                raise ValueError('Ação anterior ainda pendente ou intervalo de ataque ativo')
            state = self.status()
            observer = self.tracker.observer
            entity = observer.registry.entities.get(action['target_id'])
            if action['kind'] == 'move' and not self.hunt.auto_movement:
                raise HuntTargetChanged('Movimentação automática desativada')
            group_follow = action.get('purpose') == 'group_follow'
            is_patrol = action.get('purpose') in ('patrol','group_follow')
            move_limit = 4 if group_follow or not is_patrol else self.hunt.patrol.max_step
            if group_follow and not self.group_follower():
                raise HuntTargetChanged('Modo seguidor nao esta ativo')
            if self.group_follower():
                if group_follow:
                    if self.group_leader_id() is None:
                        raise HuntTargetChanged('Lider nao esta mais visivel')
                elif not self.group_combat_allowed(action['target_id']):
                    raise HuntTargetChanged('Aguardando alvo atual do lider')
            if (not game_gate() or self.upstream is None or state['state'] != 'tracking'
                or not observer.player_position_valid(time.monotonic()) or observer.player_id is None):
                raise ValueError('Foco, personagem ou alvo recente não confirmado')
            if is_patrol and (action['kind'] != 'move' or (not group_follow and self.hunt.patrol is None)
                              or action['target_id'] is not None):
                raise ValueError('Comando de patrulha inválido')
            captured = entity is not None and entity.kind == 'player' and self.player_target_allowed(entity.entity_id)
            if not is_patrol and (entity is None or not entity.alive
                or not (captured or (entity.kind == 'monster' and entity.species_id in observer.species
                    and self.monster_name_allowed(entity.entity_id, entity.species_id)))
                or not observer.registry.current(entity, time.monotonic())
                or self.hunt.excluded_until.get(action['target_id'], 0) > time.monotonic()):
                raise HuntTargetChanged('Alvo removido, antigo ou temporariamente ignorado')
            player = observer.player
            target = None if is_patrol else entity.combat_bounds(time.monotonic())[0][0]
            if is_patrol and not group_follow and any(math.dist(player, e['position']) <= self.hunt.SEARCH_RADIUS
                                 and self.hunt.excluded_until.get(e['entity_id'], 0) <= time.monotonic()
                                 for e in state['recent_entities']):
                raise HuntTargetChanged('Alvo apareceu; patrulha interrompida')
            if not is_patrol and action['target_id'] != self.hunt.target and math.dist(player, target) > self.hunt.SEARCH_RADIUS:
                raise HuntTargetChanged('Alvo fora do raio de caça')
            if action['kind'] in ('attack', 'skill'):
                limit = min(6, observer.skills.get(524, {}).get('range', 0)) if action['kind'] == 'skill' else 2
                positions, arrival_estimated = entity.combat_bounds(time.monotonic())
                if max(math.dist(player, point) for point in positions) > limit:
                    raise HuntTargetChanged('Alvo mudou de célula antes do ataque; recalculando')
                collision = self.collision_map()
                if collision is not None:
                    if action['kind'] == 'skill':
                        if not all(collision.line_clear(player, point) for point in positions):
                            raise HuntTargetChanged('Linha da habilidade bloqueada')
                        if (entity.destination is not None and not entity.position_bounds(time.monotonic())[1]
                            and not collision.line_clear([entity.x, entity.y], entity.destination)):
                            raise HuntTargetChanged('Trajeto estimado do alvo cruza obstaculo')
                    else:
                        if not all(collision.melee_reachable(player, point) for point in positions):
                            raise HuntTargetChanged('Alvo nao esta adjacente por caminho livre')
                if action['kind'] == 'skill':
                    persistent_position = observer.registry.ttl is None and (entity.destination is None or arrival_estimated)
                    if time.monotonic()-entity.seen_at > 1.5 and not persistent_position:
                        raise HuntTargetChanged('Posição do alvo antiga antes da habilidade; aguardando atualização')
                    expected = self.hunt.skill_action(state, entity.entity_id, time.monotonic())
                    metadata = observer.skills.get(524)
                    if expected != action or metadata is None:
                        raise HuntTargetChanged('Habilidade, SP ou intervalo não confirmado; recalculando ataque')
                    payload = skill(entity.entity_id, action['skill_id'], action['level'])
                else:
                    payload = attack(entity.entity_id)
            elif action['kind'] == 'move':
                destination = action['destination']
                if action.get('origin', player) != player:
                    raise HuntTargetChanged('Posição própria corrigida antes do envio; recalculando')
                collision = self.collision_map()
                if self.settings and self.settings['require_collision'] and collision is None:
                    raise ValueError('Movimento bloqueado: mapa de colisão indisponível')
                if collision is not None:
                    blocked = {p for p, until in self.hunt.blocked_until.items() if until > time.monotonic()}
                    if group_follow:
                        leader = self.player_tracks[self.group_leader_id()].combat_bounds(time.monotonic())[0][0]
                        expected = self.group.plan_follow(state,leader,self.settings,collision,blocked,observer.walk_speed_ms)
                        if expected != action:
                            raise HuntTargetChanged('Lider mudou de posicao; recalculando seguimento')
                    if not collision.segment(player, destination, blocked, max_steps=move_limit):
                        raise HuntTargetChanged('Rota mudou ou segmento cruza obstáculo')
                elif action.get('collision_route'):
                    raise HuntTargetChanged('Mapa da rota ficou indisponível')
                elif (not 1 <= max(abs(destination[i]-player[i]) for i in (0, 1)) <= (move_limit)
                      or not all(1 <= n <= 1022 for n in destination)
                      or (not is_patrol and action.get('purpose') != 'keep_distance' and math.dist(destination, entity.destination or target)
                          >= math.dist(player, entity.destination or target))):
                    raise HuntTargetChanged('Passo inválido ou alvo mudou de direção')
                payload = move(*destination)
            else:
                raise ValueError('Ação de caça não suportada')
            self.hunt.sent(action, time.monotonic())
            if action['kind'] == 'skill':
                self.skill_trace_count = 0
                print(f"Kunai enviada ao alvo {action['target_id']}; aguardando resposta.")
                self.record_hunt({'kind': 'skill_encoded', 'skill_id': action['skill_id'],
                                  'level': action['level'], 'target_id': action['target_id'],
                                  'player_position_age_seconds': round(time.monotonic()-observer.player_at, 3),
                                  'target_position': target, 'target_position_age_seconds': round(time.monotonic()-entity.seen_at, 3),
                                  'packet_hex': payload.hex()})
            try:
                self.trace_map_send('bot', struct.unpack_from('<H', payload)[0], len(payload))
                self.upstream.write(payload)
                await self.upstream.drain()
            except OSError:
                self.hunt.pause('envio falhou ou ficou incerto')
                raise
            self.record_hunt({'kind': 'patrol_sent' if is_patrol else action['kind']+'_sent', 'target_id': action['target_id'],
                              'destination': action.get('destination'), 'packet_length': len(payload),
                              'map': observer.map_name, 'origin': list(player),
                              'skill_id': action.get('skill_id'), 'level': action.get('level'),
                              'patrol_heading': action.get('patrol_heading'),
                              'new_sectors_on_path': action.get('new_sectors_on_path'),
                              'collision_route': action.get('collision_route', False)})


def port_busy(exc):
    """Address already in use, however the platform reports it."""
    return exc.errno in (10048, 98, 48) or getattr(exc, 'winerror', None) == 10048


def resolve_connection(args):
    """Server and local port without typing them: read from the game's own files."""
    import socket
    from . import relay_profile
    server, port = args.server, args.port
    if server is None:
        found = relay_profile.original_server()
        server, found_port = found if found else ('187.77.36.200', 6900)
        port = port or found_port
        print(f'Servidor do jogo: {server}:{port}'+(' (lido da conexão original do jogo)' if found else ' (padrão)'))
    port = port or 6900
    try:
        address = socket.gethostbyname(server)  # clientinfo may hold a host name
    except OSError:
        address = server
    local = args.local_port or relay_profile.installed_port() or 16900
    return address, port, local


async def run(args):
    folder = Path(args.session_dir) if getattr(args, 'session_dir', None) else Path(__file__).resolve().parents[1]/'logs/relay'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    active_test = getattr(args, 'single_attack_test', False)
    hunt_mode = getattr(args, 'hunt', False)
    args.server, args.port, args.local_port = resolve_connection(args)
    relay = SessionRelay(args.server, args.port, args.local_port, folder=folder,
                         species={1037} if hunt_mode else None,
                         allow_commands=active_test or hunt_mode)
    if hunt_mode:
        from .packet_hunt import PacketHunt
        relay.hunt = PacketHunt(patrol=True, use_skills=True)
        from .packet_settings import read, SPECIES
        relay.apply_settings(read())
        from .map_navigation import MapRepository
        from .grf import GrfError
        try:
            print('Preparando índice de mapas locais...')
            from .game_folder import find
            game_dir = args.game_dir or find()
            if game_dir is None:
                raise GrfError('pasta do jogo não encontrada; escolha a pasta do jogo no painel')
            from .game_folder import running_game
            opened = running_game()
            if opened is not None and Path(opened).resolve() != Path(game_dir).resolve():
                print(f'ATENÇÃO: o jogo aberto está em {opened}, mas o bot usa a pasta {game_dir}. '
                      'Escolha a pasta do jogo aberto no painel (Conexão > Pasta do jogo); mapas e GRFs vêm de lá.')
            from .packet_reader import configure_client_game
            configure_client_game(game_dir)
            relay.map_repository = MapRepository(game_dir)
            from .grf import data_ini_grfs
            import os as _os
            grfs = relay.map_repository.grfs
            listed = data_ini_grfs(_os.path.join(str(game_dir), 'DATA.INI'))
            missing = [n for n in listed if not _os.path.isfile(_os.path.join(str(game_dir), n))]
            print(f'Pasta do jogo: {game_dir} | GRFs do DATA.INI: {len(listed)} ({", ".join(listed)})'
                  + (f' | não encontrados: {", ".join(missing)}' if missing else '')
                  + (f' | ignorados: {"; ".join(grfs.skipped)}' if grfs.skipped else ''))
            from .ammo import names_from_grfs
            relay.ammo.names = names_from_grfs(relay.map_repository.grfs)
        except (OSError, ValueError, GrfError) as exc:
            print(f'Colisão indisponível: {exc}. Aproximação anterior mantida. Pasta do jogo usada: {locals().get("game_dir")}')
    from .packet_reader import client_lengths
    try:
        sizes = client_lengths()
        if not sizes:
            raise ValueError('Tabela de pacotes ausente; baixe o pacote completo do bot.')
        print(f'Tabela de pacotes validada para este cliente: {len(sizes)} mensagens.')
    except (OSError, ValueError) as exc:
        relay.error = str(exc)
        relay.stage = 'stopped'
        relay.status()
        print(f'Nao foi possivel abrir a conexao: {exc}')
        return
    controls = None
    if active_test or hunt_mode:
        from .packet_controls import GameControls
        controls = GameControls()
    previous_key = False
    previous_hunt_key = False
    try:
        port = await relay.register('login', args.server, args.port)
        relay.stage = 'waiting_login'
        relay.status()
        print(f'Relay local pronto em 127.0.0.1:{port}. Registros: {folder}')
        print('Modo de conexão/observação. Login e senha não são gravados. Ctrl+C encerra o relay e desconecta a sessão local.')
        if active_test:
            print('TESTE ÚNICO: no jogo, Ctrl+Alt+F10 solicita um ataque por pacote. Nenhum ataque é automático.')
        if hunt_mode:
            targets = 'automaticos do mapa' if relay.settings['auto_map_targets'] else ', '.join(SPECIES.get(i, str(i)) for i in relay.settings['species'])
            print(f"CAÇA: {relay.hunt_key_name} inicia/pausa. Alvos: {targets}; raio: {relay.settings['radius']} células. Começa DESLIGADA.")
            print('Habilidade: Arremessar Kunai nível 10, somente com nível/custo/SP confirmados. Falha retorna a ataque normal; '+relay.hunt_key_name+' permite reativar.')
        last_display = 0
        last_skill_message = None
        last_heartbeat = 0
        while True:
            await asyncio.sleep(.02)
            if hunt_mode:
                relay.process_control(lambda: controls.connected(relay.game_peer, relay.game_local))
                relay.finish_buff_learning(time.monotonic())
                if relay.buff_probe_request is not None:
                    request, relay.buff_probe_request = relay.buff_probe_request, None
                    try:
                        await relay.send_buff_probe(request, game_gate=lambda: controls.connected(relay.game_peer, relay.game_local))
                        relay.control_result = {'id': request['id'], 'ok': True, 'message': 'Buff enviado uma vez; aguarde o vínculo candidato na aba Habilidades'}
                    except (ValueError, OSError) as exc:
                        relay.control_result = {'id': request['id'], 'ok': False, 'message': str(exc)}
                    relay.status()
            if time.monotonic()-last_heartbeat >= .5:
                relay.status()
                last_heartbeat = time.monotonic()
            if controls is not None:
                key = controls.test_pressed() if active_test else False
                if key and not previous_key:
                    try:
                        state = relay.status()
                        if state['candidate'] is None:
                            raise ValueError('Nenhum alvo recente elegível. Aproxime-se de um Bikouchuu.')
                        await relay.send_attack(state['candidate']['entity_id'],
                            game_gate=lambda: controls.focused(relay.game_peer, relay.game_local))
                    except (OSError, ValueError, RuntimeError) as exc:
                        print(f'Teste não executado: {exc}')
                previous_key = key
                if hunt_mode:
                    hunt_key = controls.hunt_pressed(relay.hunt_key)
                    if hunt_key and not previous_hunt_key:
                        if relay.quests.recording:
                            print('Gravacao em andamento: salve ou descarte antes de iniciar a caca.')
                        elif relay.quests.active:
                            relay.quest_stop('Fila pausada pelo atalho')
                        elif relay.hunt.enabled:
                            relay.hunt.pause('pausada pelo usuário')
                            print('Caça pausada.')
                        elif controls.connected(relay.game_peer, relay.game_local):
                            try:
                                relay.validate_navigation_start()
                                relay.commands_blocked = False
                                relay.hunt.start()
                                relay.defer_until_manual_walk_finishes()
                                print('Caça ativada por pacote.')
                            except ValueError as exc:
                                relay.hunt.pause(str(exc))
                                print(f'Não foi possível iniciar: {exc}')
                        else:
                            print('Para iniciar a caça, mantenha o NRO conectado.')
                        relay.status()
                    previous_hunt_key = hunt_key
                    route_travel = await relay.quest_tick(lambda: controls.connected(relay.game_peer,relay.game_local))
                    if relay.hunt.enabled and not route_travel:
                        if not controls.connected(relay.game_peer, relay.game_local):
                            relay.hunt.pause('conexão do jogo indisponível')
                            print(f'Caça pausada: conexão do jogo indisponível. {relay.hunt_key_name} retoma.')
                        elif relay.manual_control(time.monotonic()) or await relay.update_presence_hold():
                            pass
                        else:
                            state = relay.status()
                            if relay.pvp_registered and state.get('player_position') is not None:
                                state = relay.prioritize_pvp(state)
                            if relay.rotation is not None:
                                state['engagement_range'] = relay.rotation.navigation_range(state, time.monotonic(), relay.hunt.target)
                            action = relay.plan_group_or_hunt(state, time.monotonic(), relay.tracker.observer.walk_speed_ms, relay.collision_map())
                            relay.flush_hunt_diagnostics()
                            if relay.rotation is not None and relay.group_combat_allowed():
                                now = time.monotonic()
                                # Select a combat target even while a patrol leg is in flight.
                                own = (state.get('combat_player_positions') or [state['player_position']])[0]
                                candidates = [e for e in state['recent_entities']
                                              if relay.hunt.excluded_until.get(e['entity_id'], 0) <= now]
                                if not relay.group_follower() and candidates and relay.hunt.target not in {e['entity_id'] for e in candidates}:
                                    candidate = min(candidates, key=lambda e: math.dist(own, e.get('effective_position', e['position'])))
                                    if math.dist(own, candidate.get('effective_position', candidate['position'])) <= relay.hunt.SEARCH_RADIUS:
                                        relay.hunt.target = candidate['entity_id']
                                # REDE-84: with basic attacks on, a basic attack follows every skill
                                # (skill, attack, skill...); with no skill ready it keeps attacking.
                                summon_maintenance = relay.rotation.summon_maintenance_required(state, now, relay.hunt.target)
                                attack_turn = (not summon_maintenance and relay.attack_turn(action) and relay.last_combat_packet == 'skill'
                                               and now >= relay.tracker.observer.cast_until)
                                skill_sent = False
                                rotation_action = None if attack_turn else relay.rotation.plan(state, now, relay.hunt.target)
                                if rotation_action is not None and relay.native_frames.ready:
                                    try:
                                        if await relay.send_rotation_action(rotation_action, game_gate=lambda: controls.connected(relay.game_peer, relay.game_local)):
                                            skill_sent = True
                                            relay.last_combat_packet = 'skill'
                                    except (OSError, ValueError) as exc:
                                        relay.hunt.pause(str(exc))
                                action = relay.after_rotation_action(action, skill_sent=skill_sent, attack_turn=attack_turn, now=now,
                                    summon_maintenance=summon_maintenance,
                                    hold_movement=not skill_sent and rotation_action is not None and rotation_action.get('cast_mode') == 'ground'
                                        and rotation_action.get('role') == 'summon' and rotation_action.get('cast_range', 1) == 0)
                                relay.flush_rotation_diagnostics()
                            if action is not None and action['kind'] == 'attack' and relay.settings and not relay.settings['auto_attacks']:
                                action = None
                            if not relay.native_frames.ready:
                                action = None
                            if action is not None:
                                try:
                                    await relay.send_hunt_action(action, game_gate=lambda: controls.connected(relay.game_peer, relay.game_local))
                                    if relay.rotation is not None and action['kind'] == 'attack':
                                        relay.last_combat_packet = 'attack'
                                        gap = relay.rotation.burst_interval if relay.rotation.burst else .12
                                        relay.rotation.next_send = max(relay.rotation.next_send, time.monotonic()+gap)
                                except HuntTargetChanged as exc:
                                    relay.hunt.replan_action(time.monotonic(), str(exc), action)
                                    relay.flush_hunt_diagnostics()
                                except (OSError, ValueError) as exc:
                                    relay.hunt.pause(str(exc))
                            if not relay.hunt.enabled:
                                relay.record_hunt({'kind': 'paused', 'reason': relay.hunt.reason})
                                print(f'Caça pausada: {relay.hunt.reason}')
            if relay.upstream is not None and time.monotonic()-last_display >= 1:
                last_display = time.monotonic()
                state = relay.status()
                candidate = state['candidate']
                label = f"ID {candidate['entity_id']} em {candidate['position']}" if candidate else 'aguardando alvo/posição recentes'
                mode = 'teste único disponível' if state['command_sending_enabled'] else 'somente observação'
                if relay.hunt is not None:
                    mode = ('caçando' if relay.hunt.enabled else 'caça pausada') + f" | ataques confirmados: {state['hunt']['confirmed_attacks']}"
                    if relay.hunt.enabled and relay.hunt.patrol is not None and relay.hunt.target is None:
                        mode = f"patrulhando | setores visitados: {len(relay.hunt.patrol.visits)} | ataques confirmados: {state['hunt']['confirmed_attacks']}"
                    if relay.rotation is not None:
                        mode += f" | habilidades confirmadas: {relay.rotation.confirmed} | buffs ativos confirmados: {relay.rotation.buff_confirmed} | SP: {state.get('player_sp')}"
                    if relay.hunt.use_skills:
                        mode += f" | Kunai confirmadas: {relay.hunt.confirmed_skills} | SP: {state.get('player_sp')}"
                        skill_message = relay.hunt.skill_reason
                        if skill_message != last_skill_message:
                            print(f'Kunai: {skill_message}')
                            last_skill_message = skill_message
                print(f"Mensagens: {state['messages']} | candidatos: {len(state['recent_entities'])} | {label} | {mode}")
    except Exception as exc:
        import traceback
        relay.error = f'{type(exc).__name__}: {exc}'
        (relay.folder/'erro_relay.txt').write_text(traceback.format_exc(), encoding='utf-8')
        print(f'Erro do relay: {relay.error}. Detalhes em erro_relay.txt')
        raise
    finally:
        await relay.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', default=None, help='padrão: o servidor da conexão original do jogo')
    parser.add_argument('--port', type=int, default=None)
    parser.add_argument('--local-port', type=int, default=None, help='padrão: a porta da entrada NRO - BOT LOCAL')
    parser.add_argument('--game-dir', default=None, help='pasta do jogo; padrão: a encontrada pelo bot')
    parser.add_argument('--session-dir')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--single-attack-test', action='store_true')
    modes.add_argument('--hunt', action='store_true')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print('Relay encerrado.')


if __name__ == '__main__':
    main()
