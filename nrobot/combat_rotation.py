"""REDE-41: independent skill cooldowns and effect-driven self buffs."""
import math
import time


def skill_category(metadata):
    flags = metadata.get('target_flags')
    if flags == 1:
        return 'Ofensiva no alvo'
    if flags == 4:
        return 'Em si (buff ou ofensiva)'
    if flags == 16:
        return 'Suporte / uso em si'
    if flags == 2:
        return 'Área no chão'
    if flags == 0:
        return 'Passiva'
    return 'Tipo não confirmado'


def configured_range(profile, meta):
    override = profile.get('range_override')
    # Self skills commonly advertise cast range 0, not their damage radius. In automatic
    # mode require a nearby target; the user can explicitly set its activation radius.
    value = meta.get('range', 0) if override is None else override
    if override is None and meta.get('target_flags') in (4, 16) and profile['role'] == 'offensive' and value == 0:
        value = 2
    return max(0, min(value, 32))


class CombatRotation:
    # REDE-60: Shuriken (523) and Kunai (524) take turns; the turn only passes on a confirmed hit.
    THROWS = (523, 524)
    # Never swap ammo while an unconfirmed throw may still be processed by the server.
    SWAP_SETTLE = 1.5
    BURST_SWAP_SETTLE = .3
    # A throw deferred longer than this (repeated failures) gives its turn to the other one.
    TURN_WAIT_LIMIT = 3
    # REDE-76: the server silently drops a skill sent during the previous one's delay; in the
    # logs nothing sent <0.4 s after a confirmed skill went through, almost all after 0.5 s.
    # REDE-80: the wait starts there and keeps moving towards the shortest gap that works.
    AFTER_SKILL_DELAY = .45
    MIN_AFTER_SKILL_DELAY = .3
    MAX_AFTER_SKILL_DELAY = 1.0
    FASTER_STEP = .01

    def __init__(self, profiles, *, response_timeout=1.5, attempts=3, defer=8, interval=.5, global_delay=.12, priority=None,
                 fast=False, burst=False, burst_interval=.05, ignore_animation=False):
        self.ignore_animation = ignore_animation
        self.fast = fast  # offensives ignore the manual interval: only server cooldowns and delay
        # REDE-82: burst sends every offensive in range in turn, one packet per burst_interval,
        # without waiting for the server's answer.
        self.burst, self.burst_interval = burst, burst_interval
        self.profiles = profiles or [{'skill_id': 524, 'enabled': True, 'role': 'offensive',
                                      'level': 10, 'interval': interval, 'effect_id': 0}]
        self.response_timeout, self.attempts, self.defer = response_timeout, attempts, defer
        self.next_send = 0
        self.global_delay = global_delay
        self.ready = {}
        self.pending = {}
        self.failures = {}
        self.log = []
        self.confirmed = 0
        self.buff_confirmed = 0
        self.reason = 'aguardando dados'
        self.session_key = None
        from .summon_queue import SummonQueue
        self.summons = SummonQueue()
        self.blocked_buffs = set()
        self.last_sent = {}
        self.learned_min_interval = {}
        self.last_throw = None
        self.after_skill_delay = self.AFTER_SKILL_DELAY
        self.last_confirmed_at = None
        self.order = {}
        self.cursor = None  # place in the user order of the last offensive sent
        for index, token in enumerate(priority or []):
            for identity in (self.THROWS if token == 'throws' else (token,)):
                self.order.setdefault(identity, index)

    def reset_session(self, key=None):
        self.summons.reset()
        self.ready.clear()
        self.pending.clear()
        self.failures.clear()
        self.next_send = 0
        self.blocked_buffs.clear()
        self.last_sent.clear()
        self.learned_min_interval.clear()
        self.last_throw = None
        self.session_key = key

    def _fail(self, skill_id, now, reason):
        pending = self.pending.pop(skill_id, None)
        if pending and pending['role'] == 'summon':
            self.summons.failed(skill_id, now, reason == 'servidor recusou')
        if pending and pending['role'] == 'buff':
            self.blocked_buffs.add(skill_id)
        sent = self.last_sent.get(skill_id)
        if (reason == 'sem confirmação' and sent is not None and self.last_confirmed_at is not None
                and 0 <= sent-self.last_confirmed_at < self.after_skill_delay+.25):
            # Sent close to the previous skill and ignored: the server's delay is longer here.
            self.after_skill_delay = min(self.MAX_AFTER_SKILL_DELAY, self.after_skill_delay+.05)
        count = self.failures.get(skill_id, 0)+1
        self.failures[skill_id] = count
        self.ready[skill_id] = max(self.ready.get(skill_id, 0) if pending and pending['role'] == 'summon' else 0,
                                   now+(self.defer if count >= self.attempts else .3))
        if count >= self.attempts:
            self.failures[skill_id] = 0
        self.log.append({'kind': 'rotation_failed', 'skill_id': skill_id, 'reason': reason, 'failures': count})

    def observe(self, events, player_id, now):
        self.summons.observe(events, player_id, now)
        for event in events:
            kind = event['kind']
            if kind in ('map_change', 'map_transfer'):
                self.reset_session()
                continue
            if kind == 'skill_retry_notice' and self.last_sent:
                latest = max(self.last_sent, key=self.last_sent.get)
                if latest in self.pending and 0 <= now-self.last_sent[latest] <= 2:
                    retry = min(event['seconds']+1, 300)
                    elapsed = now-self.last_sent[latest]
                    self.learned_min_interval[latest] = max(self.learned_min_interval.get(latest, 0), elapsed+retry)
                    self.ready[latest] = max(self.ready.get(latest, 0), now+retry)
                    self.pending.pop(latest)
                    self.summons.failed(latest, now, True)
                    self.log.append({'kind': 'rotation_cooldown_notice', 'skill_id': latest, 'retry_seconds': retry})
                continue
            skill_id = event.get('skill_id')
            if not self.ignore_animation and kind in ('skill_damage', 'normal_attack') and event.get('source_id') == player_id:
                self.next_send = max(self.next_send, now+min(max(event.get('source_motion_ms', 0), 0), 30000)/1000)
            if kind == 'skill_cooldown':
                self.ready[skill_id] = max(self.ready.get(skill_id, 0), now+event['duration_ms']/1000)
            if kind == 'remove':
                for identity, pending in list(self.pending.items()):
                    if pending['target_id'] == event['entity_id']:
                        self.pending.pop(identity)
            if kind == 'status_effect' and event['entity_id'] == player_id and event['active']:
                for identity, pending in list(self.pending.items()):
                    if pending['role'] == 'buff' and pending['effect_id'] == event['effect_id']:
                        self.pending.pop(identity)
                        self.failures[identity] = 0
                        self.buff_confirmed += 1
                        self.log.append({'kind': 'rotation_buff_confirmed', 'skill_id': identity, 'effect_id': event['effect_id']})
            if kind == 'status_effect' and event['entity_id'] == player_id:
                for profile in self.profiles:
                    if profile['role'] == 'buff' and profile['effect_id'] == event['effect_id']:
                        self.blocked_buffs.discard(profile['skill_id'])
            if skill_id not in self.pending:
                continue
            pending = self.pending[skill_id]
            if kind == 'skill_cast' and event['source_id'] == player_id:
                pending['deadline'] = max(pending['deadline'], now+min(event['duration_ms']/1000, 30)+self.response_timeout)
            if kind == 'skill_failed':
                self._fail(skill_id, now, 'servidor recusou')
            elif (kind == 'skill_damage' and pending['role'] == 'offensive'
                  and event['source_id'] == player_id
                  and (pending.get('cast_mode') == 'self' or event['target_id'] == pending['target_id'])
                  and event['level'] == pending['level']):
                self.pending.pop(skill_id)
                self.failures[skill_id] = 0
                self.confirmed += 1
                sent = self.last_sent.get(skill_id)
                if (self.fast and not self.burst and sent is not None and self.last_confirmed_at is not None
                        and sent-self.last_confirmed_at < self.after_skill_delay+.1):
                    # Accepted right at the current wait: try a slightly shorter one next time.
                    self.after_skill_delay = max(self.MIN_AFTER_SKILL_DELAY, self.after_skill_delay-self.FASTER_STEP)
                self.last_confirmed_at = now
                if not self.burst:
                    self.next_send = max(self.next_send, now+self.after_skill_delay)
                if skill_id in self.THROWS:
                    self.last_throw = skill_id
                self.log.append({'kind': 'rotation_skill_confirmed', 'skill_id': skill_id,
                                 'target_id': event['target_id'], 'damage_raw': event['damage_raw']})
            elif (kind == 'skill_no_damage' and (pending['role'] == 'summon' or pending.get('cast_mode') == 'self')
                  and event['source_id'] == player_id and event['target_id'] == player_id):
                if event['success']:
                    self.pending.pop(skill_id)
                    self.failures[skill_id] = 0
                    self.log.append({'kind': 'rotation_execution_confirmed', 'skill_id': skill_id, 'role': pending['role']})
                else:
                    self._fail(skill_id, now, 'servidor recusou')
            elif (kind == 'skill_no_damage' and pending['role'] == 'buff'
                  and event['source_id'] == player_id and event['target_id'] == player_id):
                if not event['success']:
                    self._fail(skill_id, now, 'buff recusado')
                else:
                    # Execution acknowledgement does not prove the linked effect is active.
                    pending['deadline'] = max(pending['deadline'], now+2)

    def engagement_range(self, state):
        """Keep ranged spacing during cooldown; range availability is not readiness."""
        known = {s['skill_id']: s for s in state.get('learned_skills', [])}
        ranges = [configured_range(p, known[p['skill_id']]) for p in self.profiles
                  if p['enabled'] and p['role'] == 'offensive' and p['skill_id'] in known
                  and known[p['skill_id']]['level'] >= p['level']
                  and (known[p['skill_id']].get('target_flags') in (1, 4, 16) or p['skill_id'] == 524)
                  and configured_range(p, known[p['skill_id']]) >= 1
                  and state.get('player_sp') is not None
                  and state['player_sp'] >= known[p['skill_id']]['sp_cost']
                  and (p['skill_id'] not in (523,524) or state.get('ammo') is None or
                       state['ammo']['options'].get(p['skill_id'], state['ammo']['options'].get(str(p['skill_id']))))]
        return max(ranges, default=2)

    def summon_monster(self, state, target_id=None, *, near_only=True):
        own = state.get('combat_player_positions') or ([state['player_position']] if state.get('player_position') else [])
        if not own:
            return None
        candidates = []
        for e in state.get('recent_entities', []):
            if e.get('kind', 'monster') != 'monster' or (e.get('position_age_seconds', 0) > 1.5 and not e.get('position_usable')):
                continue
            bounds = e.get('attack_positions') or [e.get('effective_position', e['position'])]
            distance = max(math.dist(a,b) for a in own for b in bounds)
            if not near_only or distance <= 12:
                candidates.append((e['entity_id'] != target_id, distance, e['entity_id'], e))
        return min(candidates, key=lambda x:x[:3])[-1] if candidates else None

    def summon_maintenance_required(self, state, now, target_id=None):
        self.summons.update(state, self.profiles, now)
        known = {s['skill_id']:s for s in state.get('learned_skills', [])}
        configured = [p for p in self.profiles if p['enabled'] and p['role'] == 'summon'
                      and p['skill_id'] in known and known[p['skill_id']]['level'] >= p['level']
                      and known[p['skill_id']].get('target_flags') in (2,4,16)]
        if not configured or self.summon_monster(state, target_id, near_only=False) is None:
            return False
        if self.summons.waiting is not None:
            return True
        cooldowns = state.get('skill_cooldowns', {})
        sp = state.get('player_sp')
        if sp is None:
            return False
        available_sp = sp-sum(p['sp_cost'] for p in self.pending.values())
        for profile in configured:
            identity = profile['skill_id']
            cooldown = cooldowns.get(identity, cooldowns.get(str(identity), 0))
            if (identity not in self.pending and now >= max(self.ready.get(identity,0), cooldown)
                and available_sp >= known[identity]['sp_cost'] and self.summons.may_invoke(profile,now)):
                return True
        return False

    def navigation_range(self, state, now, target_id=None):
        distance = self.engagement_range(state)
        # A long-range offensive must not kite beyond the 12-cell summon proximity.
        return min(distance, 11) if self.summon_maintenance_required(state, now, target_id) else distance

    def plan(self, state, now, target_id=None):
        self.summons.update(state, self.profiles, now)
        # Keep the half-second attribution window free of another bot skill.
        active = self.summons.active
        if active and not active['effect_id'] and now <= active.get('learn_until', 0):
            return None

        for identity, pending in list(self.pending.items()):
            if now >= pending['deadline']:
                if self.burst and pending['role'] == 'offensive':
                    self.pending.pop(identity)  # an unanswered burst packet is expected, not a failure
                else:
                    self._fail(identity, now, 'sem confirmação')
        if now < max(self.next_send, state.get('own_cast_until', 0)):
            self.reason = 'aguardando intervalo global ou conjuração'
            return None
        offensive_pending = not self.burst and any(p['role'] == 'offensive' for p in self.pending.values())
        if state.get('state') != 'tracking' or not state.get('player_position_recent'):
            self.reason = 'personagem/conexão indisponível'
            return None
        known = {s['skill_id']: s for s in state.get('learned_skills', [])}
        entities = {e['entity_id']: e for e in state.get('recent_entities', [])}
        available_sp = state.get('player_sp')
        if available_sp is None:
            self.reason = 'SP ainda não recebido'
            return None
        available_sp -= sum(p['sp_cost'] for p in self.pending.values())
        self.reason = 'aguardando alvo, intervalo individual ou término de efeito'
        if not any(profile['enabled'] for profile in self.profiles):
            self.reason = 'nenhuma habilidade habilitada na configuração'
        def priority(profile):
            options = (state.get('ammo') or {}).get('options', {})
            option = options.get(profile['skill_id'], options.get(str(profile['skill_id']), {}))
            if self.order:
                # REDE-83: the user order is a cycle. After a skill, the next one in the list that
                # is ready and in reach goes, wrapping around: a top skill that is ready again at
                # once (fast mode, close target) no longer starves the ones after it. Buffs first.
                rank = self.order.get(profile['skill_id'], len(self.order)+1)
                if profile['role'] != 'buff' and self.cursor is not None:
                    rank = (rank-self.cursor-1) % (len(self.order)+2)
                return (profile['role'] != 'buff', rank, not option.get('ready', True),
                        self.last_sent.get(profile['skill_id'], -1))
            # Without an order every offensive takes its turn: the one sent longest ago goes next.
            return (profile['role'] != 'buff', self.last_sent.get(profile['skill_id'], -1), not option.get('ready', True))
        summon_order = {p['skill_id']: i for i, p in enumerate(self.summons.ordered(self.profiles))}
        def rotation_priority(p):
            if p['role'] == 'summon':
                return (0, summon_order.get(p['skill_id'], 999), 0, 0)
            return (1, *priority(p))
        maintenance = self.summon_maintenance_required(state, now, target_id)
        if maintenance:
            self.reason = 'prioridade Kuchiyose: aguardando invocacao, recarga ou SP; ofensivas suspensas'
        profiles = sorted(self.profiles, key=rotation_priority)
        turn = self.throw_turn(state, known, now, available_sp)
        for profile in profiles:
            if maintenance and profile['role'] != 'summon':
                continue
            if offensive_pending and profile['role'] != 'summon':
                self.reason = 'aguardando confirmação da habilidade anterior'
                continue
            identity = profile['skill_id']
            meta = known.get(identity)
            cooldown = state.get('skill_cooldowns', {}).get(identity, state.get('skill_cooldowns', {}).get(str(identity), 0))
            waiting = identity in self.pending and not (self.burst and profile['role'] == 'offensive')
            if (not profile['enabled'] or meta is None or meta['level'] < profile['level']
                or waiting or now < max(self.ready.get(identity, 0), cooldown)):
                continue
            if identity in self.blocked_buffs:
                self.reason = f'Buff {identity}: sem efeito confirmado; revisar vínculo antes de repetir'
                continue
            if identity in self.THROWS and turn is not None and identity != turn:
                continue
            if available_sp < meta['sp_cost']:
                self.reason = 'SP insuficiente para próxima habilidade'
                continue
            flags = meta.get('target_flags')
            if profile['role'] == 'buff':
                effect = profile.get('effect_id', 0)
                if flags not in (4, 16) or not effect:
                    self.reason = f'Buff {identity}: tipo ou efeito ainda não vinculado'
                    continue
                if state.get('own_effects', {}).get(effect, state.get('own_effects', {}).get(str(effect), False)):
                    continue
                target = state.get('player_id')
                if target is None:
                    continue
            elif profile['role'] == 'summon':
                nearby = self.summon_monster(state, target_id)
                if nearby is None:
                    continue
                if not self.summons.may_invoke(profile, now):
                    continue
                if flags not in (2, 4, 16):
                    self.reason = f'Habilidade {identity}: invocacao exige tipo de chao'
                    continue
                target = state.get('player_id')
                if target is None:
                    continue
            else:
                if flags not in (1, 4, 16) and identity != 524:
                    self.reason = f'Habilidade {identity}: alvo ofensivo não confirmado'
                    continue
                entity = entities.get(target_id)
                if entity is None or not 0 <= configured_range(profile, meta) <= 32:
                    self.reason = f'Habilidade {identity}: alvo ou alcance ainda não confirmado'
                    continue
                bounds = entity.get('attack_positions') or [entity.get('effective_position', entity['position'])]
                if not entity.get('attack_positions') and entity.get('destination') and not entity.get('arrival_estimated'):
                    bounds.append(entity['destination'])
                if max(math.dist(own, p) for own in (state.get('combat_player_positions') or [state['player_position']]) for p in bounds) > configured_range(profile, meta):
                    continue
                if entity.get('position_age_seconds', 0) > 1.5 and not entity.get('position_usable'):
                    continue
                target = state.get('player_id') if flags in (4, 16) else target_id
                if target is None:
                    continue
            self.reason = f"pronta: {meta.get('name') or identity}"
            action = {'kind': 'skill', **profile, 'target_id': target, 'sp_cost': meta['sp_cost']}
            if profile['role'] == 'offensive' and flags in (4, 16):
                action['combat_target_id'] = target_id
                action['cast_mode'] = 'self'
            elif profile['role'] == 'summon':
                action['combat_target_id'] = nearby['entity_id']
                action['cast_mode'] = 'ground' if flags == 2 else 'self'
                # Aim beside the current position, never at an unvalidated distant cell.
                own = (state.get('combat_player_positions') or [state['player_position']])[0]
                action['ground_origin'] = [round(v) for v in own]
                action['cast_range'] = configured_range(profile, meta)
                action['initial_effects'] = [int(i) for i, v in state.get('own_effects', {}).items() if v]
            ammo = state.get('ammo')
            if identity in (523, 524) and ammo is not None:
                options = ammo['options']
                option = options.get(identity, options.get(str(identity)))
                if option is None:
                    self.reason = f'Habilidade {identity}: municao correspondente ausente ou inventario nao recebido'
                    continue
                if ammo['pending']:
                    self.reason = 'aguardando confirmacao da municao'
                    if self.burst:
                        continue  # the other skills keep going while the ammo is swapped
                    return None
                if not option['ready']:
                    if self.burst:
                        # REDE-83: the throws' turn in the rotation is the moment to swap the ammo
                        # (waiting for "nothing else ready" never happens in a burst).
                        last = max((self.last_sent.get(t, -math.inf) for t in self.THROWS), default=-math.inf)
                        if now-last < self.BURST_SWAP_SETTLE:
                            continue  # the last throw may still be on its way
                        return {**action, 'kind': 'equip', 'inventory_index': option['index']}
                    if any(p['role'] == 'offensive' for p in self.pending.values()):
                        self.reason = 'aguardando habilidade anterior antes de trocar municao'
                        return None
                    last = max((self.last_sent.get(t, -math.inf) for t in self.THROWS), default=-math.inf)
                    if self.last_throw_unconfirmed() and now-last < self.SWAP_SETTLE:
                        self.reason = 'aguardando servidor concluir arremesso anterior antes de trocar municao'
                        return None
                    return {**action, 'kind':'equip', 'inventory_index':option['index']}
            return action
        return None

    def soonest_offensive(self, state, now, target_id=None):
        """When the next enabled offensive skill could be used on the target (inf when none)."""
        known = {s['skill_id']: s for s in state.get('learned_skills', [])}
        entities = {e['entity_id']: e for e in state.get('recent_entities', [])}
        entity = entities.get(target_id)
        cooldowns = state.get('skill_cooldowns', {})
        own = state.get('combat_player_positions') or ([state['player_position']] if state.get('player_position') else [])
        soonest = math.inf
        for profile in self.profiles:
            identity, meta = profile['skill_id'], known.get(profile['skill_id'])
            if (not profile['enabled'] or profile['role'] != 'offensive' or meta is None
                    or meta['level'] < profile['level'] or (state.get('player_sp') or 0) < meta['sp_cost']):
                continue
            if entity is not None and own:
                position = entity.get('effective_position', entity['position'])
                if min(math.dist(p, position) for p in own) > configured_range(profile, meta):
                    continue  # out of this skill's reach: it will not interrupt an attack
            cooldown = cooldowns.get(identity, cooldowns.get(str(identity), 0))
            soonest = min(soonest, max(self.ready.get(identity, 0), cooldown, now))
        return soonest

    def last_throw_unconfirmed(self):
        sent = [t for t in self.THROWS if t in self.last_sent]
        if not sent:
            return False
        latest = max(sent, key=self.last_sent.get)
        return latest != self.last_throw or latest in self.pending

    def throw_turn(self, state, known, now, available_sp):
        """The throw whose turn it is, or None when either may be used."""
        if self.last_throw is None:
            return None
        other = self.THROWS[1] if self.last_throw == self.THROWS[0] else self.THROWS[0]
        profile = next((p for p in self.profiles if p['skill_id'] == other and p['enabled']), None)
        meta = known.get(other)
        ammo = state.get('ammo')
        options = (ammo or {}).get('options', {})
        usable = (profile is not None and meta is not None and meta['level'] >= profile['level']
                  and available_sp >= meta['sp_cost']
                  and (ammo is None or options.get(other, options.get(str(other))) is not None)
                  and self.ready.get(other, 0)-now <= self.TURN_WAIT_LIMIT)
        if not usable:
            return None
        self.reason = f'aguardando vez de {meta.get("name") or other} (alternando arremessos)'
        return other

    def sent(self, action, now):
        if action['role'] == 'summon':
            self.summons.reserve(action, now)
        self.last_sent[action['skill_id']] = now
        if action['role'] == 'offensive' and self.order:
            self.cursor = self.order.get(action['skill_id'], len(self.order)+1)
        self.pending[action['skill_id']] = {**action, 'deadline': now+self.response_timeout}
        offensive = action['role'] == 'offensive'
        interval = 0 if (self.fast or self.burst) and offensive else action['interval']
        self.ready[action['skill_id']] = now+max(interval, self.learned_min_interval.get(action['skill_id'], 0))
        self.next_send = now+(self.burst_interval if self.burst else self.global_delay)
        self.log.append({'kind': 'rotation_skill_sent', 'skill_id': action['skill_id'],
                         'target_id': action['target_id'], 'role': action['role']})

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        summons = self.summons.snapshot(self.profiles, now)
        summons['cooldowns'] = {str(p['skill_id']): {'ready_at': self.ready.get(p['skill_id'], 0),
            'remaining_seconds': round(max(0, self.ready.get(p['skill_id'], 0)-now), 2)}
            for p in self.profiles if p['enabled'] and p['role'] == 'summon'}
        return {'summons': summons,
                'reason': self.reason, 'confirmed_skills': self.confirmed, 'confirmed_buffs': self.buff_confirmed,
                'pending': list(self.pending.values()), 'ready_at': dict(self.ready),
                'global_ready_at': self.next_send, 'local_global_delay': self.global_delay,
                'after_skill_delay': round(self.after_skill_delay, 2),
                'observed_min_intervals': dict(self.learned_min_interval)}
