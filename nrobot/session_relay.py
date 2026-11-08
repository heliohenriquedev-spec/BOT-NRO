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
import sqlite3
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
    elif op in (0x71, 0x92):
        if len(packet) != 28:
            raise ValueError('Destino de mapa com comprimento invalido')
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


class MapEndpointStream:
    """Rewrite complete map-transfer messages, never opcode-like bytes inside other data."""
    def __init__(self, account, register, on_transfer):
        self.account, self.register, self.on_transfer = account, register, on_transfer
        self.buffer = bytearray()
        self.started = self.passthrough = False

    def flush(self):
        result = bytes(self.buffer); self.buffer.clear()
        return result

    async def feed(self, data):
        if self.passthrough:
            return data
        from .packet_reader import message_length
        self.buffer.extend(data)
        result = bytearray()
        if not self.started:
            if len(self.buffer) < 4:
                return b''
            self.started = True
            if self.account and self.buffer[:4] == self.account:
                result.extend(self.buffer[:4]); del self.buffer[:4]
        while self.buffer:
            try:
                size = message_length(self.buffer, 0)
            except (OSError, ValueError):
                self.passthrough = True
                print('Enquadramento de portal desconhecido; trafego encaminhado sem alterar destinos.')
                result.extend(self.flush())
                break
            if size is None or len(self.buffer) < size:
                break
            packet = bytes(self.buffer[:size]); del self.buffer[:size]
            opcode = struct.unpack_from('<H', packet)[0]
            if opcode == 0x92:
                self.on_transfer()
                packet = await rewrite_endpoints(opcode, packet, self.register)
            result.extend(packet)
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
        from .rcx_sides import Sides
        self.rcx_sides = Sides()  # RCX ally/enemy: battleground team, PvP map, party, guild, summons
        self.account = None
        self.upstream = None
        self.send_lock = asyncio.Lock()
        self.init_quests()
        self.allow_commands = allow_commands
        self.tracker = ContinuousTracker(species or {1051}, player_ttl=None, idle_timeout=None, entity_ttl=None)
        self.tracker.observer.collision_provider = self.server_collision_map
        from .player_hp import PlayerHp
        self.received_player_hp=PlayerHp()
        self.mirror = bytearray()
        self.mirror_ready = False
        self.mirror_sequence = 0
        self.stage = 'starting'
        self.login_phase = 'waiting'
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
        self.pvp_ignored = {}  # player id -> time until which attacks on them stop (no damage taken)
        self.player_misses = {}  # player id -> attacks in a row with no damage
        from .own_summons import OwnSummons
        self.own_summons = OwnSummons()  # own summons/homunculus: quest kills and homunculus feeding
        self.instance_maps = {}  # instance map (0045@tower) -> the base map with its layout (5@tower)
        from .group_hunt import GroupHunt
        self.group = GroupHunt()
        self.player_names = {}  # REDE-76: names of characters (0195 replies to the client's 008C)
        self.player_first_seen = {}
        self.own_option = 0  # REDE-73: own hide/cloak/@hide bits, for the in-game shadow
        self.own_look = {}  # class, sex and hairstyle for the shadow's real sprite
        from .portals import PortalGuard
        self.portals = PortalGuard()  # warps are never walked into
        self.quests.learned_portals = self.portals.destinations  # quests and BG also use the portals learned
        from .npc_transports import NpcTransports
        self.npc_transports = NpcTransports()  # NPCs that change the map (VIP room, returns), learned playing
        self.quests.learned_transports = self.npc_transports.known
        self.quests.forget_transport = self.npc_transports.forget
        from .npc_map import NpcMap
        self.npc_map = NpcMap()  # NPCs on the minimap, with names, remembered per map
        try:
            from . import map_routes, quest_routes
            for entry in map_routes.load():
                self.npc_map.learn_steps(entry.get('steps'))
            for route in quest_routes.load():
                for value in route.values():
                    if isinstance(value, list) and value and isinstance(value[0], dict):
                        self.npc_map.learn_steps(value)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass  # names from routes are a bonus; NPCs seen in the game are still recorded
        self.viewpoint_marks = {}  # minimap marks from the server (@showmobs, NPC quests): key -> mark
        from .player_registry import PlayerRegistry
        self.registry = PlayerRegistry()  # aba Jogadores: everyone ever seen
        self.registry_saved = 0
        # Lista de observação / @hide: stop everything until the user starts again.
        self.watch_entries, self.watch_stamp = [], None
        self.emergency = None  # {'id', 'reason', 'detections', 'at'} of the last stop
        self.emergency_current = set()  # (id, kind) found now; only a new one stops again
        self.chat_alert = None
        from .ground_cells import GroundCells
        self.ground_cells = GroundCells()
        from .toxic_ground import ToxicGround
        self.toxic_ground = ToxicGround()
        self.toxic_hold_until = 0
        self.ground_stream = None
        self.char_list = b''
        self.manual_until = 0  # REDE-76: the bot yields while the player walks by hand
        self.manual_active = False
        self.manual_walk_input = None  # live GameControls confirms a physical click in the game
        self.trails = {}  # REDE-76: walked cells per map, for the minimap
        self.trail_started = {}  # map -> when its trail began (cleared after TRAIL_KEEP)
        from .monster_db import load_captured
        self.monsters_seen = load_captured()  # REDE-79: what the game showed about each monster
        self.monsters_dirty = False
        self.monsters_written = 0
        from .drop_db import DropObserver, mob_info_species
        from .mob_info import MobInfoQueue
        self.drops = DropObserver()
        self.mob_info = MobInfoQueue(mob_info_species())  # @mi: the server's drop list of each monster
        from .mob_scan import MobScan
        self.mob_scan = MobScan()  # @showmobs in the quest hunt: walk to where the missing monsters are
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

    def sync_map_behavior(self):
        from . import map_behavior
        from copy import deepcopy
        if self.hunt is None or not getattr(self, 'map_behavior_base', None):
            return
        now = time.monotonic()
        if now < getattr(self, 'map_behavior_poll', 0):
            return
        self.map_behavior_poll = now + .5
        try:
            profiles = map_behavior.load()
            route = getattr(self.quests, 'route', None)
            database_combat = bool(self.quests.active and getattr(self.quests,'phase',None) == 'hunt'
                                   and route and route.get('id') == 'database_hunt')
            effective, profile = map_behavior.effective(self.map_behavior_base, profiles,
                self.tracker.observer.map_name, self.quests.active and not database_combat)
            config = profile.get('combat') if profile else None
            if config and (self.group_follower() or self.player_focus()):
                config, profile, effective = None, None, deepcopy(self.map_behavior_base)
            if config:
                from .map_combat import settings_for
                effective = settings_for(config, effective, list(getattr(self.tracker.observer, 'skills', {}).values()))
            previous_combat = getattr(self, 'map_combat', None)
            if config and (previous_combat is None or previous_combat.config != config):
                from .map_combat import MapCombat
                self.map_combat = MapCombat(config)
            elif not config:
                self.map_combat = None
                if previous_combat is not None:
                    self.hunt.priority_target = None
                    self.hunt.target_priority = {}
            self.map_combat_map = profile['map'] if config else None
            signature = (self.tracker.observer.map_name, self.quests.active, effective, config)
            if signature == getattr(self, 'map_behavior_signature', None):
                return
            # Do not reset combat timers/actions just because the map changed if rules did not.
            previous = getattr(self, 'map_behavior_effective', None)
            if effective != previous:
                self.apply_settings(effective, map_overlay=True)
                if self.quests.active:
                    self.quest_hunt_id = None
            self.map_behavior_signature = deepcopy(signature)
            self.map_behavior_effective = deepcopy(effective)
            print('Comportamento do mapa: '+(profile['name'] if profile else 'configuracoes gerais / quest'))
        except (OSError, ValueError) as exc:
            message = str(exc)
            if message != getattr(self, 'map_behavior_error', None):
                print('Perfil de mapa nao aplicado: '+message)
                self.map_behavior_error = message

    def apply_settings(self, settings, *, map_overlay=False):
        from .packet_settings import validate
        from .packet_patrol import PacketPatrol
        from .network_targets import Entity
        from .hunt_share import apply as published_patrol
        try:
            settings = validate(published_patrol(settings))  # the developer's patrol, the same on every PC
        except ValueError:
            settings = validate(settings)
        if not map_overlay:
            from copy import deepcopy
            self.map_behavior_base = deepcopy(settings)
            self.map_behavior_signature = None
            # These settings are the ones in use now: the map behavior only re-applies when a map
            # profile changes them. With None here, every quest hunt apply was re-applied by the map
            # behavior, which reset the quest hunt, which applied again... every 0.5 s (skills
            # delayed, attacks stopping; 2026-11-06).
            self.map_behavior_effective = deepcopy(settings)
            self.map_behavior_poll = 0
        if self.settings is not None and any(self.settings[k] != settings[k] for k in ('group_enabled','group_role','group_leader')):
            self.group.target_id = None
            self.group.target_at = 0
            if self.hunt is not None:
                self.hunt.priority_target = None
        if self.hunt is None:
            raise ValueError('Modo de caça não está disponível')
        # A saved setting no longer stops the hunt: every PvP checkbox (target, priority) autosaves,
        # and pausing here left the bot standing, without patrol, until Iniciar (PvP, 2026-11-05).
        # The current action is dropped so the next plan follows the new setup.
        self.hunt.pending = self.hunt.target = self.hunt.engaged = None
        self.hunt.approach_cache = None
        self.hunt.SEARCH_RADIUS = settings['radius']
        for attribute, key in (('SKILL_INTERVAL', 'skill_interval'), ('SKILL_RESPONSE_TIMEOUT', 'skill_timeout'),
                               ('SKILL_ATTEMPTS', 'skill_attempts'), ('TARGET_DEFER', 'target_defer')):
            setattr(self.hunt, attribute, settings[key])
        # REDE-82: failure rules can be switched off.
        if not settings['limit_target_failures']:
            self.hunt.SKILL_ATTEMPTS = 10**9
        if not settings['defer_failed_targets']:
            self.hunt.TARGET_DEFER = 0
        self.hunt.use_skills = settings['skills']
        self.hunt.auto_attacks = settings['auto_attacks']
        self.hunt.melee_approach = settings['melee_approach']
        self.hunt.target_priority = {}  # only the quest hunt sets an order (route "atacar sempre" list)
        self.hunt.kite = settings['kite']
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
            if settings.get('manual_movement') or not settings['auto_movement']:
                self.rotation.range_margin = 1  # never cast at the edge: the server would walk there
            if not settings['limit_target_failures']:
                self.rotation.attempts = 10**9
            if not settings['defer_failed_targets']:
                self.rotation.defer = .3
        if self.rotation is not None and previous_rotation is not None:
            # Saving a setting must not forget what was learned about the server's timing.
            self.rotation.ready = dict(previous_rotation.ready)
            self.rotation.cooldown_floor = dict(previous_rotation.cooldown_floor)
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
        if 0x7d in completed:
            self.map_loaded_at = time.monotonic()  # the client finished loading the map
        for opcode, frame in self.native_frames.frames:
            self.quests.native(opcode,frame,self.tracker.observer.map_name)
            self.npc_transports.client(opcode,frame,self.tracker.observer.map_name,self.quests.actors)
            if opcode == 0x72 and len(frame) == 25:
                if self.preview_rcx_self_skill(struct.unpack_from('<H',frame,10)[0],struct.unpack_from('<I',frame,21)[0],time.monotonic()):
                    self.publish_ground_cells()
            if opcode == 0x113 and len(frame) == 22:
                self.ground_cells.request_cast(struct.unpack_from('<H',frame,9)[0],
                    [struct.unpack_from('<H',frame,12)[0],struct.unpack_from('<H',frame,20)[0]],time.monotonic())
                self.publish_ground_cells()
            if opcode == 0x22d and self.own_summons.learn_feed(frame):
                print(f'Homúnculo alimentado pelo jogador (fome {self.own_summons.hunger}); pacote registrado: {frame.hex()}.')
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
        native_walk = self.hunt is not None and 0xa7 in completed and not getattr(self, 'manual_movement', False)
        physical_click = native_walk and (self.manual_walk_input is None or self.manual_walk_input())
        if native_walk and not physical_click:
            self.record_hunt({'kind': 'client_automatic_walk', 'target_id': self.hunt.target})
        if physical_click:
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

    def player_focus(self):
        """A priority player is on screen: PvP focus, players only."""
        if self.captured_player is None:
            return False
        identity = self.captured_player['entity_id']
        return identity in self.presence.players and identity not in self.presence.hidden and not self.dead(identity)

    PRIORITY_OFF_SCREEN = 3.0  # seconds a priority player may be out of view before it is dropped

    def expire_captured(self, now):
        """The priority never stays on someone who is not on screen (left the view, @hide)."""
        if self.captured_player is None:
            self.captured_missing_since = None
            return False
        identity = self.captured_player['entity_id']
        visible = identity in self.presence.players and identity not in self.presence.hidden
        if visible:
            self.captured_missing_since = None
            return False
        since = getattr(self, 'captured_missing_since', None)
        if since is None:
            self.captured_missing_since = now
            return False
        if now-since < self.PRIORITY_OFF_SCREEN:
            return False
        name = self.captured_player.get('name') or identity
        self.release_player()
        self.captured_missing_since = None
        print(f'Prioridade removida: {name} saiu da tela.')
        return True

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
            else:
                # "Everyone" never means a friend: whitelist and group members are left out, and so
                # is anyone whose name has not arrived yet (it could be one of them). The bot hit a
                # whitelisted player hundreds of times this way (2026-11-04, instance 0045@tower).
                eligible = {i for i in eligible if self.player_name_known(i) and not self.friendly(i)}
            now = time.monotonic()
            eligible = {i for i in eligible if self.pvp_ignored.get(i, 0) <= now and not self.dead(i)}
        for identity in self.pvp_registered - eligible:
            if identity not in observer.pinned:
                observer.registry.remove(identity)
                self.presence.allowed.discard(identity)
        for identity in eligible:
            observer.registry.update(self.player_tracks[identity])
        self.presence.allowed.update(eligible)
        self.pvp_registered = eligible
        # Players chosen in the PvP list are combat candidates like the captured one: before,
        # only a captured player ever reached the hunt and the list chose nobody.
        observer.pvp = set(eligible)

    def player_name_known(self, identity):
        return bool(self.player_names.get(identity) or (self.inventory.entities.get(identity) or {}).get('name'))

    def friendly(self, identity):
        """In the whitelist (Jogadores permitidos) or the group: never a PvP target by "todos"."""
        from .presence_guard import normalize_player_name
        name = self.player_names.get(identity) or (self.inventory.entities.get(identity) or {}).get('name')
        return bool(name) and normalize_player_name(name) in {normalize_player_name(n) for n in self.presence.allowed_names}

    PLAYER_MISSES = 6  # attacks in a row on a player with no damage: the map has no PvP for them
    PLAYER_SILENCE = 5.0  # ...and this long with no damage at all since the first of them
    PLAYER_IGNORE = 60

    def note_player_attack(self, identity, now):
        """Fast skills go out every ~70 ms, well before the first damage arrives: counting sends
        alone dropped a player who was being hit (PvP, 2026-11-04). Only real silence counts."""
        from .network_targets import is_player_id
        if not is_player_id(identity) or identity == self.tracker.observer.player_id:
            return
        misses, since = self.player_misses.get(identity, (0, now))
        misses += 1
        self.player_misses[identity] = (misses, since)
        if misses < self.PLAYER_MISSES or now-since < self.PLAYER_SILENCE:
            return
        self.player_misses.pop(identity, None)
        self.pvp_ignored[identity] = now+self.PLAYER_IGNORE
        if self.hunt is not None:
            self.hunt.excluded_until[identity] = now+self.PLAYER_IGNORE
            if self.hunt.target == identity:
                self.hunt.target = self.hunt.pending = None
        name = self.player_names.get(identity) or identity
        print(f'[ALERTA] {name}: {self.PLAYER_MISSES} ataques sem dano (mapa sem PvP?); ignorado por {self.PLAYER_IGNORE} s.')
        self.record_hunt({'kind': 'player_target_ignored', 'entity_id': identity, 'seconds': self.PLAYER_IGNORE})
        self.sync_pvp_targets()

    def player_target_allowed(self, identity):
        observer = self.tracker.observer
        if self.pvp_ignored.get(identity, 0) > time.monotonic():
            return False
        if self.settings is None:
            return identity in observer.pinned
        return (self.settings.get('pvp_enabled') and identity in self.presence.players
                and identity in self.player_tracks and identity not in self.presence.hidden
                and (identity in self.pvp_registered or identity in observer.pinned))

    def prioritize_pvp(self, state):
        """With "priorizar jogadores sobre monstros": fight registered players first, but only while
        one is actually reachable. When every player is far, behind a wall or being ignored, the bot
        goes on hunting monsters (summons included, their IDs are not players) and patrolling instead
        of standing still on an unattackable player (2026-11-05)."""
        now = time.monotonic()
        candidates = state['recent_entities']
        players = self.pvp_registered
        own = state['player_position']
        collision = self.collision_map()
        def reachable(row):
            return (self.hunt.excluded_until.get(row['entity_id'], 0) <= now
                    and self.pvp_ignored.get(row['entity_id'], 0) <= now
                    and math.dist(own, row['position']) <= self.hunt.SEARCH_RADIUS
                    and (collision is None or collision.line_clear(own, row['position'])
                         or self.hunt.auto_movement))
        players_in_reach = [row for row in candidates if row['entity_id'] in players and reachable(row)]
        if not players_in_reach:
            return state  # no player to fight now: keep monsters and summons, keep patrolling
        preferred = [row for row in candidates
                     if (row['entity_id'] in players) == self.settings['pvp_first']
                     and self.hunt.excluded_until.get(row['entity_id'], 0) <= now
                     and math.dist(own, row['position']) <= self.hunt.SEARCH_RADIUS]
        return {**state, 'recent_entities': preferred} if preferred else state

    def attacker_species(self, now, targets=None):
        """Species of the monsters attacking the character, when more than the configured number do.

        Only monsters that are not targets count: the hunted ones hitting back are fought anyway,
        and counting them made "ignorar ate 3" attack everyone with 2 targets + 2 others around."""
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
        targets = self.configured_species() if targets is None else set(targets)
        attackers = {i: s for i, s in attackers.items() if s not in targets}
        limit = (self.settings or {}).get('ignore_attackers', 0)
        return set(attackers.values()) if len(attackers) > limit else set()

    def include_attackers(self, now):
        """Monsters attacking (above the ignore limit) become targets, whatever their species, until
        they stop; the configured targets stay as they are."""
        from .network_targets import Entity
        observer = self.tracker.observer
        if not self.settings:
            return
        # On top of every configured target (automatic map targets and checked names included), not
        # instead of them: replacing them left only the species list and nothing else was hunted.
        wanted = self.configured_species() | self.attacker_species(now)
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

    def active_map_combat(self):
        combat = getattr(self, 'map_combat', None)
        route = getattr(self.quests, 'route', None)
        database_combat = bool(self.quests.active and getattr(self.quests,'phase',None) == 'hunt'
                                and route and route.get('id') == 'database_hunt')
        if combat is None or self.quests.active and not database_combat or self.group_follower():
            return None
        from .map_behavior import map_key
        if (not self.tracker.observer.map_name or self.tracker.observer.map_name.lower().removesuffix('.gat') != self.map_combat_map
            or self.player_focus()):
            return None
        return combat

    def map_combat_intent(self, combat, state, now):
        collision = self.collision_map()
        self.hunt.refresh_wall_targets(state.get('recent_entities', []),collision,state.get('player_position'),now)
        def reachable(rows):
            rows = [e for e in rows if combat.distance(state,e) <= self.hunt.SEARCH_RADIUS
                    and self.hunt.excluded_until.get(e['entity_id'],0) <= now
                    and not self.hunt.walled(e['entity_id'],now)
                    and (not combat.no_chase(e.get('species_id')) or collision is None
                         or all(collision.line_clear(own,point) for own in (state.get('combat_player_positions') or [state['player_position']])
                                for point in (e.get('attack_positions') or [e.get('effective_position',e['position'])])))]
            return self.hunt.reachable_targets(rows,collision,state['player_position'],now)
        return combat.decide(state,self.rotation,now,current=self.hunt.target,reachable=reachable)

    def plan_map_rotation(self, state, now, target_id=None):
        combat = self.active_map_combat()
        if not combat and getattr(self,'map_combat',None) is not None:
            return None  # context changed: wait for the ordinary character rotation to be restored
        if not combat or not state.get('player_position'):
            return self.rotation.plan(state,now,target_id)
        intent = self.map_combat_intent(combat,state,now)
        if intent is None:
            # Still maintain buffs, but no offensive on an unreachable target.
            safe={**state,'visible_monsters':state.get('visible_monsters',state['recent_entities']),'recent_entities':[]}
            return combat.plan(safe,self.rotation,now,None)
        return combat.plan(state,self.rotation,now,target_id,intent=intent)

    def map_damage_allowed(self, identity, state, now, *, basic=False):
        combat = self.active_map_combat()
        if combat is None:
            return True
        if not state.get('player_position') or self.rotation is None:
            return False
        if basic and not combat.basic_allowed(identity,state):
            return False
        intent = self.map_combat_intent(combat,state,now)
        return bool(intent and intent['mode']=='kill' and intent['target_id']==identity)

    def plan_group_or_hunt(self, state, now, speed, collision):
        self.include_attackers(now)
        combat = self.active_map_combat()
        if combat and self.rotation is not None and state.get('player_position'):
            intent = self.map_combat_intent(combat,state,now)
            recent=state['recent_entities']
            candidates=combat.candidates(state,self.rotation,now)
            if intent and intent['mode']=='control':
                control_target=next((e for e in recent if e['entity_id']==intent['target_id']),None)
                if control_target is not None and all(e['entity_id']!=intent['target_id'] for e in candidates):
                    # A stunned/asleep Jounin can stop targeting us and leave the kill-candidate
                    # filter, but still needs to be followed into silence range.
                    candidates.append(control_target)
            state={**state,'recent_entities':candidates}
            if intent is None:
                state={**state,'recent_entities':[]}
                self.hunt.target=self.hunt.engaged=None
            self.hunt.target_priority = dict(combat.ranks)
            self.hunt.priority_target = intent['target_id'] if intent else None
            if intent and self.hunt.engaged != intent['target_id']:
                # Delayed damage from the previous fight must not override the map's current pick.
                self.hunt.engaged = None
            if intent and self.hunt.pending and self.hunt.pending.get('target_id') != intent['target_id']:
                self.hunt.pending = None
                self.hunt.ready_at = min(self.hunt.ready_at, now)
            if intent and self.hunt.target != intent['target_id']:
                self.hunt.engaged = None
                self.hunt.target = intent['target_id']
                self.hunt.approach_cache = None
            chosen=next((e for e in state['recent_entities'] if intent and e['entity_id']==intent['target_id']),None)
            limited_approach=combat.approach_nearby(chosen,state)
            if chosen and combat.no_chase(chosen['species_id']) and not limited_approach:
                old=(self.hunt.auto_movement,self.hunt.auto_attacks,self.hunt.melee_approach,self.hunt.kite)
                self.hunt.auto_movement=self.hunt.auto_attacks=self.hunt.melee_approach=self.hunt.kite=False
                try:return self.hunt.plan(state,now,speed,collision=collision)
                finally:
                    self.hunt.auto_movement,self.hunt.auto_attacks,self.hunt.melee_approach,self.hunt.kite=old
            if limited_approach:
                # Close Salamandras are acquired without requiring an earlier hit, but the
                # movement stops at a learned offensive skill's range and never follows farther.
                state={**state,'engagement_range':self.rotation.engagement_range(state)}
                old_melee,old_kite=self.hunt.melee_approach,self.hunt.kite
                self.hunt.melee_approach=self.hunt.kite=False
                try:return self.hunt.plan(state,now,speed,collision=collision)
                finally:self.hunt.melee_approach,self.hunt.kite=old_melee,old_kite
            if intent and intent['mode']=='control':
                pending=self.hunt.pending
                if pending and (pending['kind']!='move' or pending.get('target_id')!=intent['target_id']
                                or pending.get('control_skill_id')!=intent['skill_id']):
                    # A patrol/attack or the previous stun approach must not hold the urgent
                    # silence approach at the old destination or at the longer stun range.
                    self.hunt.pending=None
                    self.hunt.ready_at=min(self.hunt.ready_at,now)
                meta = next((s for s in state.get('learned_skills',[]) if s['skill_id']==intent['skill_id']),{})
                if meta.get('range',0)>0:
                    from .combat_rotation import configured_range
                    profile = next((p for p in self.rotation.profiles if p['skill_id']==intent['skill_id']),{})
                    state['engagement_range'] = max(0,configured_range(profile,meta)-combat.control_margin(intent['skill_id'],self.rotation,state))
                # Approach within the control skill range, not melee range. No damage before control.
                old_melee,old_kite=self.hunt.melee_approach,self.hunt.kite
                self.hunt.melee_approach=self.hunt.kite=False
                try:
                    action=self.hunt.plan(state,now,speed,collision=collision)
                finally:
                    self.hunt.melee_approach,self.hunt.kite=old_melee,old_kite
                if action and action['kind']=='move':
                    return {**action,'control_skill_id':intent['skill_id']}
                return None
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

    def map_monster_names_cached(self, player_id):
        """Monster names of the map for the panel: rebuilt once a second, not on every tick."""
        now = time.monotonic()
        cached = getattr(self, 'monster_names_cache', None)
        if cached is None or now-cached[0] >= 1 or cached[1] != player_id:
            from .map_monsters import confirmed_types
            cached = self.monster_names_cache = (now, player_id, list(confirmed_types(self.inventory, player_id, by_name=True).values()))
        return cached[2]

    def sync_presence_names(self):
        self.load_watchlist()
        from .network_targets import is_player_id
        names = {i: e['name'] for i, e in self.inventory.entities.items() if is_player_id(i) and e.get('name')}
        names.update(self.player_names)
        self.presence.remember_names(names)

    def announce_presence(self):
        """Known allowed characters get an informational notice, never a pause alert."""
        self.sync_presence_names()
        player = self.tracker.observer.player
        for alert in self.presence.drain_alerts():
            if self.observation_suspended_for_route():
                continue
            identity = alert['entity_id']
            if self.presence.observation_disabled_for(identity):
                continue
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
                                          walk_speed_ms=entity.get('walk_speed_ms'),
                                          owner_id=entity.get('owner_id'), summoned=entity.get('summoned', False))

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

    TRAIL_KEEP = 1800  # s: the walked trail of a map is started over after 30 minutes there

    def record_trail(self, now=None):
        """Walked cells of the current map only: cleared when the map is left and every 30 minutes."""
        name, player = self.tracker.observer.map_name, self.tracker.observer.player
        if not name or player is None:
            return
        now = time.monotonic() if now is None else now
        if set(self.trails)-{name}:
            self.trails = {name: self.trails.get(name, [])}  # another map's trail: gone on leaving it
            self.trail_started = {name: self.trail_started.get(name, now)}
        if now-self.trail_started.setdefault(name, now) >= self.TRAIL_KEEP:
            self.trails[name], self.trail_started[name] = [], now
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
        selected = self.configured_species()
        if self.hunt is not None and self.settings:
            selected |= self.attacker_species(time.monotonic())
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

    def configured_species(self):
        """Target sprites: the species list, the map's confirmed monsters (automatic targets) and
        every sprite with a checked name on the current map."""
        from .monster_db import map_key
        observer = self.tracker.observer
        selected = set((self.settings or {}).get('species', observer.species))
        if self.settings and self.settings['auto_map_targets']:
            selected.update(getattr(self, 'discovered_monsters', None) or {})
        current_map = map_key(observer.map_name)
        for key, enabled in (self.settings or {}).get('monster_name_choices', {}).items():
            map_id, _, rest = key.partition(':')
            species, _, name = rest.partition(':')
            if enabled and map_id == current_map and species.isascii() and species.isdecimal() and name:
                selected.add(int(species))
        return selected

    def dead(self, identity):
        """Killed (the server's death notice) or lying dead when it came into view: never a target
        until it is resurrected - a player's body stays on the ground in PvP."""
        entity = self.inventory.entities.get(identity)
        return bool(entity and entity.get('dead'))

    def monster_name_allowed(self, identity, species):
        from .monster_db import monster_choice_key
        from .monster_origin import excluded_spawn, temporary_reason

        entity = self.inventory.entities.get(identity) or {}
        if temporary_reason(entity) or excluded_spawn(species, self.tracker.observer.map_name, entity.get('name')):
            return False

        settings = self.settings or {}
        choices = settings.get('monster_name_choices', {})
        if not choices:
            return True
        prefix = monster_choice_key(self.tracker.observer.map_name, species, '')
        # Only a name left unchecked restricts this sprite: with every name of it checked (or none
        # chosen), it is attacked like before, without waiting for anything else.
        if not any(key.startswith(prefix) and not enabled for key, enabled in choices.items()):
            return True
        entity = self.inventory.entities.get(identity)
        from .network_targets import is_player_id
        from .monster_db import is_known_player
        # The name tells the monsters of one sprite apart; HP is not needed for that (some PCs never
        # receive it with the name, and then nothing was ever attacked).
        if (not entity or not entity.get('name') or is_player_id(identity) or is_known_player(entity['name'])
                or entity.get('owner_id') or entity.get('summoned')):
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
        try:
            request = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            # Read while the panel was replacing it (Windows refuses): try again next tick. Deleting it
            # lost the command, the panel waited forever and settings only applied after a relog.
            return
        identity = None
        try:
            identity = request['id']
            if self.control_result and identity == self.control_result['id']:
                return
            command = request['command']
            if command.startswith('quest_'):
                self.quest_control(command,request,game_gate)
            elif command == 'apply':
                self.apply_settings(request['settings'])
                if self.quests.active:
                    self.quest_hunt_id = None  # the route puts its own monsters back on its next tick
            elif command == 'pause':
                if self.quests.active:self.quest_stop('Fila pausada pelo painel')
                self.hunt.pause('pausada pelo painel')
            elif command == 'stop':
                if self.quests.active:self.quest_stop('Envios parados pelo painel')
                self.commands_blocked = True
                self.hunt.pause('parada pelo painel')
            elif command == 'start':
                if self.quests.recording:raise ValueError('Salve ou descarte a gravacao antes de iniciar a caca')
                self.mob_scan.reset_failures()
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
            elif command == 'loot_command':
                from .database_hunt import loot_command
                queue = self.__dict__.setdefault('loot_commands', [])
                if len(queue) >= 200:
                    raise ValueError('Muitos comandos de loot aguardando envio')
                queue.append(loot_command(request.get('text')))
            elif command == 'mob_info':
                species = int(request['species_id'])
                if species <= 0:
                    raise ValueError('ID de monstro invalido')
                self.mob_info.want(species, force=True)
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

    def collision_map(self):
        if self.map_repository is None:
            return None
        name = self.tracker.observer.map_name
        collision = self.map_repository.get(name)
        if collision is None and name and '@' in name:
            base = self.instance_base(name)
            collision = self.map_repository.get(base) if base else None
        if collision is not None:
            hazards=self.ground_hazards(time.monotonic())
            own=self.tracker.observer.player
            collision.cornered_by_hazards=bool(hazards and own is not None and self.cornered(collision,tuple(own),hazards))
            if collision.cornered_by_hazards:
                hazards=frozenset()  # boxed in by skill areas: routes may cross them
            collision.hazard_cells=hazards
            collision.set_forbidden(set(self.portals.cells(name))|set(hazards))
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

    def ground_hazards(self, now):
        settings=self.settings or {}
        return self.toxic_ground.cells(now,
            include_active=bool(settings.get('avoid_ground_effects', True)),
            include_forecasts=bool(settings.get('predict_ground_effects', True)))

    def crosses_ground_hazard(self, origin, destination, now):
        settings=self.settings or {}
        collision=self.collision_map()
        if collision is not None and getattr(collision,'cornered_by_hazards',False):
            return False  # cornered by skill areas (see cornered): crossing them is allowed
        return self.toxic_ground.crosses(origin,destination,now,
            include_active=bool(settings.get('avoid_ground_effects', True)),
            include_forecasts=bool(settings.get('predict_ground_effects', True)))

    CORNERED_CELLS = 40  # fewer free cells than this around the character, with areas closing it in

    def cornered(self, collision, origin, hazards):
        """Boxed in by skill areas on the floor (or standing in one with no free cell close by): the
        free ground reachable without crossing them is tiny. Bounded search, cached per area set."""
        key=(id(collision),origin,hazards)
        cached=getattr(self,'cornered_cache',None)
        if cached and cached[0]==key:return cached[1]
        from collections import deque
        portals=set(self.portals.cells(self.tracker.observer.map_name))
        def free(p):return collision.ground(p) and p not in hazards and p not in portals
        starts=[origin] if free(origin) else [
            (origin[0]+dx,origin[1]+dy) for dx in range(-2,3) for dy in range(-2,3) if free((origin[0]+dx,origin[1]+dy))]
        seen=set(starts);queue=deque(starts)
        while queue and len(seen)<self.CORNERED_CELLS:
            x,y=queue.popleft()
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
                n=(x+dx,y+dy)
                if n not in seen and free(n):
                    seen.add(n);queue.append(n)
        result=len(seen)<self.CORNERED_CELLS
        self.cornered_cache=(key,result)
        return result

    def server_collision_map(self):
        # Hazard avoidance must not distort prediction of paths the server actually walks.
        collision=self.collision_map()
        if collision is None or not getattr(collision,'hazard_cells',None):return collision
        forbidden=frozenset(collision.forbidden)-collision.hazard_cells
        key=(id(collision),forbidden)
        cached=getattr(self,'physical_collision_cache',None)
        if cached and cached[0]==key:return cached[1]
        from .map_navigation import CollisionMap
        physical=CollisionMap(collision.width,collision.height,collision.cells)
        physical.set_forbidden(forbidden)
        self.physical_collision_cache=(key,physical)
        return physical

    async def avoid_toxic_ground(self, game_gate):
        now=time.monotonic();o=self.tracker.observer
        if (not self.allow_commands or self.commands_blocked or self.upstream is None or not game_gate()
            or not self.native_frames.ready or not o.player_alive or o.player_id is None or not o.player_position_valid(now)
            or not (self.quests.active or self.hunt is not None and self.hunt.enabled)
            or self.manual_control(now)):
            return False
        if not self.observation_suspended_for_route() and self.presence.reason(o.player,now):return False
        if now<self.toxic_hold_until:return True
        hazards=self.ground_hazards(now)
        if not hazards:return False
        positions=o.combat_positions(now)
        origin=tuple(positions[0] if positions else o.player)
        motion=o.player_motion
        threatened=(origin in hazards or any(tuple(p) in hazards for p in positions))
        crossing=bool(motion and self.walking_now() and self.crosses_ground_hazard(origin,motion['destination'],now))
        if not threatened and not crossing:return False
        async with self.send_lock:
            if self.commands_blocked or not game_gate() or not self.native_frames.ready:return False
            now=time.monotonic();hazards=self.ground_hazards(now)
            positions=o.combat_positions(now);origin=tuple(positions[0] if positions else o.player)
            motion=o.player_motion
            if (not any(tuple(p) in hazards for p in positions)
                and not (motion and self.walking_now() and self.crosses_ground_hazard(origin,motion['destination'],now))):
                return False
            collision=self.collision_map()
            blocked={p for p,t in self.hunt.blocked_until.items() if t>now} if self.hunt else set()
            destination=self.toxic_ground.escape(collision,origin,blocked,now,
                include_active=bool((self.settings or {}).get('avoid_ground_effects',True)),
                include_forecasts=bool((self.settings or {}).get('predict_ground_effects',True))) if collision is not None and origin in hazards else None
            if origin in hazards and destination is None:
                # No way out at all: holding still here kept the character idle for as long as the
                # area lasted. The hunt goes on, walking over the area if it has to.
                if self.hunt:self.hunt.reason='area de habilidade no chao sem saida: atravessando'
                return False
            destination=destination or origin  # stop an already sent path before it enters the cloud
            payload=move(*destination)
            self.trace_map_send('bot',struct.unpack_from('<H',payload)[0],len(payload))
            self.upstream.write(payload);await self.upstream.drain()
            self.toxic_hold_until=now+.18
            if self.hunt:
                self.hunt.pending=None;self.hunt.approach_cache=None;self.hunt.ready_at=now
                self.hunt.reason='desviando da nevoa toxica'
            if self.quests.pending and self.quests.pending.get('kind')=='move':self.quests.pending=None
            self.quests.path_cache=None
            self.record_hunt({'kind':'toxic_ground_escape' if destination!=origin else 'toxic_ground_stop',
                              'origin':list(origin),'destination':list(destination)})
        return True

    def instance_base(self, name):
        """The map an instance copy uses (0045@tower -> 5@tower): the game names copies by instance
        number, the files keep N@map. Several floors share the suffix, so the one where the
        character and the units around stand on walkable ground is taken."""
        if name in self.instance_maps:
            return self.instance_maps[name]
        own = self.tracker.observer.player
        if own is None:
            return None
        suffix = name[name.index('@'):]
        points = [tuple(own)]+[tuple(e['position']) for e in self.inventory.entities.values()
                               if e.get('present_last_observation') and e.get('position')][:40]
        best = None
        for floor in range(1, 10):
            candidate = f'{floor}{suffix}'
            if candidate.lower() == name.lower():
                continue
            try:
                collision = self.map_repository.get(candidate)
            except (OSError, ValueError):
                collision = None
            if collision is None or not collision.walkable(tuple(own)):
                continue
            score = sum(collision.walkable(p) for p in points)/len(points)
            if score >= .9 and (best is None or score > best[0]):
                best = (score, candidate)
        if best is None:
            return None
        self.instance_maps[name] = best[1]
        print(f'Instancia {name}: usando a colisao de {best[1]} ({best[0]:.0%} das posicoes conferem).')
        return best[1]

    def record_hunt(self, event):
        self.note_skill_result(event)
        # Kept open: opening the file for each of the ~20 events a second cost ~5% of the relay.
        log, path = getattr(self, 'hunt_log_file', None), self.folder/'caca_eventos.jsonl'
        if log is None or log.closed or getattr(self, 'hunt_log_path', None) != path:
            if log is not None and not log.closed:
                log.close()
            log = self.hunt_log_file = path.open('a', encoding='utf-8')
            self.hunt_log_path = path
        log.write(json.dumps({'time': datetime.now().isoformat(), **event}, ensure_ascii=False)+'\n')
        log.flush()

    SKILL_FAIL_WINDOW = 2.0  # s of damage skills on one target without any confirmed hit
    SKILL_FAIL_SENDS = 6
    SKILL_FAIL_GAP = .6  # s: a longer pause between sends (manual control, a fight elsewhere) starts over
    SKILL_FAIL_RETURN = 1.0  # s before that target is taken again

    def note_skill_result(self, event):
        """Offensive skills sent and hits confirmed per target, for skill_failure_switch."""
        kind = event.get('kind')
        if kind == 'rotation_skill_sent' and event.get('role') == 'offensive':
            combat = self.active_map_combat() if hasattr(self, 'active_map_combat') else None
            if combat is not None and event.get('skill_id') in combat.control_skill_ids:
                return  # stun/sleep/silence: control, not damage; their own retries apply
            now, target = time.monotonic(), event.get('target_id')
            track = getattr(self, 'skill_fail_track', None)
            if track is None or track[0] != target or now-track[3] > self.SKILL_FAIL_GAP:
                track = [target, now, 0, now]
            track[2] += 1
            track[3] = now
            self.skill_fail_track = track
        elif kind in ('rotation_skill_confirmed', 'attack_confirmed', 'rotation_control_confirmed'):
            track = getattr(self, 'skill_fail_track', None)
            if track is not None and track[0] == event.get('target_id'):
                self.skill_fail_track = None

    def skill_failure_switch(self, state, now):
        """Many offensive skills on one target and none taking: go for the next monster close by now,
        and back to this one a second later."""
        track = getattr(self, 'skill_fail_track', None)
        hunt = self.hunt
        if (track is None or hunt is None or track[0] != hunt.target or track[2] < self.SKILL_FAIL_SENDS
                or now-track[1] < self.SKILL_FAIL_WINDOW or now-track[3] > self.SKILL_FAIL_GAP
                or (self.manual_active and now < self.manual_until)):
            return False
        target = track[0]
        own = state.get('player_position')
        others = [e for e in state.get('recent_entities', []) if e['entity_id'] != target
                  and hunt.excluded_until.get(e['entity_id'], 0) <= now and not hunt.walled(e['entity_id'], now)
                  and own is not None and math.dist(own, e.get('effective_position', e['position'])) <= hunt.SEARCH_RADIUS]
        self.skill_fail_track = None
        if not others:
            return False  # alone: keep at it (the approach moves closer when out of reach)
        hunt.excluded_until[target] = now+self.SKILL_FAIL_RETURN
        if hunt.engaged == target:
            hunt.engaged = None
        hunt.target = hunt.pending = None
        hunt.approach_cache = None
        self.record_hunt({'kind': 'target_switched_skill_failures', 'target_id': target,
                          'seconds': round(now-track[1], 2), 'skills_sent': track[2]})
        return True

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

    def mob_info_observe(self, events, now):
        """Monsters seen get their server sheet (@mi) once; answers go to the drop database."""
        from .map_monsters import is_confirmed_monster
        from .monster_origin import excluded_spawn
        queue = self.mob_info
        queue.observe(events, now)
        for event in events:
            if event['kind'] == 'name':
                entity = self.inventory.entities.get(event.get('entity_id'))
                if (entity and is_confirmed_monster(entity, self.tracker.observer.player_id)
                        and not excluded_spawn(entity['species_id'], self.inventory.map_name, entity.get('name'))):
                    queue.want(entity['species_id'])
        while queue.results:
            species, info, lines = queue.results.pop(0)
            try:
                with (self.folder/'respostas_mi.jsonl').open('a', encoding='utf-8') as log:
                    log.write(json.dumps({'at': datetime.now().isoformat(), 'species_id': species,
                                          'recognized': info is not None, 'lines': lines}, ensure_ascii=False)+'\n')
            except OSError:
                pass
            if info is None:
                print(f'[DROPS] @mi {species}: resposta nao reconhecida ({len(lines)} linha(s)): '
                      + (' | '.join(lines[:3]) or 'nenhuma resposta do servidor'))
                if queue.suspended:
                    print('[DROPS] Consultas @mi automaticas suspensas nesta sessao; use "Consultar @mi" na Database.')
                continue
            try:
                from .drop_db import save_mob_info
                save_mob_info(species, info, lines)
                print(f"[DROPS] @mi {species} ({info['name']}): {len(info['drops'])} drop(s)"
                      + (f", {len(info['mvp'])} MVP" if info['mvp'] else '') + ' salvos na Database.')
            except (sqlite3.Error, OSError) as exc:
                print(f'[DROPS] @mi {species}: nao foi possivel salvar ({exc})')

    LOOT_GAP = 1.2  # s between two loot commands: the server's chat flood guard

    async def send_loot_commands(self, *, game_gate):
        """@alootid / @autoloot chosen in the hunt window, one at a time."""
        queue = self.__dict__.get('loot_commands')
        now = time.monotonic()
        name = (self.own_look or {}).get('name')
        if (not queue or not name or not self.allow_commands or self.login_phase != 'map'
                or now-self.__dict__.get('loot_sent_at', -1e9) < self.LOOT_GAP):
            return
        from .mob_info import chat_command
        payload = chat_command(queue[0], name)
        if self.native_frames.fallback().get(0xf3) not in (-1, len(payload)):
            print('[LOOT] Pacote de chat 00F3 nao validado para este cliente; comando nao enviado: '+queue.pop(0))
            return
        async with self.send_lock:
            if not self.native_frames.ready or not game_gate() or self.upstream is None:
                return
            text = queue.pop(0)
            self.loot_sent_at = now
            self.trace_map_send('bot', 0xf3, len(payload))
            self.upstream.write(payload)
            await self.upstream.drain()
            print('[LOOT] Enviado: '+text)

    async def send_mob_info(self, *, game_gate):
        now = time.monotonic()
        species = self.mob_info.due(now)
        name = (self.own_look or {}).get('name')
        if (species is None or not name or not self.allow_commands or self.login_phase != 'map'
                or not self.tracker.observer.player_position_valid(now)):
            return
        from .mob_info import chat_command
        payload = chat_command(f'@mi {species}', name)
        if self.native_frames.fallback().get(0xf3) not in (-1, len(payload)):
            self.mob_info.suspended = True; self.mob_info.queue.clear()
            print('[DROPS] Pacote de chat 00F3 nao validado para este cliente; @mi desativado.')
            return
        async with self.send_lock:
            if not self.native_frames.ready or not game_gate() or self.upstream is None:
                return
            self.mob_info.sent(species, now)
            self.trace_map_send('bot', 0xf3, len(payload))
            self.upstream.write(payload)
            await self.upstream.drain()

    def quest_missing_species(self):
        """Monsters the quest still needs on its hunting map (finished counters left out)."""
        q = self.quests
        route = q.route or {}
        if route.get('id') == 'database_hunt':
            return sorted(route.get('showmobs_species') or [])  # only the monsters marked "usar @showmobs"
        targets = route.get('kill_targets') or []
        if not targets:
            return sorted(route.get('species', []))
        return sorted({s for target, progress in zip(targets, q.progress()) if not progress['complete']
                       for s in target['species']})

    async def send_mob_scan(self, *, game_gate):
        """From time to time in the quest hunt: @showmobs of each missing monster, then the densest spot."""
        if not self.mob_scan.AUTOMATIC_ENABLED:
            if not getattr(self,'automatic_scan_stopped',False):
                self.mob_scan.reset()  # invalidates results from an already-running background job
                self.automatic_scan_stopped=True
            patrol=self.hunt.patrol if self.hunt is not None else None
            if patrol is not None and patrol.focus is not None:
                patrol.focus=patrol.goal=patrol.goal_block=None
                patrol.focus_key=patrol.focus_block=None
                patrol.route_cache_key=patrol.route_cache=None
                if self.hunt.pending and self.hunt.pending.get('purpose')=='patrol':self.hunt.pending=None
            self.scan_no_target_since=None
            return
        self.automatic_scan_stopped=False
        from .portals import PortalGuard
        q, observer, now = self.quests, self.tracker.observer, time.monotonic()
        if (not q.active or q.phase != 'hunt' or q.errands or self.hunt is None or not self.hunt.enabled
                or not observer.map_name or PortalGuard.key(observer.map_name) != PortalGuard.key(q.route['target_map'])):
            return
        # Every 60 s, fighting or not; and early after 10 s with no quest target in sight (unless the
        # scheduled scan is within 15 s), so a dry spot is left quickly for where the monsters are.
        if self.hunt.target is not None:
            self.scan_no_target_since = None
        elif getattr(self, 'scan_no_target_since', None) is None:
            self.scan_no_target_since = now
        early = (getattr(self, 'scan_no_target_since', None) is not None
                 and now-self.scan_no_target_since >= 10)
        self.mob_scan.start(observer.map_name, self.quest_missing_species(), now, idle=True, early=early)
        self.mob_scan.include_cached(self.viewpoint_marks, now, self.VIEWPOINT_TTL,
                                     self.quest_missing_species())
        collision = self.collision_map()
        found = self.mob_scan.poll_finish(observer.player, now, collision=collision)
        if found:
            self.record_hunt({'kind': 'showmobs_goal', 'calculation_ms': self.mob_scan.last_calculation_ms, **found})
            print(f"[ROTA] @showmobs: indo onde ha mais monstros da quest ({found['monsters']} de {found['total']} "
                  f"perto de {found['position']}, a {found.get('walk_cells')} celulas; soma por tipo: {found.get('species_counts',{})}).")
        elif self.mob_scan.map_failed(observer.map_name) and getattr(self, 'mob_scan_failed_note', None) != observer.map_name:
            self.mob_scan_failed_note = observer.map_name
            self.record_hunt({'kind': 'showmobs_failed', 'map': observer.map_name})
            print(f'[ROTA] @showmobs sem resultado em {observer.map_name}: percorrendo o mapa inteiro em linha; '
                  'continuarei consultando periodicamente para localizar a maior concentracao.')
        elif self.mob_scan.suspended and not getattr(self, 'mob_scan_warned', False):
            self.mob_scan_warned = True
            print('[ROTA] @showmobs ainda sem resposta apos 3 rodadas; continuarei tentando no intervalo normal e quando ficar sem alvo.')
        species = self.mob_scan.next_command(now)
        name = (self.own_look or {}).get('name')
        if (species is None or not name or not self.allow_commands or self.commands_blocked
                or self.login_phase != 'map' or not observer.player_position_valid(now)):
            return
        from .mob_info import chat_command
        payload = chat_command(f'@showmobs {species}', name)
        if self.native_frames.fallback().get(0xf3) not in (-1, len(payload)):
            return
        async with self.send_lock:
            if not self.native_frames.ready or not game_gate() or self.upstream is None:
                return
            self.mob_scan.sent(species, now)
            self.trace_map_send('bot', 0xf3, len(payload))
            self.upstream.write(payload)
            await self.upstream.drain()

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
            if self.plan_map_rotation(state, now, self.hunt.target) != action:
                return False
            observer = self.tracker.observer
            if not observer.player_alive or observer.player_id is None:
                return False
            collision = self.collision_map()
            if self.settings and self.hunt.auto_movement and self.settings['require_collision'] and collision is None:
                raise ValueError('Mapa de colisão deixou de estar disponível')
            if self.group_follower() and (not self.group_combat_allowed() or action['role'] in ('offensive','summon') and not self.group_combat_allowed(action.get('combat_target_id',action['target_id']))):
                return False
            if action.get('idle_summon'):
                combat=self.active_map_combat()
                if (action['role']!='summon' or combat is None
                    or action['skill_id']!=combat.config.get('idle_summon',{}).get('skill_id') or not combat.idle_clear(state)):
                    return False
            elif action['role'] == 'summon' and action.get('combat_target_id') is None:
                return False  # summons only with a monster to fight
            elif action['role'] in ('offensive', 'summon'):
                entity = observer.registry.entities.get(action.get('combat_target_id', action['target_id']))
                if (entity is None or not entity.alive or not observer.registry.current(entity, now)
                    or (entity.kind == 'player' and not self.player_target_allowed(entity.entity_id))
                    or (entity.kind == 'monster' and (entity.species_id not in observer.species
                    or not self.monster_name_allowed(entity.entity_id, entity.species_id)))
                    or self.dead(entity.entity_id)):
                    return False
                if action['role'] == 'summon' and (entity.kind != 'monster' or max(math.dist(own, p) for own in observer.combat_positions(now) for p in entity.combat_bounds(now)[0]) > 12):
                    return False
                if collision is not None and action['role'] == 'offensive':
                    # Ground-skill/portal reservations constrain walking, not shooting. Keep
                    # actual walls in the final range/line check without treating poison as one.
                    attack_collision=collision.plain()
                    bounds, _ = entity.combat_bounds(now)
                    if (entity.destination is not None and not entity.position_bounds(now)[1]
                        and not attack_collision.line_clear([entity.x, entity.y], entity.destination)):
                        self.rotation.reason = 'movimento estimado contorna obstaculo; aguardando posicao segura'
                        return False
                    if not all(attack_collision.line_clear(own, point) for own in observer.combat_positions(now) for point in bounds):
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
                    self.ground_cells.request_cast(action['skill_id'],list(point),now)
                    self.publish_ground_cells()
                    action = {**action, 'ground_position': list(point)}
                else:
                    payload = skill(action['target_id'], action['skill_id'], action['level'])
                    if self.preview_rcx_self_skill(action['skill_id'],action['target_id'],now):
                        self.publish_ground_cells()
                self.rotation.sent(action, now)
            try:
                self.trace_map_send('bot', struct.unpack_from('<H', payload)[0], len(payload))
                self.upstream.write(payload)
                await self.upstream.drain()
            except OSError:
                self.hunt.pause('envio de rotação falhou ou ficou incerto')
                raise
            combat = self.active_map_combat()
            if combat and action['kind']=='skill':
                combat.sent(action,now)
            if action.get('role') == 'offensive':
                self.note_player_attack(action.get('combat_target_id') or action['target_id'], now)
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
                self.npc_transports.save()
                self.npc_map.save()
                self.registry.save()
            except OSError as error:
                print(f'Registro de jogadores nao salvo: {error}')
        if self.last_test is not None and self.last_test['status'] == 'sent_waiting_response' and time.monotonic() >= self.test_deadline:
            self.last_test['status'] = 'no_confirmation'
            self.record_test()
            print('O ataque de teste foi enviado, mas não houve confirmação de dano no prazo. Não repetirei automaticamente.')
        state = self.tracker.snapshot(time.monotonic())
        hp_observations=self.received_player_hp.snapshot(self.tracker.observer.player_id,self.registry.players,
                            {**self.own_look,**self.rcx_sides.guild},party_ids=self.rcx_sides.party)
        state['received_player_hp']=hp_observations
        if time.monotonic()-getattr(self,'hp_diagnostic_saved',0)>1:
            self.hp_diagnostic_saved=time.monotonic()
            try:
                (self.folder/'hp_recebido.json').write_text(json.dumps(hp_observations,ensure_ascii=False,indent=2),encoding='utf-8')
            except OSError:pass
        if self.hunt is not None and self.hunt.patrol is not None and state.get('player_position_recent'):
            self.hunt.patrol.observe_position(state.get('player_position'),time.monotonic(),self.tracker.observer.map_name)
        state.update(login_phase=self.login_phase)
        # Map behaviors such as low-HP Namekuji must use server-reported vitals.
        state.update(player_hp=self.tracker.observer.hp,
                     player_max_hp=self.tracker.observer.max_hp)
        state['drop_database'] = {'collecting': self.drops.error is None, 'error': self.drops.error}
        state['recent_entities'] = [entity for entity in state['recent_entities']
                                   if (entity.get('kind') == 'player' or self.monster_name_allowed(
                                       entity['entity_id'], entity.get('species_id')))
                                   and not self.dead(entity['entity_id'])]
        for row in state['recent_entities']:
            received = self.inventory.entities.get(row['entity_id'], {})
            row['body_state'] = received.get('body_state',0)
            row['health_state'] = received.get('health_state',0)
        combat = self.active_map_combat()
        if combat and combat.config.get('idle_summon'):
            from .map_monsters import is_confirmed_monster
            visible={e['entity_id']:e for e in state['recent_entities'] if e.get('kind','monster')=='monster'}
            state['visible_monsters']=[visible.get(e['entity_id'],dict(entity_id=e['entity_id'],species_id=e['species_id'],
                kind='monster',position=e['position'],destination=e.get('destination')))
                for e in self.inventory.entities.values() if e.get('present_last_observation') and not e.get('dead')
                and is_confirmed_monster(e,self.tracker.observer.player_id)]
            state.update(idle_summon_skill_id=combat.config['idle_summon']['skill_id'],idle_summon_clear=combat.idle_clear(state))
        state['map_combat'] = {'active':combat is not None,'reason':combat.reason if combat else None}
        state['toxic_ground']={'blocked_cells':len(self.ground_hazards(time.monotonic())),
            'predicted_casts':len(self.toxic_ground.forecasts)}
        state['player_focus'] = self.player_focus()
        if state['player_focus']:
            # A player focused with the mouse (or given priority in PvP): monsters and summons are
            # ignored, attackers included; only players are fought until the focus ends.
            state['recent_entities'] = [entity for entity in state['recent_entities'] if entity.get('kind') == 'player']
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
                     observation_suspended_for_route=self.observation_suspended_for_route(),
                     presence=self.presence.snapshot(self.tracker.observer.player, time.monotonic()),
                     players_nearby=self.players_nearby(), captured_player=self.captured_player,
                     capture_armed=time.monotonic() < self.capture_armed_until,
                     own_motion=self.own_motion(), clock_now=time.monotonic(),
                     own_look=self.own_look or None,
                     emergency_stop=self.emergency,
                     chat_alert=self.chat_alert,
                     ground_cells={**self.rcx_ground_snapshot(), "feed_file": str(self.folder/"rcx_terreno.json"), "feed_ipc": str(self.folder/"rcx_terreno.ipc")},
                     portals=[{'position': list(cell), 'margin': margin,
                               'to': (self.portals.destination(self.tracker.observer.map_name, cell) or {}).get('map')}
                              for cell, margin in self.portals.portals(self.tracker.observer.map_name)],
                     npcs=self.npc_map.for_map(self.tracker.observer.map_name),
                     viewpoint_marks=self.current_viewpoint_marks(),
                     own_hidden=({'option': self.own_option & 0x4046, 'gm_invisible': bool(self.own_option & 0x40)}
                                 if self.own_option & 0x4046 else None),
                     native_frame_error=self.native_frames.error,
                     client_vision=(self.client_vision.diagnostic() if getattr(self,'client_vision',None) else None),
                     map_monsters=list(self.discovered_monsters.values()),
                     map_monster_names=self.map_monster_names_cached(observer.player_id),
                     buff_candidates=dict(self.buff_candidates), buff_learning_result=self.buff_learning_result,
                     map_validation=self.map_validation,
                     control_result=self.control_result, settings=self.settings,
                     map_name=self.tracker.observer.map_name,
                     command_sending_enabled=self.allow_commands and not self.commands_blocked and not self.single_attack_used,
                     last_attack_test=self.last_test,
                     upstream_connected=self.upstream is not None,
                     updated_at=datetime.now().isoformat())
        if self.hunt is not None:
            scan = self.mob_scan.current_goal(observer.player, time.monotonic()) if self.quests.active and self.mob_scan.AUTOMATIC_ENABLED else None
            state['showmobs_goal'] = {'position': scan} if scan else None
            state['showmobs_failed'] = bool(self.mob_scan.AUTOMATIC_ENABLED and self.quests.active and self.mob_scan.map_failed(observer.map_name))
            state['showmobs_suspended'] = not self.mob_scan.AUTOMATIC_ENABLED
            scan_job = getattr(self.mob_scan, '_finish_job', None)
            state['showmobs_calculation'] = {'running': bool(scan_job and not scan_job['task'].done()),
                'last_ms': self.mob_scan.last_calculation_ms, 'error': self.mob_scan.calculation_error}
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
                temp.write_text(json.dumps(state, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
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
            self.received_player_hp.observe(events,self.tracker.observer.map_name)
            rcx_changed=False
            rcx_now=time.monotonic()
            for event in events:
                ground_event=event
                if event['kind']=='skill_cast' and event.get('source_id')!=self.tracker.observer.player_id and event.get('target_id')==event.get('source_id'):
                    track=self.player_tracks.get(event.get('source_id'))
                    entity=self.inventory.entities.get(event.get('source_id'),{})
                    position=track.combat_bounds(rcx_now)[0][0] if track is not None else entity.get('position')
                    if position is not None:ground_event={**event,'position':[round(v) for v in position]}
                self.ground_cells.observe([ground_event],self.tracker.observer.player_id,rcx_now)
                if event['kind'] in ('skill_cast','skill_no_damage','skill_damage') and event.get('source_id')==self.tracker.observer.player_id:
                    if event['kind']=='skill_no_damage' and not event.get('success'):continue
                    if event['kind']=='skill_cast' and event.get('duration_ms',0)<=0:continue
                    rcx_changed=self.preview_rcx_self_skill(event.get('skill_id'),self.tracker.observer.player_id,rcx_now,
                        duration=event.get('duration_ms',0)/1000 if event['kind']=='skill_cast' else .2,confirmed=True) or rcx_changed
            self.toxic_ground.observe(events,self.inventory,rcx_now,self.ground_cells,
                                      own_id=self.tracker.observer.player_id)
            for note in self.ground_cells.trace:
                self.record_hunt(note)  # which spell gave each RCX area (or none): checkable later
            self.ground_cells.trace.clear()
            if self.ground_cells.map is None:
                self.ground_cells.map = self.tracker.observer.map_name
            if rcx_changed or any(e["kind"] in ("ground_effect", "ground_effect_removed", "map_change", "map_transfer", "skill_cast", "skill_failed", "ground_skill", "skill_cast_cancel") for e in events):
                self.publish_ground_cells()
            if self.ground_cells.map is None:
                self.ground_cells.map = self.tracker.observer.map_name
            if any(e['kind'] == 'player_position_init' for e in events):
                self.login_phase = 'map'
                self.native_feed = True  # the server accepted this map connection: frames align from here
            self.observe_own_summons(events, time.monotonic())
            self.npc_transports.observe(events,self.tracker.observer.map_name)
            self.quests.observe(events,self.tracker.observer.player_id,self.tracker.observer.map_name,time.monotonic())
            self.bg_observe(events)
            self.flush_quest_kills()
            self.quest_events(events,time.monotonic())
            for transition in events:
                if transition['kind'] in ('map_change','map_transfer') and transition.get('map'):
                    self.next_map=transition['map']
            self.mirror_sequence += len(data)
            self.inventory.observe(events, time.monotonic())
            combat = getattr(self, 'map_combat', None)
            if combat:
                combat.observe(events,self.tracker.observer.player_id,time.monotonic())
            try:
                self.drops.observe(events, self.tracker.observer.player_id, time.monotonic(),
                                   self.inventory.map_name or self.tracker.observer.map_name)
            except (sqlite3.Error, OSError, ValueError, KeyError, TypeError) as exc:
                if self.drops.error is None:
                    self.drops.error = str(exc)
                    self.drops.close()
                    print('Database de drops indisponivel; jogo e combate continuam: '+str(exc))
            self.mob_info_observe(events, time.monotonic())
            self.mob_scan.observe(events, time.monotonic())
            self.observe_viewpoints(events, time.monotonic())
            from .monster_origin import temporary_reason
            if getattr(self, 'origin_epoch', None) != self.inventory.epoch:
                self.origin_epoch = self.inventory.epoch
                self.origin_notified = set()
            for event in events:
                if event['kind'] not in ('appearance', 'name'):
                    continue
                entity = self.inventory.entities.get(event.get('entity_id')) or {}
                note = temporary_reason(entity)
                identity = entity.get('entity_id')
                if note and identity not in self.origin_notified:
                    self.origin_notified.add(identity)
                    print(f'[INFO] {note} | ID {identity} | celula {entity.get("position")}')
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
            if any(e['kind'] in ('map_change', 'map_transfer') for e in events):
                self.map_changed_at = time.monotonic()
            self.check_recall(events, time.monotonic())
            if self.portals.observe(events, self.tracker.observer.map_name, self.tracker.observer.player,
                                    (self.tracker.observer.player_motion or {}).get('destination')):
                self.collision_map()  # apply the new portal area right away
            touched = {e.get('entity_id') for e in events if e['kind'] in ('appearance', 'name')}
            if touched:
                self.npc_map.observe([self.inventory.entities[i] for i in touched if i in self.inventory.entities],
                                     self.inventory.map_name or self.tracker.observer.map_name)
            self.registry.observe(events, self.tracker.observer.player_id,
                                  self.inventory.map_name or self.tracker.observer.map_name)
            affiliation_changed=self.observe_rcx_affiliation(events)
            if affiliation_changed or any(e['kind']=='name' and any(k in e for k in ('guild','guild_id')) for e in events):
                self.publish_ground_cells()
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
            self.observe_chat_alerts(events)
            self.check_emergency()
            self.record_damage_taken(events)
            for event in events:
                if event['kind'] == 'stream_resync':
                    self.record_hunt(event)
                    print(f"Mensagem do servidor nao reconhecida ({event['opcode']}, {event['dropped']} bytes); leitura ressincronizada sem pausar.")
            if any(e['kind'] in ('appearance', 'name', 'remove', 'map_change', 'map_transfer') for e in events):
                self.sync_map_monsters()
            for event in events:
                if event['kind'] == 'server_disconnect':
                    self.login_phase = 'failed' if event['reason_raw'] else 'disconnected'
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
                    self.begin_hunt_transfer()
                before = self.hunt.confirmed_attacks
                for event in events:  # damage taken: that player can be fought here
                    if (event['kind'] in ('skill_damage', 'normal_attack') and event.get('source_id') == self.tracker.observer.player_id
                            and event.get('target_id') in self.player_misses):
                        self.player_misses.pop(event['target_id'], None)
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
            self.rcx_sides.reset()
        self.character_id = identity

    def begin_map_observation(self):
        self.received_player_hp.rows.clear()
        self.ground_cells.reset()
        self.publish_ground_cells()
        self.drops.reset()
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

    MAP_LOAD_LIMIT = 6.0  # without the client's "map loaded" (007D) the bot waits at most this long

    def map_loading(self, now):
        """True between a map change and the client's 007D: the server drops what the bot sends
        then (equip, walk, skills), and each lost request cost a timeout of seconds after a portal."""
        changed = getattr(self, 'map_changed_at', None)
        if changed is None or now-changed >= self.MAP_LOAD_LIMIT:
            return False
        loaded = getattr(self, 'map_loaded_at', None)
        return loaded is None or loaded < changed

    def check_recall(self, events, now):
        """Stop everything when the server moves the character while the bot acts (GM @recall)."""
        from .portals import PortalGuard
        map_event = any(e['kind'] in ('map_change', 'map_transfer') for e in events)
        pending = getattr(self, 'recall_candidate', None)
        if not map_event and pending is None:
            return False
        q = self.quests
        # The death workflow takes ownership of map changes immediately after it observes
        # the death. Clear any provisional recall while it plans the return route.
        if (self.tracker.observer.player_alive is False
                or getattr(self, 'revive', None) is not None
                or getattr(self, 'hunt_revive', None) is not None):
            self.recall_candidate = None
            return False
        if pending is not None:
            if not self.tracker.observer.player_alive:
                self.recall_candidate = None
                return False  # delayed death signal: let the revive workflow take over
            if now-pending['at'] < 2.0:
                return False
            current_map = self.tracker.observer.map_name
            if current_map and PortalGuard.key(current_map) != PortalGuard.key(pending['info']['to_map']):
                self.recall_candidate = None
                return False  # another expected transition superseded this candidate
        hunting = self.hunt is not None and self.hunt.enabled
        if not (hunting or q.active):
            return False
        # A death return (B2) is a server-side map transfer without a portal. The death
        # watcher owns the subsequent trip back to the hunt; don't classify it as @recall.
        if q.active and (q.phase != 'hunt' or q.errands or now-q.voltar_sent_at < 20):
            return False  # route travel, NPC warps and @voltar change maps on purpose
        if q.recording or self.manual_active or now < self.manual_until+5:
            return False  # the player is moving the character
        from .recall_guard import unexpected_teleport
        info = pending['info'] if pending is not None else unexpected_teleport(
            events, self.portals.map_name, self.portals.last_own, self.portals)
        if info is None:
            return False
        if self.walked_into_portal(info):
            self.recall_candidate = None
            return False
        if pending is None and PortalGuard.key(info['from_map']) != PortalGuard.key(info['to_map']):
            # Death returns and legitimate server transfers can arrive before the HP/death
            # packet. Give the observer two seconds to confirm a death; same-map recalls
            # remain immediate, and unexplained live transfers still stop safely afterward.
            self.recall_candidate = {'info': info, 'at': now}
            return False
        reason = (f"teletransporte sem portal ({info['from_map']} {info['origin']} -> "
                  f"{info['to_map']} {info['position']}): possivel recall de GM")
        if q.active:
            self.quest_stop('Parada por seguranca: '+reason)
        if self.hunt is not None:
            self.hunt.pause('parada por seguranca: '+reason)
        self.commands_blocked = True
        self.recall_candidate = None
        self.record_hunt({'kind': 'recall_detected', **info})
        print('[ALERTA] Bot parado por seguranca: '+reason+'. Nenhum comando sera enviado ate voce iniciar de novo.')
        return True

    def walked_into_portal(self, info):
        """The move in flight passed by a known portal: the bot stepped into it (its area is wider
        than learned, gl_sew02 2026-11-05). The area grows so it never happens again; not a recall."""
        pending = self.hunt.pending if self.hunt is not None else None
        if not pending or pending.get('kind') != 'move' or not info.get('origin'):
            return False
        origin = pending.get('origin') or info['origin']  # info's origin is already the move's end
        destination = pending.get('destination') or origin
        from .map_navigation import server_line
        path = [list(origin)]+[list(cell) for cell in server_line(tuple(origin), tuple(destination))]
        widened = self.portals.widen(info['from_map'], path)
        if widened is None:
            return False
        cell, margin = widened
        self.portals.save()
        self.record_hunt({'kind': 'portal_stepped_in', **info, 'portal': list(cell), 'margin': margin})
        print(f"[ALERTA] O personagem entrou sem querer no portal {list(cell)} de {info['from_map']}; "
              f"area dele aumentada para {margin} celulas. Nao foi recall.")
        q = self.quests
        if q.active and q.phase == 'hunt':
            q.enter_stage('travel', time.monotonic())
            q.reason = 'Voltando ao mapa de caca depois do portal: '+q.route['name']
            print('[ROTA] '+q.reason)
        elif self.hunt is not None:
            self.hunt.pause('entrou num portal sem querer; confira o mapa e inicie de novo')
        return True

    def leave_portal_area(self, now):
        """Standing in or next to a portal's area (arrival, a fight pushed us there): the first
        move goes away from it, never towards it, before anything else is planned. Returns the move
        to send, or None."""
        collision = self.collision_map()
        position = self.tracker.observer.player
        if (collision is None or position is None or self.hunt is None or not self.hunt.enabled
                or not getattr(self.hunt, 'auto_movement', True)):
            return None
        from .portals import chebyshev
        name = self.tracker.observer.map_name
        inner = {cell for cell, _ in self.portals.links(name)}
        # Inside or right at the edge of a portal's area (its learned size, made larger by any
        # accidental warp there): a diagonal first step from gl_sew02 [31,275] went back through it.
        near = [(cell, margin) for cell, margin in self.portals.portals(name)
                if cell not in inner and chebyshev(position, cell) <= margin+1]
        if not near:
            return None
        def clearance(point):
            return min(chebyshev(point, cell)-margin for cell, margin in near)
        def ground(point):
            x, y = point
            return 0 <= x < collision.width-1 and 0 <= y < collision.height-1 and bool(collision.cells[y*collision.width+x])
        start = tuple(position)
        seen, queue = {start}, [start]
        for point in queue:
            if clearance(point) >= 3 and ground(point):
                return point
            if max(abs(point[i]-start[i]) for i in (0, 1)) >= 8:
                continue
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    other = (point[0]+dx, point[1]+dy)
                    # Every step farther from the portal: straight out, never along its edge.
                    if other not in seen and ground(other) and clearance(other) > clearance(point):
                        seen.add(other)
                        queue.append(other)
        return None

    async def step_out_of_portal(self, now):
        """Sends the move out of a portal's area; True while that walk is going on."""
        if now < getattr(self, 'portal_escape_until', 0):
            return True
        destination = self.leave_portal_area(now)
        if destination is None or self.upstream is None or not self.allow_commands or self.commands_blocked:
            return False
        position = self.tracker.observer.player
        async with self.send_lock:
            if not self.native_frames.ready:
                return True
            payload = move(*destination)
            self.trace_map_send('bot', struct.unpack_from('<H', payload)[0], len(payload))
            self.upstream.write(payload)
            await self.upstream.drain()
        seconds = max(50, min(self.tracker.observer.walk_speed_ms or 150, 2000))/1000
        steps = max(abs(destination[i]-position[i]) for i in (0, 1))
        self.portal_escape_until = now+steps*seconds*1.4+.3
        self.hunt.pending = None
        self.record_hunt({'kind': 'portal_area_left', 'origin': list(position), 'destination': list(destination)})
        print(f'Saindo da area do portal antes de andar pelo mapa: {list(position)} -> {list(destination)}.')
        return True

    def begin_hunt_transfer(self, now=None):
        if self.hunt is not None:
            self.hunt.map_transition()
        self.map_validation = None
        self.hunt_transfer_until = (time.monotonic() if now is None else now)+20

    def waiting_hunt_transfer(self, connected, now=None):
        until = getattr(self, 'hunt_transfer_until', 0)
        if not until:
            return False
        now = time.monotonic() if now is None else now
        if connected and self.tracker.observer.player_position_valid(now):
            self.hunt_transfer_until = 0
            return False
        if now >= until:
            self.hunt_transfer_until = 0
            if self.hunt is not None and self.hunt.enabled:
                self.hunt.pause('portal sem confirmacao do mapa de chegada; confira a conexao')
        return True

    async def bridge(self, stage, host, port, client_reader, client_writer):
        upstream = None
        jobs = []
        try:
            remote_reader, upstream = await asyncio.open_connection(host, port)
            self.error = None
            self.stage = stage
            if stage == 'login':
                self.login_phase = 'waiting'
                self.account = None
                self.character_id = None
                self.tracker.observer.clear()
                self.own_option = 0
            if stage == 'map':
                self.login_phase = 'loading'
                self.map_changed_at = time.monotonic()  # a new map server: wait for its 007D too
                # A new map connection is a new stream: what was left of the old one, and the map
                # login request (a format the guard does not know), desynchronized the frames
                # ("Comando nativo 1A00 sem enquadramento", 2026-11-04). Fresh guard, read after 0073.
                from .client_frame_guard import ClientFrameGuard
                self.native_frames = ClientFrameGuard()
                self.native_feed = False
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
                if self.hunt is not None:
                    self.hunt.map_transition()
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
                            if data[:2] == b'\x7d\x00':
                                self.map_loaded_at = time.monotonic()  # 007D before the position is known
                            # Every byte after the server's 0073 is read, position known or not: skipping
                            # a read while the position was briefly invalid cut frames in half.
                            if getattr(self, 'native_feed', True):
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
                endpoints = MapEndpointStream(self.account, self.register, self.begin_hunt_transfer) if stage == 'map' else None
                from .client_vision import ClientVision, VisionConfig
                vision=ClientVision.for_account(self.account,VisionConfig()) if stage=='map' else None
                if vision is not None:self.client_vision=vision
                removal = None
                # Part of the bot for every user (instant death removal, multi-hit shown as one hit):
                # on unless perfis/sem_remocao_visual exists. It used to need a file in perfis/, which
                # updates never carry, so only the developer's copy had it. The same pass withholds
                # the game's own drawing of skills RCX draws, when asked (hide_native_effect).
                if stage == 'map':
                    from .immediate_monster_removal import ImmediateMonsterRemoval
                    from .map_monsters import is_confirmed_monster

                    def confirmed_monster(entity_id):
                        entity = self.inventory.entities.get(entity_id)
                        if entity is None or not is_confirmed_monster(entity, self.tracker.observer.player_id):
                            return False
                        self.record_hunt({'kind': 'immediate_monster_removal', 'target_id': entity_id,
                                          'map': self.tracker.observer.map_name})
                        return True

                    removal = ImmediateMonsterRemoval(
                        self.account, confirmed_monster, drop=self.hide_native_effect,
                        rewrite=not (Path(__file__).resolve().parents[1]/'perfis'/'sem_remocao_visual').is_file())
                while data := await remote_reader.read(65536):
                    if stage == 'map':
                        routed = await endpoints.feed(data)
                        visible = removal.feed(routed) if removal is not None else routed
                        visible = vision.feed(visible)
                        if visible:
                            client_writer.write(visible)
                            await client_writer.drain()
                        self.mirror_map(data)
                    else:
                        frames.feed(data)
                        while (frame := frames.pop()) is not None:
                            op, packet = frame
                            if op == 0x69:
                                self.login_phase = 'world'
                                self.account = packet[8:12]  # in memory only
                                self.own_look = {'sex': packet[46]} if len(packet) > 46 else {}
                            elif op == 0x6b:
                                self.login_phase = 'characters'
                                self.char_list = packet
                            elif op == 0x71:
                                self.login_phase = 'loading'
                                self.select_character(struct.unpack_from('<I', packet, 2)[0])
                                from .packet_reader import character_look
                                self.own_look.update(character_look(self.char_list, self.character_id) or {})
                                self.next_map = packet[6:22].split(b'\0')[0].decode('cp1252', 'replace')
                            elif op in (0x6a, 0x6c, 0x6e, 0x70, 0x81):
                                self.login_phase = 'failed'
                            packet = await rewrite_endpoints(op, packet, self.register)
                            client_writer.write(packet)
                            await client_writer.drain()
                    if time.monotonic()-self.last_saved > .5:
                        self.last_saved = time.monotonic()
                        self.status()
                if endpoints is not None and (remaining := endpoints.flush()):
                    remaining=removal.feed(remaining) if removal is not None else remaining
                    client_writer.write(vision.feed(remaining))
                    await client_writer.drain()
                if removal is not None and (remaining := removal.flush()):
                    client_writer.write(vision.feed(remaining))
                    await client_writer.drain()
                if vision is not None and (remaining := vision.flush()):
                    client_writer.write(remaining);await client_writer.drain()
                if stage == 'map':
                    self.record_hunt({'kind': 'connection_eof', 'source': 'remote_server', 'recent_map_sends': list(self.recent_map_sends)})
            jobs = [asyncio.create_task(client_to_server()), asyncio.create_task(server_to_client())]
            done, pending = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (OSError, ValueError, asyncio.IncompleteReadError) as exc:
            if stage in ('login', 'char'):
                self.login_phase = 'failed'
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
                self.login_phase = ('loading' if getattr(self, 'hunt_transfer_until', 0) else
                                    'failed' if self.login_phase == 'failed' else 'disconnected')
                if self.hunt is not None and not getattr(self, 'hunt_transfer_until', 0):
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
        self.ground_cells.reset()
        self.publish_ground_cells()
        if self.ground_stream is not None:
            self.ground_stream.close()
            self.ground_stream = None
        if self.quests.active:
            self.save_progress(time.monotonic(), force=True)
        self.drops.close()
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

    def observe_chat_alerts(self, events):
        if self.observation_suspended_for_route():
            return
        """Public/private messages alert only when their sender is on the observation list."""
        from .watchlist import watched
        from .presence_guard import normalize_player_name
        found = []
        entries = None
        for event in events:
            public = event['kind'] == 'actor_signal' and event.get('signal') == 'chat'
            private = event['kind'] == 'chat_received' and event.get('channel') == 'private'
            if public or private:
                if entries is None:
                    entries = self.load_watchlist()
                if not entries:
                    return
                identity = event.get('entity_id')
                name = event.get('name') or (self.registry.players.get(str(identity)) or {}).get('name')
                matched = any(watched(entry, identity, name) for entry in entries)
                # Whispers carry the sender's name, not its actor ID. Resolve watched IDs
                # through their latest registered name; never guess an unknown sender's ID.
                if private and not matched and name:
                    for entry in entries:
                        if entry.isdigit():
                            known = self.registry.players.get(str(int(entry))) or {}
                            if known.get('name') and normalize_player_name(known['name']) == normalize_player_name(name):
                                identity, matched = int(entry), True
                                break
                if not matched:
                    continue
                found.append(dict(kind='chat', watched=True, entity_id=identity,
                                  name=name, channel='private' if private else 'public',
                                  text='Mensagem recebida no '+('privado' if private else 'chat geral')))
        if found:
            import uuid
            self.chat_alert = dict(id=uuid.uuid4().hex, detections=found[-4:], count=len(found))

    def load_watchlist(self):
        from . import watchlist
        now = time.monotonic()
        if now < getattr(self, 'watch_checked_until', 0) and self.watch_stamp is not None:
            stamp = self.watch_stamp  # the files are looked at once a second, not on every tick
        else:
            self.watch_checked_until = now+1
            stamp = self.watch_files_stamp(watchlist)
        if stamp != self.watch_stamp:
            self.watch_stamp, self.watch_entries = stamp, watchlist.load()
            self.watch_enabled = watchlist.enabled()
        return self.watch_entries_effective()

    @staticmethod
    def watch_files_stamp(watchlist):
        stamp = []
        for path in (watchlist.FILE, watchlist.FILE.with_name('observacao_opcoes.json')):
            try:
                info = path.stat()
                stamp.append((info.st_mtime_ns, info.st_size))
            except OSError:
                stamp.append(None)
        return tuple(stamp)

    def watch_entries_effective(self):
        from .presence_guard import normalize_player_name
        on = getattr(self, 'watch_enabled', True)
        self.presence.observation_ignored = {int(e) for e in self.watch_entries if e.isdigit()} if not on else set()
        self.presence.observation_ignored_names = {normalize_player_name(e) for e in self.watch_entries if not e.isdigit()} if not on else set()
        # Private/name detections of IDs learned earlier use the same registered identity.
        if not on:
            self.presence.observation_ignored_names.update(normalize_player_name(row['name'])
                for identity, row in self.registry.players.items()
                if str(identity) in self.watch_entries and row.get('name'))
        return self.watch_entries if on else []

    def gm_signs_found(self, now):
        """[(row, reasons)] of visible characters that look like GM/staff."""
        if not self.gm_detection_on():
            return []
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

    def gm_detection_on(self):
        return bool((self.settings or {}).get('gm_detection', True))

    def preview_rcx_self_skill(self, skill_id, target_id, now, duration=1.0, confirmed=False):
        """Self-centred terrain skills (Desperado etc.) use the caster's cell, never the mouse."""
        observer=self.tracker.observer
        metadata=observer.skills.get(skill_id) or {}
        if (observer.player_id is None or target_id!=observer.player_id
                or metadata.get('level',0)<=0 or metadata.get('target_flags')!=4):return False
        from .rcx_settings import catalog
        if not any(s['skill_id']==skill_id and not s.get('ground',False) for r in catalog() for s in r['skills']):return False
        positions=observer.combat_positions(now)
        position=positions[0] if positions else observer.player
        if position is None:return False
        if confirmed:self.ground_cells.preview_cast(skill_id,list(position),now,duration)
        else:self.ground_cells.request_cast(skill_id,list(position),now)
        if confirmed:
            self.ground_cells.note_ground_skill(dict(skill_id=skill_id,source_id=observer.player_id,
                position=list(position),level=metadata['level']),now)
        return True

    VIEWPOINT_TTL = 90.0  # s: monsters marked by @showmobs walk away; old marks would mislead

    def observe_viewpoints(self, events, now):
        """Server minimap marks (0144): @showmobs answers one per monster; type 2 removes one."""
        for event in events:
            if event['kind'] in ('map_change', 'map_transfer'):
                self.viewpoint_marks.clear()
            elif event['kind'] == 'viewpoint' and event.get('position'):
                key = (event.get('npc_id'), event.get('mark_id'))
                if event.get('mark_type') == 2:
                    self.viewpoint_marks.pop(key, None)
                    from .mob_scan import mark_key
                    self.mob_scan.mark_records.pop(mark_key(event.get('npc_id'), event.get('mark_id')), None)
                elif event.get('mark_type') == 1:
                    species = self.mob_scan.current_species if now-self.mob_scan.sent_at <= self.mob_scan.LISTEN else None
                    self.viewpoint_marks[key] = {'position': list(event['position']), 'species': species, 'at': now}
        if len(self.viewpoint_marks) > 2000:
            for key in sorted(self.viewpoint_marks, key=lambda k: self.viewpoint_marks[k]['at'])[:-2000]:
                del self.viewpoint_marks[key]

    def current_viewpoint_marks(self, now=None):
        now = time.monotonic() if now is None else now
        result = []
        for key, mark in list(self.viewpoint_marks.items()):
            if now-mark['at'] > self.VIEWPOINT_TTL:
                del self.viewpoint_marks[key]
                continue
            result.append({'position': mark['position'], 'name': self.viewpoint_name(mark['species'])})
        return result

    def viewpoint_name(self, species):
        """Monster name of an @showmobs mark, looked up once per kind: name_of reads the monster
        files from disk, and doing it per mark on every state update froze the relay (lag)."""
        if not species:
            return None
        names = self.__dict__.setdefault('viewpoint_names', {})
        if species not in names:
            from .monster_db import name_of
            try:
                names[species] = name_of(species)
            except (OSError, ValueError, KeyError, TypeError):
                names[species] = None
        return names[species]

    RCX_HEARTBEAT = 3.0  # s: the RCX panel touches rcx_ativo while it draws in the game

    def rcx_drawing(self, now):
        """RCX config and whether RCX is drawing now; re-read at most twice a second."""
        cached = getattr(self, 'rcx_native_cache', None)
        if cached and now < cached[0]:
            return cached[1], cached[2]
        from . import rcx_settings
        try:
            active = time.time()-(self.folder/'rcx_ativo').stat().st_mtime < self.RCX_HEARTBEAT
        except OSError:
            active = False
        config = None
        if active:
            try:
                stamp = rcx_settings.FILE.stat().st_mtime_ns
            except OSError:
                stamp = None
            previous = getattr(self, 'rcx_native_config', None)
            if previous and previous[0] == stamp:
                config = previous[1]
            else:
                config = rcx_settings.load()
                self.rcx_native_config = (stamp, config)
        self.rcx_native_cache = (now+.5, active, config)
        return active, config

    def record_damage_taken(self, events):
        """Every hit the character takes, with the body armor worn at that moment, goes to
        dano_recebido.jsonl: lets the player compare damage with and without a piece of gear.
        Equipment changes and the character's status effects are written too."""
        own = self.tracker.observer.player_id
        if own is None or not hasattr(self, 'folder'):
            return
        lines = []
        for e in events:
            kind = e['kind']
            if kind in ('skill_damage', 'normal_attack') and e.get('target_id') == own and e.get('source_id') != own:
                lines.append({k: e[k] for k in ('kind', 'skill_id', 'level', 'source_id', 'damage_raw', 'action_type') if k in e})
            elif kind in ('equipment_ack', 'inventory_list') or (kind == 'status_effect' and e.get('entity_id') == own):
                lines.append({k: e[k] for k in ('kind', 'index', 'position', 'success', 'equipped', 'effect_id', 'active', 'duration_ms') if k in e})
        if not lines:
            return
        gear = getattr(getattr(self.quests, 'body', None), 'gear', {}) or {}
        armor = next((v['item_id'] for v in gear.values() if v.get('worn', 0) & 16), 0)
        stamp = datetime.now().isoformat()
        try:
            with (self.folder/'dano_recebido.jsonl').open('a', encoding='utf-8') as log:
                for line in lines:
                    log.write(json.dumps({'at': stamp, 'map': self.tracker.observer.map_name, 'armor': armor, **line}, ensure_ascii=False)+'\n')
        except OSError:
            pass

    def hide_native_effect(self, packet):
        """A skill unit on the floor (011F) or a ground skill's animation (0117) that RCX acts on
        (its side checked) and whose entry asks to hide the GRF effect is not forwarded to the client."""
        op = bytes(packet[:2])
        if not ((op == b'\x1f\x01' and len(packet) == 16) or (op == b'\x17\x01' and len(packet) == 18)):
            return False
        now = time.monotonic()
        active, config = self.rcx_drawing(now)
        if not active or not config:
            return False
        if not any(s.get('hide_native') for section in ('effects', 'skill_styles') for s in config[section].values()):
            return False
        from . import rcx_settings
        own = self.tracker.observer.player_id
        def ground_for(source):
            # Only this caster's side is needed (a full snapshot per packet would cost too much).
            records = self.registry.players
            guild = {k: v for k, v in {**records.get(str(own), {}), **(self.own_look or {})}.items() if k in ('guild_id', 'guild')}
            allied = self.rcx_sides.allied(source, own, records, set(self.group_member_ids()), self.own_summons.allies(), guild)
            return {'own_id': own, 'allied_ids': [source] if allied else []}
        if op == b'\x1f\x01':
            source, unit_type = struct.unpack_from('<I', packet, 6)[0], packet[14]
            skill = self.ground_cells.area_skill(source, now, unit_type)
            hidden = rcx_settings.hides_native(config, unit_type, skill, source, ground_for(source))
        else:
            skill, source = struct.unpack_from('<HI', packet, 2)
            hidden = rcx_settings.hides_native(config, None, skill, source, ground_for(source))
        return hidden

    def rcx_summon_skills(self):
        """Summon skills known to the bot (own profiles and learned creatures): another player's
        creature created right after one of them belongs to that player."""
        skills = {p['skill_id'] for p in (self.settings or {}).get('skill_profiles', []) if p.get('role') == 'summon'}
        learned = self.rotation.summons.learned if self.rotation is not None else None
        if learned is None:
            if not hasattr(self, 'rcx_learned_summons'):
                try:
                    path = Path(__file__).resolve().parents[1]/'data/rede/invocacoes_aprendidas.json'
                    self.rcx_learned_summons = json.loads(path.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    self.rcx_learned_summons = {}
            learned = self.rcx_learned_summons
        for key, row in (learned or {}).items():
            if isinstance(row, dict) and row.get('creature') and str(key).split(':')[0].isdigit():
                skills.add(int(str(key).split(':')[0]))
        return skills

    def observe_rcx_affiliation(self, events):
        """Battleground team, PvP map, party, own guild and other players' summons (rcx_sides)."""
        if not any(e['kind'] in ('map_change', 'map_transfer', 'bg_team', 'map_property', 'map_type', 'pvp_rank', 'party_list',
                                 'party_join', 'party_leave', 'name', 'appearance', 'skill_cast', 'skill_no_damage',
                                 'remove') for e in events):
            return False
        own = self.tracker.observer.player_id
        def position_of(identity):
            if identity == own:
                return self.tracker.observer.player
            entity = self.inventory.entities.get(identity)
            return entity.get('position') if entity else None
        self.rcx_sides.map_name = self.tracker.observer.map_name or ''
        before = self.rcx_sides.describe()
        changed = self.rcx_sides.observe(events, own, time.monotonic(), self.rcx_summon_skills(), position_of)
        for event in events:
            if event['kind'] in ('map_property', 'map_type', 'pvp_rank'):
                self.record_hunt({'kind': 'rcx_map_side', 'packet': event['kind'], 'value': event.get('value'),
                                  'map': self.tracker.observer.map_name, 'mode': self.rcx_sides.describe()})
        if self.rcx_sides.describe() != before:
            print(f"RCX: aliados/inimigos agora pela regra de mapa {self.rcx_sides.describe()}.")
        return changed

    def rcx_ground_snapshot(self):
        value = self.ground_cells.snapshot(); own = self.tracker.observer.player_id
        sides = self.rcx_sides
        records = self.registry.players
        guild = {k: v for k, v in {**records.get(str(own), {}), **(self.own_look or {})}.items() if k in ('guild_id', 'guild')}
        group = set(self.group_member_ids()); summons = self.own_summons.allies()
        sources = {e.get('source_id') for e in value['effects']+value['casts']} | group | summons
        allies = {s for s in sources if type(s) is int and sides.allied(s, own, records, group, summons, guild)}
        value.update(own_id=own, allied_ids=sorted(allies), rcx_side_rule=sides.describe())
        if sides.battleground:
            value['battleground_team'] = sides.own_team
        return value

    def publish_ground_cells(self):
        """Small independent RCX feed; a terrain packet does not wait for the full UI snapshot."""
        try:
            value = self.rcx_ground_snapshot()
            from .rcx_stream import Publisher
            if self.ground_stream is None:
                self.ground_stream = Publisher(self.folder/'rcx_terreno.ipc')
            self.ground_stream.publish(value)
            now=time.monotonic()
            if now-getattr(self,'last_rcx_json',0)<.1:return
            self.last_rcx_json=now
            target = self.folder/'rcx_terreno.json'
            temp = target.with_suffix('.tmp')
            temp.write_text(json.dumps(value), encoding='utf-8')
            temp.replace(target)
        except (OSError, ValueError):
            pass  # a display problem must never disconnect the game

    def observation_suspended_for_route(self):
        """Trips between maps (quests, database hunt, return after death, BG, heal test), NPC talks and
        mount/equipment/@voltar: watched players neither stop the bot nor alert; only the hunt does."""
        q = self.quests
        return q.active and (q.phase != "hunt" or bool(q.errands))

    def emergency_detections(self):
        """Watched characters found (any way, @hide included) and anyone in @hide / invisible."""
        from . import watchlist
        from .presence_guard import OPTION_INVISIBLE
        now = time.monotonic()
        if self.observation_suspended_for_route():
            return []  # trips between maps and errands go on; the hunt (patrol) stops
        entries = self.load_watchlist()
        hidden_gm = self.gm_detection_on() and any(h['option'] & OPTION_INVISIBLE for h in self.presence.hidden.values())
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
            if (d['kind'] == 'gm_hide' and self.gm_detection_on() and d['entity_id'] not in found
                    and not self.presence.ignored(d['entity_id'])):
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
        self.sync_presence_names()
        if self.observation_suspended_for_route():
            return
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
        reason = None if self.observation_suspended_for_route() else self.presence.reason(self.tracker.observer.player, time.monotonic())
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

    SLOW_CAST = .3  # s: an offensive skill casting this long gives way to basic attacks

    def prefer_basic_attack(self, rotation_action, action, state, now):
        """Map behavior: with the monster right next to the character and basic attacks possible, a
        skill with a cast time waits. TsuutenKyaku cast for ~1.3 s (~90k) while ~8 basic attacks of
        65535 each would have landed (Lider Jounin, ra_fild03 2026-11-06)."""
        if (rotation_action is None or rotation_action.get('role') != 'offensive' or action is None
                or action['kind'] != 'attack' or self.active_map_combat() is None
                or not (self.settings and self.settings['auto_attacks'])):
            return rotation_action
        cast = getattr(self.tracker.observer, 'cast_times', {}).get(rotation_action.get('skill_id'), 0)
        if cast < self.SLOW_CAST or not self.map_damage_allowed(action['target_id'], state, now, basic=True):
            return rotation_action
        return None

    def attack_turn(self, action, rotation_action=None):
        """Use a basic attack only when no rotation skill is ready to send."""
        return (rotation_action is None and action is not None and action['kind'] == 'attack' and self.rotation is not None
                and bool(self.settings and self.settings['auto_attacks']))

    def walking_now(self):
        motion = self.tracker.observer.player_motion
        return motion is not None and time.monotonic() < motion['at']+motion['duration']

    def observe_own_summons(self, events, now):
        """Own summons (appear next to the character right after its summon) and the homunculus."""
        own = self.own_summons
        waiting = self.rotation.summons.waiting if self.rotation is not None else None
        if waiting is not None:
            own.until = max(own.until, waiting['sent_at']+own.WINDOW)
        skills = {p['skill_id'] for p in (self.settings or {}).get('skill_profiles', []) if p.get('role') == 'summon'}
        own.observe(events, self.tracker.observer.player_id, self.tracker.observer.player, now, skills)
        for event in events:
            if (event['kind'] in ('appearance', 'move', 'position')
                    and event.get('entity_id') == own.homunculus):
                self.homun_rested_at = None
                self.homun_away_since = None
                self.homun_call_attempts = 0
            elif event['kind'] in ('map_change', 'map_transfer'):
                self.homun_away_since = None
        self.quests.allies = own.allies() | self.group_member_ids()
        queue = self.rotation if self.rotation is not None else None
        for entry in own.log:
            if queue is not None and entry['kind'] == 'own_summon_seen':
                queue.summon_created(entry['entity_id'], now)
        if queue is not None:
            for event in events:
                if event['kind'] == 'remove' and event.get('reason') != 0:
                    queue.summons.creature_gone(event.get('entity_id'), now)
            self.flush_rotation_diagnostics()
        for identity in own.allies():
            entity = self.inventory.entities.get(identity)
            if entity is not None:
                entity['summoned'] = True  # never a hunt target
        for entry in own.log:
            self.record_hunt(entry)
            if entry['kind'] == 'own_summon_seen':
                print(f"Invocação reconhecida como sua: {entry['entity_id']} ({entry['evidence']}, {entry['cells']} células).")
            elif entry['kind'] == 'own_summon_dropped':
                print(f"Invocação {entry['entity_id']} descartada: {entry['reason']}.")
            elif entry['kind'] == 'homunculus_seen':
                print(f"Homúnculo identificado pelo servidor: ID {entry['entity_id']}.")
            if entry['kind'] == 'homunculus_fed':
                print(f"Homúnculo alimentado (fome antes: {entry['hunger_before']})." if entry['success'] else
                      '[ALERTA] O servidor recusou alimentar o homúnculo (comida no inventário?). Nova tentativa em 2 min.')
        own.log.clear()

    def group_member_ids(self):
        """Players of the group (leader and members in the Grupo tab) seen here: the server gives
        party members nearby the quest kill too, so theirs are counted like ours."""
        from .presence_guard import normalize_player_name
        settings = self.settings or {}
        names = {normalize_player_name(n) for n in [settings.get('group_leader', ''), *settings.get('group_members', [])] if n}
        if not names:
            return set()
        own = self.tracker.observer.player_id
        return {identity for identity, name in self.player_names.items()
                if identity != own and name and normalize_player_name(name) in names}

    def flush_quest_kills(self):
        """Every kill the quest counted, with who made it: compare with the game's own counter."""
        own = self.tracker.observer.player_id
        homunculus = self.own_summons.homunculus
        for kill in self.quests.kill_log:
            by = kill['by']
            from .network_targets import is_player_id
            kill['by_kind'] = ('personagem' if by == own else 'homúnculo' if by == homunculus else
                               f"grupo ({self.player_names.get(by, by)})" if is_player_id(by) else 'invocação')
            self.record_hunt(kill)
            print(f"[ROTA] Morte contada: {kill.get('name') or kill['species_id']} (por {kill['by_kind']}"
                  + ('' if by == own else f' {by}')+').')
        self.quests.kill_log.clear()

    CALL_HOMUNCULUS, REST_HOMUNCULUS, RESURRECT_HOMUNCULUS = 243, 244, 247  # Invocar / guardar / Remontar Marionete
    HOMUN_OUT_OF_VIEW = 3.0  # s out of the screen before it is put away and called again
    HOMUN_SKILL_EVERY = 3.0

    async def keep_homunculus_alive(self, now):
        """Remontar Marionete when it died; out of the screen (left behind walls): put it away
        and Invocar Marionete next to the character. Uses only the skills the character has."""
        own = self.own_summons
        observer = self.tracker.observer
        learned = {identity for identity in (self.CALL_HOMUNCULUS, self.REST_HOMUNCULUS, self.RESURRECT_HOMUNCULUS)
                   if observer.skills.get(identity, {}).get('level', 0) > 0}
        if (not learned or self.hunt is None or not self.hunt.enabled or observer.player_id is None
                or not observer.player_alive or self.map_loading(now)
                or self.manual_control(now) or self.presence_hold is not None
                or now-getattr(self, 'homun_skill_at', -1e9) < self.HOMUN_SKILL_EVERY):
            return False
        entity = self.inventory.entities.get(own.homunculus) or {}
        if own.dead:
            skill_id, why = self.RESURRECT_HOMUNCULUS, 'Remontar Marionete (morreu)'
        elif getattr(self, 'homun_rested_at', None) is not None or not own.homunculus:
            skill_id, why = self.CALL_HOMUNCULUS, 'Invocar Marionete (perto do personagem)'
        elif self.homunculus_far(entity, observer.player, now):
            since = getattr(self, 'homun_away_since', None)
            if since is None:
                self.homun_away_since = now
                return False
            if now-since < self.HOMUN_OUT_OF_VIEW:
                return False
            # Only the server's visibility removal authorizes recovery. Standing
            # still to wait for it left the bot frozen in mazes (tur_dun01, 2026-11-05: 491 waits).
            if not {self.REST_HOMUNCULUS, self.CALL_HOMUNCULUS} <= learned:
                return False
            skill_id, why = self.REST_HOMUNCULUS, 'guardando a marionete fora da visao recebida do servidor'
        else:
            self.homun_away_since = None
            return False
        metadata = observer.skills.get(skill_id)
        if not metadata or metadata.get('level', 0) < 1:
            if skill_id not in getattr(self, 'homun_missing_warned', set()):
                self.homun_missing_warned = getattr(self, 'homun_missing_warned', set()) | {skill_id}
                print(f'[ALERTA] Marionete: habilidade {skill_id} nao aprendida neste personagem; {why} nao sera feito.')
            return False
        if self.upstream is None or not self.allow_commands or self.commands_blocked:
            return False
        # No response must not turn into a successful call, or starve combat forever.
        if getattr(self, 'homun_call_attempts', 0) >= 3:
            if now-getattr(self, 'homun_skill_at', now) < 15:
                return False
            self.homun_call_attempts = 0
            if getattr(self, 'homun_rested_at', None) is not None and self.REST_HOMUNCULUS in learned:
                skill_id, why = self.REST_HOMUNCULUS, 'repetindo recuperacao sem reaparecimento confirmado'
                metadata = observer.skills[skill_id]
        if (now < max(observer.cast_until, observer.skill_cooldowns.get(skill_id, 0),
                      self.rotation.next_send if self.rotation is not None else 0)
                or observer.sp is not None and observer.sp < metadata.get('sp_cost', 0)):
            return False
        async with self.send_lock:
            if not self.native_frames.ready:
                return False
            payload = skill(observer.player_id, skill_id, metadata['level'])
            self.trace_map_send('bot', struct.unpack_from('<H', payload)[0], len(payload))
            self.upstream.write(payload)
            await self.upstream.drain()
        self.homun_skill_at = now
        if skill_id == self.REST_HOMUNCULUS:
            self.homun_rested_at, self.homun_away_since = now, None
            self.homun_call_attempts = 0
        elif skill_id == self.CALL_HOMUNCULUS:
            self.homun_call_attempts = getattr(self, 'homun_call_attempts', 0)+1
        if self.rotation is not None:
            self.rotation.next_send = max(self.rotation.next_send, now+self.rotation.global_delay)
        print(f'Marionete: {why}.')
        self.record_hunt({'kind': 'homunculus_skill', 'skill_id': skill_id, 'reason': why})
        return True

    def homunculus_far(self, entity, own, now):
        """Server view, independent of camera zoom; a distant destination is not invisibility."""
        if self.own_summons.visible is not None:
            return not self.own_summons.visible
        return entity.get('present_last_observation') is False

    async def maintain_homunculus(self, now):
        """Feeds the homunculus when its hunger reaches the chosen number (same command as its menu)."""
        settings = self.settings or {}
        if (not any(self.tracker.observer.skills.get(identity, {}).get('level', 0) > 0
                    for identity in (self.CALL_HOMUNCULUS, self.REST_HOMUNCULUS, self.RESURRECT_HOMUNCULUS))
                or not settings.get('homun_feed') or not self.own_summons.should_feed(settings.get('homun_hunger', 25), now)):
            return False
        if (self.upstream is None or not self.allow_commands or self.commands_blocked or self.map_loading(now)
                or not self.tracker.observer.player_alive):
            return False
        from .own_summons import feed_packet
        async with self.send_lock:
            if not self.native_frames.ready:
                return False
            payload = feed_packet(self.own_summons.feed_type)
            self.trace_map_send('bot', 0x22d, len(payload))
            self.upstream.write(payload)
            await self.upstream.drain()
        self.own_summons.sent(now)
        print(f'Alimentando o homúnculo (fome {self.own_summons.hunger}, limite {settings.get("homun_hunger", 25)}).')
        self.record_hunt({'kind': 'homunculus_feed_sent', 'hunger': self.own_summons.hunger})
        return True

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
            if action['kind'] in ('attack','skill') and not self.map_damage_allowed(action['target_id'],state,time.monotonic(),basic=action['kind']=='attack'):
                raise HuntTargetChanged('Perfil de combate: controle de status antes do dano')
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
            if not is_patrol and self.dead(action['target_id']):
                raise HuntTargetChanged('Alvo morto: nenhum ataque ou habilidade')
            player = observer.player
            target = None if is_patrol else entity.combat_bounds(time.monotonic())[0][0]
            # A monster across a wall is no reason to stop walking: the patrol is what gets there.
            if is_patrol and not group_follow:
                combat=self.active_map_combat()
                if combat:
                    interrupt=self.map_combat_intent(combat,state,time.monotonic()) is not None
                else:
                    interrupt=any(math.dist(player,e['position'])<=self.hunt.SEARCH_RADIUS
                                  and self.hunt.excluded_until.get(e['entity_id'],0)<=time.monotonic()
                                  and not self.hunt.walled(e['entity_id'],time.monotonic())
                                  and e['entity_id'] not in self.hunt.passed_over for e in state['recent_entities'])
                if interrupt:raise HuntTargetChanged('Alvo elegivel apareceu; patrulha interrompida')
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
                positions=observer.combat_positions(time.monotonic())
                safe_origin=positions[0] if positions else player
                if self.crosses_ground_hazard(safe_origin,destination,time.monotonic()):
                    raise HuntTargetChanged('Nevoa toxica no caminho; recalculando')
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
            combat = self.active_map_combat()
            if combat and action['kind']=='attack':
                combat.attacked.add(action['target_id'])
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
            if action['kind'] in ('attack', 'skill'):
                self.note_player_attack(action['target_id'], time.monotonic())
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
            relay.map_repository = MapRepository(game_dir, independent=True)
            print('Navegacao independente: usando colisao do servidor/base do bot; GRFs e DATA.INI visuais ignorados.')
        except (OSError, ValueError, GrfError) as exc:
            print(f'Colisão indisponível: {exc}. Aproximação anterior mantida. Pasta do jogo usada: {locals().get("game_dir")}')
    from .ammo import names_from_catalog
    try:
        relay.ammo.names = names_from_catalog()
        print(f'Catalogo independente de municao: {len(relay.ammo.names)} itens.')
    except (OSError, ValueError) as exc:
        print(f'Municao automatica indisponivel: {exc}. Atualize os recursos do bot.')
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
        relay.manual_walk_input = lambda: controls.movement_input(relay.game_peer, relay.game_local)
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
                controls.movement_input(relay.game_peer, relay.game_local)
                relay.process_control(lambda: controls.connected(relay.game_peer, relay.game_local))
                relay.sync_map_behavior()
                relay.finish_buff_learning(time.monotonic())
                try:
                    await relay.maintain_homunculus(time.monotonic())
                except OSError as exc:
                    print(f'Alimentação do homúnculo não enviada: {exc}')
                if relay.buff_probe_request is not None:
                    request, relay.buff_probe_request = relay.buff_probe_request, None
                    try:
                        await relay.send_buff_probe(request, game_gate=lambda: controls.connected(relay.game_peer, relay.game_local))
                        relay.control_result = {'id': request['id'], 'ok': True, 'message': 'Buff enviado uma vez; aguarde o vínculo candidato na aba Habilidades'}
                    except (ValueError, OSError) as exc:
                        relay.control_result = {'id': request['id'], 'ok': False, 'message': str(exc)}
                    relay.status()
            if time.monotonic()-last_heartbeat >= .5:
                if relay.ground_stream is not None and relay.stage=='map' and relay.upstream is not None:
                    relay.ground_stream.pulse()
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
                    relay.expire_captured(time.monotonic())
                    loading = relay.map_loading(time.monotonic())  # nothing is sent until the game shows the map
                    try:
                        was_route = relay.observation_suspended_for_route()
                        toxic_hold = False if loading else await relay.avoid_toxic_ground(lambda: controls.connected(relay.game_peer,relay.game_local))
                        route_travel = loading or toxic_hold or await relay.quest_tick(lambda: controls.connected(relay.game_peer,relay.game_local))
                    except (asyncio.CancelledError, KeyboardInterrupt):
                        raise
                    except Exception as exc:  # the queue stops; the connection stays up
                        import traceback
                        (relay.folder/'erro_relay.txt').write_text(traceback.format_exc(), encoding='utf-8')
                        relay.quest_stop(f'erro interno na fila ({type(exc).__name__}); conexão mantida')
                        print(f'Erro na fila de quests: {type(exc).__name__}: {exc}. Detalhes em erro_relay.txt')
                        route_travel = False
                    if was_route and not relay.observation_suspended_for_route():
                        relay.check_emergency()
                    if not loading:
                        await relay.send_mob_info(game_gate=lambda: controls.connected(relay.game_peer, relay.game_local))
                        await relay.send_loot_commands(game_gate=lambda: controls.connected(relay.game_peer, relay.game_local))
                        await relay.send_mob_scan(game_gate=lambda: controls.connected(relay.game_peer, relay.game_local))
                    if relay.hunt.enabled and not route_travel:
                        if relay.waiting_hunt_transfer(controls.connected(relay.game_peer, relay.game_local)):
                            pass
                        elif not controls.connected(relay.game_peer, relay.game_local):
                            relay.hunt.pause('conexão do jogo indisponível')
                            print(f'Caça pausada: conexão do jogo indisponível. {relay.hunt_key_name} retoma.')
                        elif (relay.manual_control(time.monotonic()) or await relay.update_presence_hold()
                              or await relay.step_out_of_portal(time.monotonic())):
                            pass
                        else:
                            try:
                                state = relay.status()
                                if relay.pvp_registered and state.get('player_position') is not None:
                                    state = relay.prioritize_pvp(state)
                                if relay.rotation is not None:
                                    state['engagement_range'] = relay.rotation.navigation_range(state, time.monotonic(), relay.hunt.target)
                                action = relay.plan_group_or_hunt(state, time.monotonic(), relay.tracker.observer.walk_speed_ms, relay.collision_map())
                                homun_sent = (relay.group_combat_allowed()
                                              and await relay.keep_homunculus_alive(time.monotonic()))
                                if homun_sent and action is not None and action['kind'] != 'move':
                                    action = None
                                relay.flush_hunt_diagnostics()
                                # Dead or with no position (e.g. killed in PvP): no skill target to measure from.
                                if (not homun_sent and relay.rotation is not None and relay.group_combat_allowed()
                                        and state.get('player_position') is not None and relay.tracker.observer.player_alive):
                                    now = time.monotonic()
                                    # Select a combat target even while a patrol leg is in flight.
                                    own = (state.get('combat_player_positions') or [state['player_position']])[0]
                                    candidates = [e for e in state['recent_entities']
                                                  if relay.hunt.excluded_until.get(e['entity_id'], 0) <= now
                                                  and not relay.hunt.walled(e['entity_id'], now)]
                                    # The ordinary combat's own pick, only without a map behavior: with one, the
                                    # map's decision is the only one (two pickers took turns overriding each other).
                                    if (relay.active_map_combat() is None and not relay.group_follower() and candidates
                                            and relay.hunt.target not in {e['entity_id'] for e in candidates}):
                                        candidate = min(candidates, key=lambda e: (relay.hunt.target_priority.get(e.get('species_id'), 1000),
                                                                                   math.dist(own, e.get('effective_position', e['position']))))
                                        if math.dist(own, candidate.get('effective_position', candidate['position'])) <= relay.hunt.SEARCH_RADIUS:
                                            relay.hunt.target = candidate['entity_id']
                                    # Keep basic attacks interleaved during skill cooldowns, but let any
                                    # ready map-profile skill take priority over another basic packet.
                                    # Focused on a player: keeping the own summon up never holds attacks back.
                                    summon_maintenance = (not state.get('player_focus')
                                                          and relay.rotation.summon_maintenance_required(state, now, relay.hunt.target))
                                    rotation_action = relay.plan_map_rotation(state, now, relay.hunt.target)
                                    rotation_action = relay.prefer_basic_attack(rotation_action, action, state, now)
                                    attack_turn = (relay.map_damage_allowed(relay.hunt.target,state,now,basic=True) and not summon_maintenance
                                                   and relay.last_combat_packet == 'skill' and now >= relay.tracker.observer.cast_until
                                                   and relay.attack_turn(action, rotation_action))
                                    skill_sent = False
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
                                    if relay.skill_failure_switch(state, time.monotonic()):
                                        action = None  # the next tick picks the other monster
                                if action is not None and action['kind'] in ('attack','skill') and not relay.map_damage_allowed(action['target_id'],state,time.monotonic(),basic=action['kind']=='attack'):
                                    action = None
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
                            except (asyncio.CancelledError, KeyboardInterrupt):
                                raise
                            except Exception as exc:
                                # One bad tick must never take the relay down: that dropped the game
                                # connection at once (death in PvP, 2026-11-04). The hunt pauses instead.
                                import traceback
                                (relay.folder/'erro_relay.txt').write_text(traceback.format_exc(), encoding='utf-8')
                                relay.hunt.pause(f'erro interno na caça ({type(exc).__name__}); conexão mantida')
                                print(f'Erro na caça: {type(exc).__name__}: {exc}. Caça pausada, conexão mantida; detalhes em erro_relay.txt')
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
