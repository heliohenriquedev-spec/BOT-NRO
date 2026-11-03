"""REDE-30: decisões de caça por ID. Sem teclado, mouse ou acesso à rede."""
from __future__ import annotations

import math
import time


class PacketHunt:
    SEARCH_RADIUS = 28
    MAX_STEPS = 12
    SKILL_INTERVAL = .5
    SKILL_RESPONSE_TIMEOUT = 1.5
    SKILL_ATTEMPTS = 3
    TARGET_DEFER = 8
    SWITCH_DISTANCE = 6
    SWITCH_SAVING = 3
    SWITCH_RATIO = .65
    # REDE-62: a monster we hit (or that hits us) is kept until it dies or leaves the
    # client view; only this long without any confirmed damage releases it.
    ENGAGED_GIVE_UP = 15
    # REDE-84: basic attacks on: walk up to the target and attack it between skills.
    # Basic attacks off: run away whenever the monster comes inside the skill distance.
    MELEE_RANGE = 2  # the server itself takes the last step of an attack request
    KITE_MARGIN = 1  # flee when the monster is closer than skill range minus this
    ATTACK_RESPONSE_TIMEOUT = 1.2  # a basic attack is answered well within this; then the next one goes

    def __init__(self, patrol=False, patrol_step=8, use_skills=False):
        self.auto_attacks = True
        self.use_skills = use_skills
        self.skill_disabled = False
        self.skill_ready_at = 0
        self.skill_reason = 'aguardando dados do servidor'
        self.confirmed_skills = 0
        self.skill_failures = 0
        self.skill_attempts = {}
        from .packet_patrol import PacketPatrol
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

    def replan_action(self, now, reason):
        self.pending = None
        self.ready_at = now+.05
        self.reason = 'recalculando aproximacao: '+reason
        self.record('action_replanned', target_id=self.target, reason=reason)

    def engage(self, target_id, now):
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
        if best is None:
            return None
        destination = best[1]
        steps = max(abs(destination[i]-player[i]) for i in (0, 1))
        seconds = max(50, min(walk_speed_ms, 2000))/1000
        duration = (steps+.4*min(abs(destination[i]-player[i]) for i in (0,1)))*seconds
        self.reason = 'monstro dentro da distância: correndo para manter o alcance das habilidades'
        return {'kind': 'move', 'target_id': self.target, 'destination': destination, 'wait_seconds': duration,
                'origin': list(player), 'collision_route': collision is not None, 'seconds_per_step': duration/steps,
                'purpose': 'keep_distance'}

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

    def observe(self, events, player_id, now):
        events = [{**e, 'kind': 'player_move'} if e['kind'] == 'move' and e.get('entity_id') == player_id and e.get('destination') is not None else e for e in events]
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
                    else:
                        self.fail_movement(now, 'correção própria sem avanço; alvo ignorado', position)
            elif event['kind'] == 'player_move' and self.pending.get('origin') is not None:
                origin, requested = self.pending['origin'], self.pending['destination']
                destination = event.get('destination')
                if destination == requested:
                    self.pending['movement_acknowledged'] = True
                    self.pending['wait_until'] = max(self.pending['wait_until'], now+self.pending['wait_seconds'])
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

    def fail_movement(self, now, reason, position=None):
        action = self.pending
        if self.patrol is not None:
            self.patrol.failed(action.get('origin'), action['destination'], now)
        self.blocked_until[tuple(action['destination'])] = now+8
        self.movement_failures += 1
        self.record('movement_failed', target_id=action['target_id'], reason=reason,
                    origin=action.get('origin'), destination=action['destination'], position=position)
        self.reason = reason+'; recalculando rota para o mesmo alvo'
        self.pending = None
        self.ready_at = now+.15

    def abandon(self, now, reason):
        if self.target is not None and self.target == self.engaged:
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
        if self.target is not None:
            self.excluded_until[self.target] = now+self.TARGET_DEFER
            self.record('target_ignored', target_id=self.target, reason=reason)
        self.reason = reason
        self.target = self.pending = None
        self.attempts = 0
        self.target_since = None
        self.ready_at = now

    def sent(self, action, now):
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

    def plan(self, state, now, walk_speed_ms=400, collision=None):
        self.navigation = 'rotas por colisão' if collision is not None else 'colisão indisponível; aproximação anterior'
        if not self.enabled:
            return None
        if (state['state'] != 'tracking' or not state['player_position_recent']
            or state.get('player_position') is None):
            self.pause('posição própria ou leitura indisponível')
            return None
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
                    if e['entity_id'] not in self.excluded_until}
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
        entity = entities.get(self.target)
        def distance_to(e):
            return math.dist(player, (e.get('attack_positions') or [e.get('destination') or e.get('effective_position', e['position'])])[0])
        nearby = [e for e in entities.values() if distance_to(e) <= self.SEARCH_RADIUS]
        closest = min(nearby, key=lambda e: (distance_to(e), e['entity_id'])) if nearby else None
        # REDE-57: keep a visible valid target until removal; proximity does not override it.
        if entity is None:
            if not nearby:
                self.target = None
                if self.patrol is not None:
                    search_goal = state.get('search_goal')
                    if collision is not None:
                        search_goal = None  # coverage cycle owns exploration; old sightings cannot reorder it
                    self.patrol.search_destination = search_goal['position'] if search_goal else None
                    self.reason = ('buscando ultima localizacao recebida de monstro' if search_goal else 'patrulhando setores sem alvo')
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
        path = collision.route(player, chase_position, blocked) if collision else None
        if collision and not path and blocked:
            self.reason = 'rota temporariamente bloqueada; mantendo alvo'
            self.ready_at = now+.5
            return None
        if collision and not path:
            self.abandon(now, 'sem rota livre até o alvo; procurando outro')
            return None
        metadata = next((s for s in state.get('learned_skills', []) if s['skill_id'] == 524), {})
        wants_skill = (self.use_skills and not self.skill_disabled and metadata.get('level', 0) >= 10
                       and metadata.get('range', 0) >= 1 and state.get('player_sp') is not None
                       and state['player_sp'] >= metadata.get('sp_cost', 65535))
        combat_range = state.get('engagement_range', min(6, metadata['range']) if wants_skill else 2)
        closest = min(math.dist(player, point) for point in range_positions)
        melee = self.auto_attacks and not wants_skill  # the old Kunai-only mode keeps its range
        if melee:
            combat_range = self.MELEE_RANGE  # go hand to hand: basic attacks between the skills
        # The configured rotation supplies engagement_range and handles shooting while
        # retreating. The legacy Kunai planner must reach its cast/response checks first;
        # otherwise a nearby target always produces a walk instead of a ready skill.
        elif not self.auto_attacks and combat_range >= 3:
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
            if not melee or max(math.dist(player, point) for point in range_positions) > 2:
                self.reason = ('mantendo distância; só habilidades' if not self.auto_attacks
                               else 'mantendo alcance; aguardando habilidade disponivel')
                return None
            return {'kind': 'attack', 'target_id': self.target}
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
