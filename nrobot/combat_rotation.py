"""REDE-41: independent skill cooldowns and effect-driven self buffs."""
import math


def skill_category(metadata):
    flags = metadata.get('target_flags')
    if flags == 1:
        return 'Ofensiva no alvo'
    if flags == 4:
        return 'Em si (confirmar buff)'
    if flags == 16:
        return 'Suporte (confirmar buff/alvo)'
    if flags == 2:
        return 'Área no chão (não suportada)'
    if flags == 0:
        return 'Passiva'
    return 'Tipo não confirmado'


class CombatRotation:
    # REDE-60: Shuriken (523) and Kunai (524) take turns; the turn only passes on a confirmed hit.
    THROWS = (523, 524)
    # Never swap ammo while an unconfirmed throw may still be processed by the server.
    SWAP_SETTLE = 1.5
    # A throw deferred longer than this (repeated failures) gives its turn to the other one.
    TURN_WAIT_LIMIT = 3
    # REDE-76: the server silently drops a skill sent during the previous one's delay; in the
    # logs nothing sent <0.4 s after a confirmed skill went through, almost all after 0.5 s.
    AFTER_SKILL_DELAY = .55
    MAX_AFTER_SKILL_DELAY = 1.0

    def __init__(self, profiles, *, response_timeout=1.5, attempts=3, defer=8, interval=.5, global_delay=.12, priority=None):
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
        self.blocked_buffs = set()
        self.last_sent = {}
        self.learned_min_interval = {}
        self.last_throw = None
        self.after_skill_delay = self.AFTER_SKILL_DELAY
        self.last_confirmed_at = None
        self.order = {}
        for index, token in enumerate(priority or []):
            for identity in (self.THROWS if token == 'throws' else (token,)):
                self.order.setdefault(identity, index)

    def reset_session(self, key=None):
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
        if pending and pending['role'] == 'buff':
            self.blocked_buffs.add(skill_id)
        sent = self.last_sent.get(skill_id)
        if (reason == 'sem confirmação' and sent is not None and self.last_confirmed_at is not None
                and 0 <= sent-self.last_confirmed_at < self.after_skill_delay+.25):
            # Sent close to the previous skill and ignored: the server's delay is longer here.
            self.after_skill_delay = min(self.MAX_AFTER_SKILL_DELAY, self.after_skill_delay+.05)
        count = self.failures.get(skill_id, 0)+1
        self.failures[skill_id] = count
        self.ready[skill_id] = now+(self.defer if count >= self.attempts else .3)
        if count >= self.attempts:
            self.failures[skill_id] = 0
        self.log.append({'kind': 'rotation_failed', 'skill_id': skill_id, 'reason': reason, 'failures': count})

    def observe(self, events, player_id, now):
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
                    self.log.append({'kind': 'rotation_cooldown_notice', 'skill_id': latest, 'retry_seconds': retry})
                continue
            skill_id = event.get('skill_id')
            if kind in ('skill_damage', 'normal_attack') and event.get('source_id') == player_id:
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
                  and event['source_id'] == player_id and event['target_id'] == pending['target_id']
                  and event['level'] == pending['level']):
                self.pending.pop(skill_id)
                self.failures[skill_id] = 0
                self.confirmed += 1
                self.last_confirmed_at = now
                self.next_send = max(self.next_send, now+self.after_skill_delay)
                if skill_id in self.THROWS:
                    self.last_throw = skill_id
                self.log.append({'kind': 'rotation_skill_confirmed', 'skill_id': skill_id,
                                 'target_id': event['target_id'], 'damage_raw': event['damage_raw']})
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
        ranges = [min(known[p['skill_id']]['range'], 12) for p in self.profiles
                  if p['enabled'] and p['role'] == 'offensive' and p['skill_id'] in known
                  and known[p['skill_id']]['level'] >= p['level']
                  and (known[p['skill_id']].get('target_flags') == 1 or p['skill_id'] == 524)
                  and 1 <= known[p['skill_id']]['range'] <= 32
                  and state.get('player_sp') is not None
                  and state['player_sp'] >= known[p['skill_id']]['sp_cost']
                  and (p['skill_id'] not in (523,524) or state.get('ammo') is None or
                       state['ammo']['options'].get(p['skill_id'], state['ammo']['options'].get(str(p['skill_id']))))]
        return max(ranges, default=2)

    def plan(self, state, now, target_id=None):
        for identity, pending in list(self.pending.items()):
            if now >= pending['deadline']:
                self._fail(identity, now, 'sem confirmação')
        if now < max(self.next_send, state.get('own_cast_until', 0)):
            self.reason = 'aguardando intervalo global ou conjuração'
            return None
        if any(p['role'] == 'offensive' for p in self.pending.values()):
            self.reason = 'aguardando confirmação da habilidade anterior'
            return None
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
                # User order is strict: the first usable skill in the list always wins.
                rank = self.order.get(profile['skill_id'], len(self.order)+(profile['role'] != 'buff'))
                return (rank, not option.get('ready', True), self.last_sent.get(profile['skill_id'], -1))
            return (profile['role'] != 'buff', self.last_sent.get(profile['skill_id'], -1), not option.get('ready', True))
        profiles = sorted(self.profiles, key=priority)
        turn = self.throw_turn(state, known, now, available_sp)
        for profile in profiles:
            identity = profile['skill_id']
            meta = known.get(identity)
            cooldown = state.get('skill_cooldowns', {}).get(identity, state.get('skill_cooldowns', {}).get(str(identity), 0))
            if (not profile['enabled'] or meta is None or meta['level'] < profile['level']
                or identity in self.pending or now < max(self.ready.get(identity, 0), cooldown)):
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
            else:
                if flags != 1 and identity != 524:
                    self.reason = f'Habilidade {identity}: alvo ofensivo não confirmado'
                    continue
                entity = entities.get(target_id)
                if entity is None or not 1 <= meta['range'] <= 32:
                    self.reason = f'Habilidade {identity}: alvo ou alcance ainda não confirmado'
                    continue
                bounds = entity.get('attack_positions') or [entity.get('effective_position', entity['position'])]
                if not entity.get('attack_positions') and entity.get('destination') and not entity.get('arrival_estimated'):
                    bounds.append(entity['destination'])
                if max(math.dist(own, p) for own in (state.get('combat_player_positions') or [state['player_position']]) for p in bounds) > min(meta['range'], 12):
                    continue
                if entity.get('position_age_seconds', 0) > 1.5 and not entity.get('position_usable'):
                    continue
                target = target_id
            self.reason = f"pronta: {meta.get('name') or identity}"
            action = {'kind': 'skill', **profile, 'target_id': target, 'sp_cost': meta['sp_cost']}
            ammo = state.get('ammo')
            if identity in (523, 524) and ammo is not None:
                options = ammo['options']
                option = options.get(identity, options.get(str(identity)))
                if option is None:
                    self.reason = f'Habilidade {identity}: municao correspondente ausente ou inventario nao recebido'
                    continue
                if ammo['pending']:
                    self.reason = 'aguardando confirmacao da municao'
                    return None
                if not option['ready']:
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
        self.last_sent[action['skill_id']] = now
        self.pending[action['skill_id']] = {**action, 'deadline': now+self.response_timeout}
        self.ready[action['skill_id']] = now+max(action['interval'], self.learned_min_interval.get(action['skill_id'], 0))
        self.next_send = now+self.global_delay
        self.log.append({'kind': 'rotation_skill_sent', 'skill_id': action['skill_id'],
                         'target_id': action['target_id'], 'role': action['role']})

    def snapshot(self):
        return {'reason': self.reason, 'confirmed_skills': self.confirmed, 'confirmed_buffs': self.buff_confirmed,
                'pending': list(self.pending.values()), 'ready_at': dict(self.ready),
                'global_ready_at': self.next_send, 'local_global_delay': self.global_delay,
                'after_skill_delay': round(self.after_skill_delay, 2),
                'observed_min_intervals': dict(self.learned_min_interval)}
