"""REDE-30: decisões de caça por ID. Sem teclado, mouse ou acesso à rede."""
from __future__ import annotations

import math
import time
from collections import deque


class PacketHunt:
    SEARCH_RADIUS = 28
    MAX_STEPS = 12
    SKILL_INTERVAL = .5
    SKILL_RESPONSE_TIMEOUT = 1.5
    SKILL_ATTEMPTS = 3
    TARGET_DEFER = 8
    # REDE-62: a monster we hit (or that hits us) is kept until it dies or leaves the
    # client view; only this long without any confirmed damage releases it.
    ENGAGED_GIVE_UP = 15
    # REDE-84: basic attacks on: walk up to the target and attack it between skills.
    # Basic attacks off: run away whenever the monster comes inside the skill distance.
    MELEE_RANGE = 2  # the server itself takes the last step of an attack request
    KITE_MARGIN = 1  # flee when the monster is closer than skill range minus this
    ATTACK_RESPONSE_TIMEOUT = 1.2  # a basic attack is answered well within this; then the next one goes
    # A monster close in a straight line but with a long walk around a wall is not a target: going
    # for it took the character away until it left the view, then back, over and over.
    WALL_DETOUR = 10    # extra steps accepted beyond the straight distance (or the distance itself)
    WALL_CHECKS = 6     # routes measured per decision

    def __init__(self, patrol=False, patrol_step=8, use_skills=False):
        self.auto_attacks = True
        self.melee_approach = True
        self.kite = False
        self.use_skills = use_skills
        self.skill_disabled = False
        self.skill_ready_at = 0
        self.skill_reason = 'aguardando dados do servidor'
        self.confirmed_skills = 0
        self.skill_failures = 0
        self.skill_attempts = {}
        from .packet_patrol import PacketPatrol
        self.auto_movement = True
        self.patrol = PacketPatrol(max_step=patrol_step) if patrol else None
        self.enabled = False
        self.reason = 'aguardando Home'
        self.target = None
        self.pending = None
        self.attempts = 0
        self.ready_at = 0
        self.confirmed_attacks = 0
        self.moves = 0
        self.target_since = None
        self.excluded_until = {}
        self.blocked_until = {}
        self.navigation = 'sem mapa de colisão'
        self.diagnostics = []
        self.movement_corrections = 0
        self.movement_failures = 0
        self.last_target_motion = -float('inf')
        self.last_decision = None
        self.engaged = None
        self.engaged_until = 0
        self.aggressors = {}
        self.priority_target = None  # REDE-67: captured character
        self.target_priority = {}  # species -> order (1 first): quest monsters to finish before the rest
        self.approach_cache = None
        self.awaiting_map = False
        self.wall_checks = {}  # entity id -> (until, player, monster point, behind a wall)
        self.passed_over = set()  # monsters in view when the last patrol step was chosen

    def map_transition(self):
        """Keep the run/pause choice, discard commands and IDs from the previous area."""
        self.awaiting_map = self.enabled
        self.target = self.pending = self.engaged = None
        self.aggressors.clear()
        self.excluded_until.clear()
        self.blocked_until.clear()
        self.wall_checks.clear()
        self.approach_cache = None
        self.attempts = 0
        self.ready_at = 0
        self.target_since = None
        if self.patrol is not None:
            self.patrol.goal = self.patrol.goal_block = None
            self.patrol.route_cache = self.patrol.route_cache_key = None
        if self.enabled:
            self.reason = 'portal atravessado; aguardando posicao do mapa de chegada'

    def approach_path(self, collision, player, target, blocked, now):
        key = (id(collision), self.target, frozenset(blocked), getattr(collision, 'forbidden', frozenset()))
        cached = self.approach_cache
        if cached is not None and cached['key'] == key and math.dist(cached['goal'], target) <= 2:
            path = cached['path']
            if path and collision.line_clear(cached['goal'], target) and tuple(player) in path[:-1]:
                return path[path.index(tuple(player)):]
            if path is None and now < cached['retry_at'] and tuple(player) == cached['origin']:
                return None
        path = collision.route(player, target, blocked, max_nodes=16000)
        self.approach_cache = dict(key=key, goal=tuple(target), origin=tuple(player), path=path, retry_at=now+.75)
        return path

    def behind_wall(self, collision, player, point, steps=None):
        """True when walking to point takes far more steps than the straight distance (or no
        route at all): the monster is on the other side of a wall."""
        straight = max(abs(point[0]-player[0]), abs(point[1]-player[1]))
        if steps is None:
            path = collision.route(player, point, max_nodes=8000)
            if not path:
                return True
            steps = len(path)-1
        return steps > straight+max(self.WALL_DETOUR, straight)

    def walled(self, identity, now):
        """Found across a wall a moment ago: not picked again (even with target deferral off),
        which made the hunt drop and re-pick it every tick while standing still."""
        check = self.wall_checks.get(identity)
        return bool(check and check[3] and now < check[0])

    def refresh_wall_targets(self, candidates, collision, player, now):
        """A wall classification belongs to positions, never permanently to an ID."""
        if collision is None or player is None:
            return
        collision = collision.plain() if hasattr(collision, 'plain') else collision
        for entity in candidates:
            identity = entity['entity_id']
            cached = self.wall_checks.get(identity)
            if not cached or not cached[3]:
                continue
            point = tuple((entity.get('attack_positions') or [entity.get('effective_position', entity['position'])])[0])
            clear = collision.line_clear(player, point)
            if clear or math.dist(cached[1], player) > 3 or math.dist(cached[2], point) > 3:
                self.wall_checks.pop(identity, None)
                self.excluded_until.pop(identity, None)
                self.record('target_wall_recheck', target_id=identity, line_clear=clear)

    def reachable_targets(self, candidates, collision, player, now):
        """Candidates in order of preference, leaving out the ones behind a wall."""
        if collision is None:
            return candidates
        collision = collision.plain() if hasattr(collision, 'plain') else collision  # skill areas on the floor and portal cells are not walls
        result, checked = [], 0
        for e in candidates:
            point = tuple((e.get('attack_positions') or [e.get('destination') or e.get('effective_position', e['position'])])[0])
            cached = self.wall_checks.get(e['entity_id'])
            if collision.line_clear(player, point):
                wall = False  # nothing in between: no route to measure
                self.wall_checks.pop(e['entity_id'], None)
            elif (cached and now < cached[0] and math.dist(cached[1], player) <= 3 and math.dist(cached[2], point) <= 3):
                wall = cached[3]
            elif checked >= self.WALL_CHECKS:
                continue  # expensive checks are bounded; still inspect later clear-line targets
            else:
                checked += 1
                wall = self.behind_wall(collision, player, point)
                self.wall_checks[e['entity_id']] = (now+2, tuple(player), point, wall)
                if wall:
                    self.record('target_behind_wall', target_id=e['entity_id'], position=list(point))
            if not wall:
                result.append(e)
        if len(self.wall_checks) > 200:
            self.wall_checks = {i: c for i, c in self.wall_checks.items() if c[0] > now}
        return result

    def replan_action(self, now, reason, action=None):
        if action and action.get('purpose') == 'patrol' and self.patrol is not None and action.get('origin'):
            # Refused before sending (blocked cells, route changed): the same step is not proposed again.
            self.patrol.failed(action['origin'], action['destination'], now)
            self.patrol.route_cache_key = self.patrol.route_cache = None
        self.pending = None
        self.ready_at = now+.05
        self.reason = 'recalculando aproximacao: '+reason
        self.record('action_replanned', target_id=self.target, reason=reason)

    def engage(self, target_id, now):
        # A failed route puts the entity aside briefly. Repeated incoming attack packets
        # must not clear that deferral and reacquire the same unreachable target each tick.
        if now < self.excluded_until.get(target_id, 0):
            return
        if self.engaged != target_id:
            self.record('target_engaged', target_id=target_id)
        self.engaged = target_id
        self.engaged_until = now+self.ENGAGED_GIVE_UP
        self.excluded_until.pop(target_id, None)

    def record(self, kind, **details):
        if kind in ('target_switched', 'target_ignored', 'skill_retry', 'skill_confirmed', 'movement_failed'):
            self.last_decision = {'kind': kind, **details}
        self.diagnostics.append({'kind': kind, **details})
        self.diagnostics = self.diagnostics[-100:]

    def drain_diagnostics(self):
        result, self.diagnostics = self.diagnostics, []
        return result

    def start(self):
        self.awaiting_map = False
        self.approach_cache = None
        self.enabled = True
        self.skill_disabled = False
        self.skill_failures = 0
        self.skill_attempts.clear()
        self.excluded_until.clear()
        self.blocked_until.clear()
        self.reason = ''
        self.target = self.pending = None
        self.attempts = 0
        self.ready_at = 0
        self.target_since = None
        self.engaged = None
        self.aggressors.clear()

    def pause(self, reason):
        self.awaiting_map = False
        self.approach_cache = None
        self.enabled = False
        self.reason = reason
        self.pending = None
        self.target = None
        self.engaged = None

    def snapshot(self):
        now = time.monotonic()
        phase = 'pausada' if not self.enabled else 'selecionando alvo'
        if self.enabled and self.pending:
            phase = {'move': 'patrulhando' if self.pending.get('purpose') == 'patrol' else 'aproximando do alvo',
                     'skill': 'aguardando resposta da Kunai', 'attack': 'aguardando resposta do ataque'}[self.pending['kind']]
        elif self.enabled and self.target is None and self.patrol is not None:
            phase = 'procurando alvos por setores'
        wait_until = self.pending.get('deadline', self.pending.get('wait_until', now)) if self.pending else self.ready_at
        return {'auto_attacks': self.auto_attacks, 'combat_mode': 'aproximar para ataque basico' if self.auto_attacks else 'manter alcance das habilidades',
                'enabled': self.enabled, 'reason': self.reason, 'target_id': self.target,
                'pending': self.pending, 'confirmed_attacks': self.confirmed_attacks,
                'move_commands': self.moves, 'search_radius': self.SEARCH_RADIUS,
                'approach_steps': self.attempts, 'temporarily_ignored': list(self.excluded_until),
                'navigation': self.navigation, 'movement_corrections': self.movement_corrections,
                'movement_failures': self.movement_failures,
                'patrol': self.patrol.snapshot() if self.patrol else None,
                'skills_enabled': self.use_skills and not self.skill_disabled,
                'skill_reason': self.skill_reason, 'confirmed_skills': self.confirmed_skills,
                'phase': phase, 'wait_seconds': round(max(0, wait_until-now), 2),
                'skill_cooldown_seconds': round(max(0, self.skill_ready_at-now), 2),
                'target_skill_failures': self.skill_attempts.get(self.target, 0),
                'last_decision': self.last_decision, 'engaged_target_id': self.engaged}

    def step_back(self, player, monster, combat_range, collision, walk_speed_ms, blocked=frozenset()):
        """Run from a monster inside the skill distance: the free spot farthest from it, ideally
        still inside skill range. Walls are walked around by trying other directions."""
        dx, dy = player[0]-monster[0], player[1]-monster[1]
        length = math.hypot(dx, dy)
        want = max(1, combat_range-1)
        best = None
        # Search the nearby grid, including slopes such as 3/4, so a diagonal
        # retreat can actually end at range-1 rather than oscillating around it.
        for ox in range(-4,5):
            for oy in range(-4,5):
                destination = [player[0]+ox, player[1]+oy]
                if (ox == 0 and oy == 0) or tuple(destination) in blocked:
                    continue
                distance = math.dist(destination, monster)
                if not length < distance <= want:
                    continue
                if collision is not None and (not collision.segment(player, destination, blocked, max_steps=4)
                                               or not collision.line_clear(destination, monster)):
                    continue
                heading = (ox*dx+oy*dy)/max(1, math.hypot(ox,oy))
                clearance = collision.clearance(destination) if collision is not None else 0
                score = (distance, heading, clearance, -max(abs(ox),abs(oy)))
                if best is None or score > best[0]:
                    best = (score, destination)
        if collision is not None and (best is None or self.room_behind(best[1], monster, collision, blocked) < self.ROOM_NEEDED):
            # Wall (or portal area) behind: backing up further would corner the character.
            # Circle to open ground that still keeps the monster in skill range.
            spot = self.reposition(player, monster, want, collision, blocked)
            if spot is not None:
                self.reason = 'sem espaço para recuar: reposicionando o kite para uma área livre'
                return self.retreat_move(player, spot, collision, walk_speed_ms, reposition=True)
        if best is None:
            return None
        self.reason = 'monstro dentro da distância: correndo para manter o alcance das habilidades'
        return self.retreat_move(player, best[1], collision, walk_speed_ms)

    ROOM_NEEDED = 6  # free cells farther from the monster around a retreat spot
    REPOSITION_STEPS = 12

    @staticmethod
    def room_behind(cell, monster, collision, blocked=frozenset()):
        """How much ground is left to keep running from this cell: free cells of the 7x7 box at
        least one cell farther from the monster (side cells along a wall do not count)."""
        base = math.dist(cell, monster)
        return sum(1 for ox in range(-3, 4) for oy in range(-3, 4)
                   if math.dist((cell[0]+ox, cell[1]+oy), monster) > base+1
                   and (cell[0]+ox, cell[1]+oy) not in blocked and collision.walkable((cell[0]+ox, cell[1]+oy)))

    def reposition(self, player, monster, want, collision, blocked=frozenset()):
        """Walkable path (never brushing the monster) to the nearby spot with room to keep kiting."""
        start = tuple(player)
        parents, queue, best = {start: None}, deque([(start, 0)]), None
        while queue:
            point, depth = queue.popleft()
            distance = math.dist(point, monster)
            if depth and distance >= 2 and collision.line_clear(point, monster):
                room = self.room_behind(point, monster, collision, blocked)
                if room >= self.ROOM_NEEDED:
                    score = (round(min(distance, want)), room, collision.clearance(point), -depth)
                    if best is None or score > best[0]:
                        best = (score, point)
            if depth == self.REPOSITION_STEPS:
                continue
            for dx, dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                nxt = (point[0]+dx, point[1]+dy)
                if nxt not in parents and math.dist(nxt, monster) >= 2 and collision.edge(point, nxt, blocked):
                    parents[nxt] = point
                    queue.append((nxt, depth+1))
        if best is None:
            return None
        path, point = [], best[1]
        while point is not None:
            path.append(point)
            point = parents[point]
        path.reverse()
        # The farthest waypoint a single straight move (up to 4 cells) reaches safely.
        for step in range(min(4, len(path)-1), 0, -1):
            if collision.segment(start, path[step], blocked, max_steps=4):
                return list(path[step])
        return None

    def retreat_move(self, player, destination, collision, walk_speed_ms, reposition=False):
        steps = max(abs(destination[i]-player[i]) for i in (0, 1))
        seconds = max(50, min(walk_speed_ms, 2000))/1000
        duration = (steps+.4*min(abs(destination[i]-player[i]) for i in (0,1)))*seconds
        action = {'kind': 'move', 'target_id': self.target, 'destination': list(destination), 'wait_seconds': duration,
                  'origin': list(player), 'collision_route': collision is not None, 'seconds_per_step': duration/steps,
                  'purpose': 'keep_distance'}
        if reposition:
            action['reposition'] = True
        return action

    def retry_skill(self, now, reason):
        target_id = self.pending['target_id']
        self.skill_attempts[target_id] = self.skill_attempts.get(target_id, 0)+1
        self.skill_failures += 1
        count = self.skill_attempts[target_id]
        self.record('skill_retry', target_id=target_id, failures=count, reason=reason)
        self.skill_reason = f'{reason}; tentativa {count}/{self.SKILL_ATTEMPTS}'
        if count >= self.SKILL_ATTEMPTS:
            self.abandon(now, f'habilidade sem sucesso após {self.SKILL_ATTEMPTS} tentativas; alvo adiado por {self.TARGET_DEFER} segundos')
        else:
            self.pending = None
        self.ready_at = now+.25

    def skill_action(self, state, target_id, now):
        if not self.use_skills or self.skill_disabled:
            return None
        metadata = next((s for s in state.get('learned_skills', []) if s['skill_id'] == 524), None)
        if metadata is None or metadata['level'] < 10 or metadata['range'] < 1:
            self.skill_reason = 'Kunai nível 10 ou alcance não confirmado pelo servidor'
            return None
        if state.get('player_sp') is None or state['player_sp'] < metadata['sp_cost']:
            self.skill_reason = 'SP desconhecido ou insuficiente'
            return None
        if now < self.skill_ready_at:
            self.skill_reason = 'intervalo entre habilidades'
            return None
        self.skill_reason = 'Arremessar Kunai nível 10 disponível'
        return {'kind': 'skill', 'target_id': target_id, 'skill_id': 524, 'level': 10}

    def observe(self, events, player_id, now, movement_motion=None):
        events = [{**e, 'kind': 'player_move'} if e['kind'] == 'move' and e.get('entity_id') == player_id and e.get('destination') is not None else e for e in events]
        own_cast_response = player_id is not None and any(
            e.get('source_id')==player_id and (e['kind'] in ('skill_cast','skill_damage')
                or e['kind']=='skill_no_damage' and e.get('success') is True) for e in events)
        for event in events:
            kind = event['kind']
            if kind in ('map_change', 'map_transfer'):
                self.engaged = None
                self.aggressors.clear()
            elif kind == 'remove':
                self.aggressors.pop(event.get('entity_id'), None)
                if event.get('entity_id') == self.engaged:
                    self.engaged = None
            elif kind in ('skill_damage', 'normal_attack') and player_id is not None:
                if event.get('source_id') == player_id and event.get('target_id') not in (None, player_id):
                    self.engage(event['target_id'], now)
                elif event.get('target_id') == player_id and event.get('source_id') is not None:
                    self.aggressors[event['source_id']] = now
        if self.pending is None:
            return
        for event in events:
            if self.pending is None:
                break
            if (event['kind'] in ('move', 'position') and event.get('entity_id') == self.target
                and event.get('entity_id') != player_id and now-self.last_target_motion >= 1):
                self.last_target_motion = now
                self.record('target_motion', target_id=self.target, position=event.get('position'),
                            destination=event.get('destination'))
            if event['kind'] == 'remove' and event.get('entity_id') == self.pending['target_id']:
                if self.pending['kind'] in ('attack', 'skill'):
                    self.pending = None
                self.target = None
                self.ready_at = now
                continue
            if self.pending['kind'] in ('attack', 'skill'):
                using_skill = self.pending['kind'] == 'skill'
                if using_skill and event['kind'] == 'skill_failed' and event['skill_id'] == self.pending['skill_id']:
                    self.record('skill_failed', skill_id=event['skill_id'], cause_raw=event.get('cause_raw'))
                    self.retry_skill(now, 'servidor recusou a habilidade')
                elif (event['kind'] == ('skill_damage' if using_skill else 'normal_attack')
                    and event['source_id'] == player_id and event['target_id'] == self.pending['target_id']
                    and (not using_skill or (event['skill_id'] == self.pending['skill_id']
                                            and event['level'] == self.pending['level']))):
                    self.confirmed_attacks += 1
                    if using_skill:
                        self.skill_failures = 0
                        self.skill_attempts.pop(event['target_id'], None)
                        self.confirmed_skills += 1
                        self.record('skill_confirmed', target_id=event['target_id'], skill_id=event['skill_id'],
                                    damage_raw=event.get('damage_raw'))
                    self.pending = None
                    self.ready_at = now+.05
                    self.attempts = 0
            elif event['kind'] == 'position' and event.get('entity_id') == player_id:
                position = event['position']
                if position == self.pending['destination']:
                    self.pending['movement_acknowledged'] = True
                    self.pending['arrival_confirmed'] = True
                    self.pending['wait_until'] = now
                elif self.pending.get('origin') is not None:
                    origin, destination = self.pending['origin'], self.pending['destination']
                    progressed = (math.dist(position, origin) >= 1
                                  and math.dist(position, destination) < math.dist(origin, destination))
                    self.movement_corrections += 1
                    self.record('movement_correction', target_id=self.pending['target_id'],
                                origin=origin, destination=destination, position=position,
                                partial_progress=progressed)
                    if progressed:
                        self.pending = None
                        self.ready_at = now+.05
                    elif position == origin and own_cast_response:
                        # The server stopped the walk on this cell to execute our skill. It has
                        # not proved the next cell is a wall: retry the same path after the cast,
                        # instead of adding fake obstacles and zigzagging around every skill.
                        self.record('movement_interrupted_by_skill', target_id=self.pending['target_id'],
                                    origin=origin, destination=destination, position=position)
                        self.pending = None
                        self.ready_at = now+.05
                    else:
                        self.fail_movement(now, 'correção própria sem avanço; alvo ignorado', position)
            elif event['kind'] == 'player_move' and self.pending.get('origin') is not None:
                origin, requested = self.pending['origin'], self.pending['destination']
                destination = event.get('destination')
                if destination == requested:
                    if not self.pending['movement_acknowledged']:
                        self.pending['wait_until'] = now+self.pending['wait_seconds']
                    self.pending['movement_acknowledged'] = True
                elif (destination and event.get('position') == origin and destination != origin
                      and all(min(origin[i], requested[i]) <= destination[i] <= max(origin[i], requested[i])
                              for i in (0, 1))
                      and math.dist(destination, requested) < math.dist(origin, requested)):
                    self.movement_corrections += 1
                    self.record('movement_shortened', target_id=self.pending['target_id'],
                                origin=origin, destination=requested, accepted_destination=destination)
                    self.pending['destination'] = list(destination)
                    self.pending['movement_acknowledged'] = True
                    steps = max(abs(destination[i]-origin[i]) for i in (0, 1))
                    self.pending['wait_until'] = now+steps*self.pending.get('seconds_per_step', .4)
            elif ((event['kind'] == 'player_move' and event.get('destination') == self.pending['destination'])
                  or (event['kind'] == 'position' and event.get('entity_id') == player_id
                      and event.get('position') == self.pending['destination'])):
                self.pending['movement_acknowledged'] = True
                # A position correction proves arrival; a route acknowledgement does not.
                if event['kind'] == 'position':
                    self.pending['wait_until'] = now
            if (self.pending is not None and self.pending['kind'] == 'move'
                and event['kind'] == 'player_move' and self.pending['movement_acknowledged'] and not self.pending.get('arrival_confirmed')
                and movement_motion and list(movement_motion.get('destination', [])) == self.pending['destination']
                and movement_motion.get('at', now+1) <= now+.05
                and math.isfinite(movement_motion.get('at', float('nan')))
                and math.isfinite(movement_motion.get('duration', float('nan')))
                and movement_motion.get('duration', -1) >= 0):
                # This is the observer's accepted server path/start, not another full
                # walk duration beginning when the ACK happens to reach the bot.
                self.pending['wait_until'] = max(self.pending['sent_at'], movement_motion['at']+movement_motion['duration'])

    def fail_movement(self, now, reason, position=None):
        action = self.pending
        if self.patrol is not None:
            self.patrol.failed(action.get('origin'), action['destination'], now)
        self.blocked_until[tuple(action["destination"])] = now+2
        self.movement_failures += 1
        self.record('movement_failed', target_id=action['target_id'], reason=reason,
                    origin=action.get('origin'), destination=action['destination'], position=position)
        self.reason = reason+'; recalculando rota para o mesmo alvo'
        self.pending = None
        self.ready_at = now+.15

    UNREACHABLE_DEFER = 8.0  # s: no way to it / across a wall, even with failed-target deferral off
    HAZARD_RETURN = 1.0  # s: a monster cut off by a skill area on the floor is taken again this soon
    HAZARD_SWITCH_GAP = 3.0  # s between two switches caused by skill areas on the floor
    hazard_switch_at = -1e9

    def abandon(self, now, reason, defer=None, *, force=False, exact=False):
        if not force and self.target is not None and self.target == self.engaged:
            if now < self.engaged_until:
                # Transient failures (cell changed, line blocked, retries) never drop the fight.
                self.record('engaged_target_kept', target_id=self.target, reason=reason)
                self.reason = reason+'; mantendo o monstro em combate ate finalizar'
                self.skill_attempts.pop(self.target, None)
                self.pending = None
                self.attempts = 0
                self.ready_at = now+.2
                return
            self.engaged = None
        elif force and self.target is not None and self.target == self.engaged:
            self.engaged = None
            self.aggressors.pop(self.target, None)
        if self.target is not None:
            # With deferral off (TARGET_DEFER 0) an unreachable monster was picked again on the next
            # tick, 2600 times in 30 minutes, the character standing still (2026-11-05).
            self.excluded_until[self.target] = now+(defer if exact and defer is not None else max(self.TARGET_DEFER, defer or 0))
            self.record('target_ignored', target_id=self.target, reason=reason)
        self.reason = reason
        self.target = self.pending = None
        self.attempts = 0
        self.target_since = None
        self.ready_at = now

    def sent(self, action, now):
        self.last_action_at = now
        self.pending = {**action, 'sent_at': now}
        if action['kind'] == 'move':
            self.pending['movement_acknowledged'] = False
            self.pending['wait_until'] = now+action['wait_seconds']
            self.pending['ack_deadline'] = now+.9
            self.attempts += 1
            self.moves += 1
        else:
            self.pending['deadline'] = now+(self.SKILL_RESPONSE_TIMEOUT if action['kind'] == 'skill' else self.ATTACK_RESPONSE_TIMEOUT)
            if action['kind'] == 'skill':
                self.skill_ready_at = now+self.SKILL_INTERVAL

    IDLE_LIMIT = 2  # seconds hunting without sending anything before the stall breaker acts

    def plan(self, state, now, walk_speed_ms=400, collision=None):
        self.navigation = 'rotas por colisão' if collision is not None else 'colisão indisponível; aproximação anterior'
        if not self.enabled:
            self.last_action_at = None
            return None
        self.refresh_wall_targets(state.get('recent_entities', []), collision, state.get('player_position'), now)
        if getattr(self, 'last_action_at', None) is None or self.target is not None or self.engaged is not None:
            self.last_action_at = now  # fighting is not standing still (skills go through the rotation)
        if self.pending is None and now-self.last_action_at > self.IDLE_LIMIT:
            # Never stand still while hunting (players around are handled before this is called):
            # forget recent failures and blocks and pick a fresh route.
            self.record('stall_breaker', seconds=round(now-self.last_action_at, 1))
            self.blocked_until.clear()
            if self.patrol is not None:
                recovered = self.patrol.recover_stall(state.get('player_position'), now)
                self.record('patrol_stall_recovered', reachable=bool(recovered),
                            position=state.get('player_position'))
            self.last_action_at = now
        if (state['state'] != 'tracking' or not state['player_position_recent']
            or state.get('player_position') is None):
            if self.awaiting_map:
                self.reason = 'aguardando dados atuais depois do portal'
                return None
            self.pause('posição própria ou leitura indisponível')
            return None
        self.awaiting_map = False
        if self.pending:
            if self.pending['kind'] in ('attack', 'skill'):
                if now >= self.pending['deadline']:
                    if self.pending['kind'] == 'skill':
                        self.record('skill_timeout', target_id=self.pending['target_id'], skill_id=self.pending['skill_id'])
                        self.retry_skill(now, 'habilidade sem confirmação')
                    else:
                        self.pending = None
                        self.reason = 'ataque sem resposta; mantendo o mesmo alvo'
                        self.ready_at = now+.2
                else:
                    return None
            if self.pending and now < self.pending['wait_until']:
                if (not self.pending['movement_acknowledged']
                    and now >= self.pending['ack_deadline']):
                    self.fail_movement(now, 'movimento sem confirmação em 0,9 segundo')
                return None
            if self.pending and not self.pending['movement_acknowledged']:
                self.fail_movement(now, 'movimento sem confirmação; alvo temporariamente ignorado')
            elif self.pending and self.pending.get('origin') == state['player_position']:
                self.fail_movement(now, 'sem progresso na caminhada; procurando outra rota', state['player_position'])
            if self.pending and self.patrol is not None:
                self.patrol.reached(state['player_position'], self.pending.get('origin'))
            self.pending = None
        if now < self.ready_at:
            return None
        for identity, deadline in list(self.excluded_until.items()):
            if deadline <= now:
                self.skill_attempts.pop(identity, None)
        self.excluded_until = {i: t for i, t in self.excluded_until.items() if t > now}
        entities = {e['entity_id']: e for e in state['recent_entities']
                    if e['entity_id'] not in self.excluded_until
                    and (not self.walled(e['entity_id'], now) or e['entity_id'] in self.aggressors)}
        player = state['player_position']
        self.blocked_until = {p: t for p, t in self.blocked_until.items() if t > now}
        blocked = set(self.blocked_until)
        if self.priority_target in entities and self.engaged != self.priority_target:
            self.engage(self.priority_target, now)
        if self.engaged is not None and self.engaged not in entities:
            self.engaged = None  # removed from view or filtered out
        if self.engaged is None:
            # A selected monster hitting us becomes the fight to finish.
            attackers = [i for i in sorted(self.aggressors, key=self.aggressors.get, reverse=True)
                         if i in entities and now-self.aggressors[i] <= 10]
            if attackers and self.target not in attackers:
                self.engage(attackers[0], now)
        if self.engaged is not None and self.target != self.engaged:
            self.target, self.attempts, self.target_since, self.pending = self.engaged, 0, now, None
        if not self.auto_movement and self.target is not None and self.target != self.priority_target:
            # The player moves the character: never stay on a target left behind, take the nearest
            # each time (the one the skills can reach), instead of waiting for one far away.
            self.target = None
        entity = entities.get(self.target)
        def distance_to(e):
            return math.dist(player, (e.get('attack_positions') or [e.get('destination') or e.get('effective_position', e['position'])])[0])
        heading = getattr(self.patrol, 'heading', None) if self.auto_movement and self.patrol is not None else None

        def alignment(e):
            """1 straight ahead on the patrol heading, -1 right behind, 0 sideways or no heading."""
            if not heading or not any(heading):
                return 0
            point = (e.get('attack_positions') or [e.get('destination') or e.get('effective_position', e['position'])])[0]
            offset = (point[0]-player[0], point[1]-player[1])
            size = math.hypot(*offset)*math.hypot(*heading)
            return (offset[0]*heading[0]+offset[1]*heading[1])/size if size else 0

        def weighed(e):
            # Monsters behind the sweep count up to twice as far: the hunt goes on forward instead
            # of running back over covered ground, which made the patrol loop around.
            distance = distance_to(e)
            return distance*(1+max(0, -alignment(e))) if distance > 4 else distance
        nearby = [e for e in entities.values() if distance_to(e) <= self.SEARCH_RADIUS
                  and not (alignment(e) < -.3 and distance_to(e) > self.SEARCH_RADIUS/2)]
        def rank(e):
            return self.target_priority.get(e.get('species_id'), 1000)
        if (entity is not None and self.target_priority and self.target != self.engaged
                and self.target not in self.aggressors
                and any(rank(e) < rank(entity) for e in nearby)):
            entity = None  # a monster that must go first came into reach: switch to it
        if entity is None and nearby:
            nearby = self.reachable_targets(sorted(nearby, key=lambda e: (rank(e), weighed(e), e['entity_id'])),
                                            collision, player, now)
        closest = min(nearby, key=lambda e: (rank(e), weighed(e), e['entity_id'])) if nearby else None
        # REDE-57: keep a visible valid target until removal; proximity does not override it.
        if entity is None:
            if not nearby:
                self.target = None
                # Everything in view was weighed and declined (behind a wall, behind the sweep, too far,
                # put aside): the relay must not stop this patrol step for one of them.
                self.passed_over = {e['entity_id'] for e in state['recent_entities']}
                if self.auto_movement and self.patrol is not None:
                    # @showmobs supplies a real monster coordinate; walk to that cell through the
                    # collision map, then resume the persistent coverage circuit.
                    focus = (state.get('showmobs_goal') or {}).get('position')
                    # @showmobs failed here: sweep the whole map in one planned walk (like the mazes).
                    self.patrol.linear = bool(state.get('showmobs_failed'))
                    if focus:
                        self.patrol.update_focus(focus, now)
                    self.patrol.search_destination = None  # the coverage cycle owns exploration
                    self.reason = 'patrulhando setores sem alvo'
                    return self.patrol.plan(player, now, walk_speed_ms, collision)
                if not self.excluded_until:
                    self.reason = f'aguardando monstro recente dentro de {self.SEARCH_RADIUS} células'
                return None
            entity = closest
            self.target = entity['entity_id']
            self.attempts = 0
            self.target_since = now
            self.reason = ''
        actual_position = entity.get('effective_position', entity['position'])
        chase_position = (entity.get('attack_positions') or [entity.get('destination') or actual_position])[-1]
        # REDE-53: lead the route by estimated approach time, but range checks
        # below still use the current/near-future attack positions.
        range_positions = entity.get('attack_positions') or [actual_position, chase_position]
        speed = entity.get('walk_speed_ms')
        if entity.get('destination') and speed and state.get('engagement_range'):
            destination = entity['destination']
            remaining = math.dist(actual_position, destination)
            approach = max(0, math.dist(player, actual_position)-state['engagement_range'])*walk_speed_ms/1000
            lead_cells = min(remaining, approach*1000/speed)
            fraction = lead_cells/remaining if remaining else 1
            chase_position = [round(actual_position[i]+(destination[i]-actual_position[i])*fraction) for i in (0, 1)]
            if collision is not None and not collision.walkable(chase_position):
                chase_position = actual_position
        distance = math.dist(player, chase_position)
        metadata = next((s for s in state.get('learned_skills', []) if s['skill_id'] == 524), {})
        wants_skill = (self.use_skills and not self.skill_disabled and metadata.get('level', 0) >= 10
                       and metadata.get('range', 0) >= 1 and state.get('player_sp') is not None
                       and state['player_sp'] >= metadata.get('sp_cost', 65535))
        combat_range = state.get('engagement_range', min(6, metadata['range']) if wants_skill else 2)
        closest = min(math.dist(player, point) for point in range_positions)
        # Three separate choices: basic attacks between skills (auto_attacks), walking up to the
        # basic-attack range (melee_approach) and running back to keep the skills' distance (kite).
        # Approach and kite exclude each other; with both off the bot stops at the skills' range.
        melee = self.melee_approach and not wants_skill  # the old Kunai-only mode keeps its range
        if melee:
            combat_range = self.MELEE_RANGE  # go hand to hand: basic attacks between the skills
        # The configured rotation supplies engagement_range and handles shooting while
        # retreating. The legacy Kunai planner must reach its cast/response checks first;
        # otherwise a nearby target always produces a walk instead of a ready skill.
        elif (self.auto_movement and self.kite and combat_range >= 3
              and (collision is None or all(collision.line_clear(player, point) for point in range_positions))):
            spacing = max(1, combat_range-1)
            if closest < spacing-.25:
                retreat = self.step_back(player, actual_position, combat_range, collision, walk_speed_ms, blocked)
                if retreat is not None:
                    return retreat
            combat_range = spacing
        in_range = max(math.dist(player, point) for point in range_positions) <= combat_range
        if melee and collision is not None:
            in_range = in_range and all(collision.melee_reachable(player, point) for point in range_positions)
        # With collision data, retain adjacent-cell combat until ranged line-of-sight is supported.
        if in_range and (collision is None or all(collision.line_clear(player, point) for point in range_positions)):
            skill_action = self.skill_action(state, self.target, now)
            if wants_skill:
                if entity.get('position_age_seconds', 0) > 1.5 and not entity.get('position_usable', False):
                    self.skill_reason = 'posição do alvo antiga; procurando alvo atualizado'
                    self.abandon(now, self.skill_reason)
                    return None
                if skill_action is None:
                    return None
                return skill_action
            # The server takes the last step of an attack request: with the movement in the player's
            # hands the target must already be right next to the character.
            reach = self.MELEE_RANGE if self.auto_movement else 1.5
            adjacent = (max(math.dist(player, point) for point in range_positions) <= reach
                        and (collision is None or all(collision.melee_reachable(player, point) for point in range_positions)))
            if not self.auto_attacks or not adjacent:
                # Without melee approach a basic attack is only sent to a target already in reach:
                # the server would otherwise walk the character up to it.
                self.reason = ('mantendo distância; só habilidades' if self.kite or not self.auto_attacks
                               else 'mantendo alcance; aguardando habilidade disponivel')
                return None
            return {'kind': 'attack', 'target_id': self.target}
        if not self.auto_movement:
            self.reason = 'Movimentação automática desativada; aguardando alvo ao alcance'
            return None
        path = self.approach_path(collision, player, chase_position, blocked, now) if collision else None
        if collision and not path and blocked:
            self.reason = 'rota temporariamente bloqueada; mantendo alvo'
            self.ready_at = now+.5
            return None
        if (collision and not path and getattr(collision, 'hazard_cells', None)
                and collision.plain().route(player, chase_position, blocked, max_nodes=8000)):
            # Enemy skill areas on the floor (poison...) are what close the way: another monster
            # really reachable is taken now and this one again a second later; otherwise get as close
            # as the area allows. One switch every few seconds at most: monsters all beyond the
            # area made it hop between them without hitting anything (ra_fild03 2026-11-06).
            if now-self.hazard_switch_at >= self.HAZARD_SWITCH_GAP:
                others = sorted((e for e in state['recent_entities'] if e['entity_id'] != self.target
                                 and self.excluded_until.get(e['entity_id'], 0) <= now and not self.walled(e['entity_id'], now)
                                 and math.dist(player, e.get('effective_position', e['position'])) <= self.SEARCH_RADIUS),
                                key=lambda e: math.dist(player, e.get('effective_position', e['position'])))[:3]
                if any(collision.route(player, e.get('effective_position', e['position']), blocked, max_nodes=4000)
                       for e in others):
                    self.hazard_switch_at = now
                    self.abandon(now, 'alvo atras de area de habilidade no chao; trocando de alvo',
                                 defer=self.HAZARD_RETURN, force=True, exact=True)
                    return None
            path = collision.route(player, chase_position, blocked, max_nodes=8000, partial=True)
            if not path or len(path) < 2:
                self.reason = 'alvo cercado por area de habilidade no chao; aguardando'
                self.ready_at = now+.3
                return None
        if collision and not path:
            # The engaged-target hold is useful for transient packet/path failures, but
            # an impossible route is terminal for this attempt: clear the lock so the
            # hunt can choose a reachable target or resume patrol immediately.
            self.abandon(now, 'sem rota livre até o alvo; procurando outro',
                         defer=self.UNREACHABLE_DEFER, force=True)
            return None
        if (collision and self.target not in self.aggressors and not collision.line_clear(player, chase_position)
                and not self.reachable_targets([entity], collision, player, now)):
            # Unless it is fighting us, a monster across a wall is left for when the patrol gets there.
            # Measured without the cells blocked by failed steps (a detour around them is no wall).
            self.abandon(now, 'monstro do outro lado da parede; procurando outro',
                         defer=self.UNREACHABLE_DEFER, force=True)
            return None
        # REDE-46: route may contain only the origin when the predicted target
        # is adjacent but its observed position still lies outside combat range.
        if collision and len(path) < 2:
            self.reason = 'destino previsto adjacente; aguardando movimento do alvo'
            self.ready_at = now+.05
            return None
        if distance == 0:
            self.abandon(now, 'destino estimado alcançado sem posição atual; procurando outro alvo')
            return None
        dx, dy = chase_position[0]-player[0], chase_position[1]-player[1]
        reach = min(4, max(1, distance-combat_range))
        destination = [round(player[0]+dx/distance*reach), round(player[1]+dy/distance*reach)]
        if collision:
            # REDE-51: pull the path across free ground instead of emitting every A* bend.
            index = 1
            for candidate in range(2, min(12, len(path))):
                if collision.segment(player, path[candidate], blocked, max_steps=4, wall_margin=min(3, collision.clearance(path[1]))):
                    index = candidate
            # Stop the current segment when ranged combat becomes possible.
            for step in range(1, index+1):
                if (max(math.dist(path[step], point) for point in range_positions) <= combat_range
                    and (not melee or all(collision.melee_reachable(path[step], point) for point in range_positions))
                    and collision.segment(player, path[step], blocked, max_steps=4)
                    and collision.line_clear(path[step], actual_position) and collision.line_clear(path[step], chase_position)):
                    index = step
                    break
            destination = list(path[index])
        elif tuple(destination) in blocked:
            self.reason = 'aguardando confirmação de avanco; mantendo o alvo'
            self.ready_at = max(now+.2, self.blocked_until[tuple(destination)])
            return None
        steps = max(abs(destination[0]-player[0]), abs(destination[1]-player[1]))
        # Wait is a conservative estimate, not proof of arrival. A server move
        # response is required; failure to reach attack range is bounded.
        diagonal_factor = 1+.4*min(abs(destination[i]-player[i]) for i in (0, 1))/steps
        duration = steps*max(50, min(walk_speed_ms, 2000))/1000*diagonal_factor
        return {'kind': 'move', 'target_id': self.target, 'destination': destination,
                'wait_seconds': duration, 'origin': list(player), 'collision_route': collision is not None,
                'seconds_per_step': max(50, min(walk_speed_ms, 2000))/1000*diagonal_factor}
