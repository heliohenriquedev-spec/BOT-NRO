"""Coelho x3 -> Fukai Kemuri, for a map behavior: put a group to sleep, then keep fighting.

Seen in every manual use (2026-11-04..09, 600+ times): the client only sends the three Coelho
(500) seals. Right after the third seal's acknowledgement the server itself answers with
Fukai Kemuri (668): an 011A on the player and 01DE on the monsters. So the bot never casts the
area skill; it sends the seals and waits for the server's answer. No escape follows: once the
monsters sleep, the ordinary control (silence) and damage go on.
"""
import copy


def validate(config):
    expected={'prepare_skill','prepare_casts','area_skill','minimum_count','radius','rearm_seconds'}
    if not isinstance(config,dict) or not expected<=set(config)<=expected|{'keep_others_asleep'}:
        raise ValueError('Sono em area invalido')
    if type(config.get('keep_others_asleep',False)) is not bool:
        raise ValueError('Sono em area: keep_others_asleep invalido')
    for key,low,high in [('prepare_casts',1,5),('minimum_count',2,10),('radius',1,20)]:
        if type(config[key]) is not int or not low<=config[key]<=high:
            raise ValueError('Sono em area: '+key+' invalido')
    if type(config['rearm_seconds']) not in (int,float) or not .5<=config['rearm_seconds']<=120:
        raise ValueError('Sono em area: rearm_seconds invalido')
    for key in ('prepare_skill','area_skill'):
        row=config[key]
        if (not isinstance(row,dict) or set(row)!={'skill_id','name'} or type(row['skill_id']) is not int
            or not 1<=row['skill_id']<=65535 or not isinstance(row['name'],str) or not 1<=len(row['name'])<=100):
            raise ValueError('Habilidade do sono em area invalida')
    return copy.deepcopy(config)


class AreaSleep:
    SEAL_WAIT = 1.0  # s for the server to acknowledge a sent seal
    AREA_WAIT = 1.0  # s after the last seal for the server's area skill
    SEQUENCE_LIMIT = 6.0  # s for the whole sequence
    PAUSE = 5.0  # s of ordinary combat after a refused seal or seals unanswered again and again
    RETRIES = 2  # an unanswered seal is sent again this many times before giving up
    SETTLE = .35  # s after the last skill sent before the first seal
    # The server ignored seals sent right behind other skills (buffs 100-250 ms before, a Shuriken
    # still unanswered): yuno_fild07 2026-11-09 16:44. Each one then held the Kemuri for 15 s.

    def __init__(self, config):
        self.config = validate(config)
        self.prepare_id = self.config['prepare_skill']['skill_id']
        self.area_id = self.config['area_skill']['skill_id']
        self.fired_at = -1e9
        self.paused_until = 0
        self.fired = 0
        self.reason = ''
        self.reset()

    def reset(self):
        self.phase = None  # 'prepare' -> 'area' -> None
        self.confirmed = 0
        self.waiting = None  # when the seal in flight was sent
        self.unanswered = 0
        self.started = 0
        self.area_since = None

    def drop(self, now, reason):
        self.reset()
        self.paused_until = now+self.PAUSE
        self.reason = reason

    def observe(self, events, player_id, now):
        for e in events:
            kind = e.get('kind')
            if kind in ('map_change', 'map_transfer'):
                self.reset()
                continue
            if player_id is None or e.get('source_id', player_id) != player_id:
                continue
            identity = e.get('skill_id')
            if identity == self.area_id and kind in ('skill_no_damage', 'skill_damage'):
                if kind == 'skill_no_damage' and not e.get('success', True):
                    continue
                if now-self.fired_at > .5:
                    self.fired += 1
                self.fired_at = now
                self.reset()
                self.reason = 'Fukai Kemuri confirmada pelo servidor; silenciando e focando o menor HP'
            elif identity == self.prepare_id and self.phase == 'prepare':
                if kind == 'skill_no_damage' and e.get('target_id') == player_id:
                    if not e.get('success', True):
                        self.drop(now, 'selo recusado pelo servidor; combate normal por alguns segundos')
                        continue
                    self.confirmed += 1
                    self.waiting = None
                    if self.confirmed >= self.config['prepare_casts']:
                        self.phase = 'area'
                        self.area_since = now
                elif kind == 'skill_failed':
                    self.drop(now, 'selo recusado pelo servidor; combate normal por alguns segundos')

    def sent(self, action, now):
        if action.get('area_sleep_stage') == 'prepare':
            self.waiting = now

    def nearby(self, state, distance, species):
        return [e for e in state.get('recent_entities', []) if e.get('kind', 'monster') == 'monster'
                and e.get('species_id') in species and distance(state, e) <= self.config['radius']]

    def uncontrolled(self, state, distance, statuses, species, current=None):
        """Monsters close by that are neither silenced, stunned nor asleep. With keep_others_asleep,
        every monster but the one being killed must sleep: silence no longer counts as controlled."""
        keep = self.config.get('keep_others_asleep')
        rows = []
        for e in self.nearby(state, distance, species):
            if keep and e['entity_id'] == current:
                continue
            status = statuses(e)
            if not (status['stun'] or status['sleep'] or status['silence'] and not keep):
                rows.append(e)
        return rows

    def wanted(self, group, state, distance, species, attackers=()):
        # keep_others_asleep: the group is the others besides the one being killed. A single one
        # awake gets Fukai Yasumi from the ordinary control; two or more, the Kemuri. Two or more
        # monsters hitting the player close by (any species, the target included) also call it.
        return len(group) >= self.config['minimum_count'] or len(attackers) >= self.config['minimum_count']

    def learned(self, state, identity):
        return next((s for s in state.get('learned_skills', []) if s['skill_id'] == identity and s.get('level', 0) > 0), None)

    def cooling(self, state, now):
        cds = state.get('skill_cooldowns', {})
        server = max(cds.get(i, cds.get(str(i), 0)) for i in (self.prepare_id, self.area_id))
        return now < max(server, self.fired_at+self.config['rearm_seconds'])

    def intent(self, state, now, distance, statuses, species, current=None, attackers=()):
        group = self.uncontrolled(state, distance, statuses, species, current)
        attackers = [e for e in attackers if distance(state, e) <= self.config['radius']
                     and not (statuses(e)['sleep'] or statuses(e)['stun'])]
        if self.phase is None:
            if now < self.paused_until or self.cooling(state, now):
                return None
            if not self.wanted(group, state, distance, species, attackers) or self.learned(state, self.prepare_id) is None:
                return None
            self.phase = 'prepare'
            self.started = now
            self.confirmed = 0
            self.waiting = None
            self.reason = ''
        if self.phase == 'prepare' and self.waiting is not None and now-self.waiting > self.SEAL_WAIT:
            if self.unanswered >= self.RETRIES:
                self.drop(now, 'selos sem resposta do servidor; combate normal por alguns segundos')
                return None
            self.unanswered += 1
            self.waiting = None  # send it again
            self.started = now
            self.reason = 'selo sem resposta; enviando de novo'
        if self.phase == 'area' and now-self.area_since > self.AREA_WAIT:
            # The seals went through but no Kemuri came: it is recharging on the server.
            self.reset()
            self.fired_at = now
            self.reason = 'Kemuri nao veio apos os selos (recarga); focando o menor HP'
            return None
        if now-self.started > self.SEQUENCE_LIMIT:
            self.drop(now, 'sequencia de selos nao concluida; combate normal por alguns segundos')
            return None
        nearby = group or attackers or self.nearby(state, distance, species)
        if not nearby:
            self.reset()
            return None
        target = min(nearby, key=lambda e: distance(state, e))
        if self.phase == 'prepare':
            reason = f"Fukai Kemuri: selo Coelho {self.confirmed}/{self.config['prepare_casts']} confirmados ({len(group)} sem sono, {len(attackers)} batendo)"
        else:
            reason = 'Fukai Kemuri: selos concluidos, aguardando o servidor'
        return dict(mode='area_sleep', target_id=target['entity_id'], skill_id=None, phase=self.phase, reason=reason)

    def plan(self, state, rotation, now, intent):
        if self.phase != 'prepare' or self.waiting is not None:
            return None
        meta = self.learned(state, self.prepare_id)
        if meta is None or meta.get('target_flags') not in (4, 16):
            return None  # the seal is a self skill; never aim it at the monster
        if rotation.pending:
            # Expire the unanswered ones first: only the rotation's planning does it, and it does not
            # run during the seals; a stun left pending held the character still for 6 s, until the
            # sequence gave up (yuno_fild07 2026-11-09 17:06:49-55).
            original = rotation.profiles
            rotation.profiles = []
            try:
                rotation.plan(state, now, None)
            finally:
                rotation.profiles = original
        if rotation.pending:
            return None  # the previous skill still unanswered: a seal now is ignored by the server
        last = max(rotation.last_sent.values(), default=-1e9)
        if self.confirmed == 0 and now-last < self.SETTLE:
            return None
        # A one-skill rotation: same SP, cast, cooldown and send gates as any other skill. The seal
        # is cast on the player; the range only asks for the monster to be on screen.
        profile = dict(skill_id=self.prepare_id, enabled=True, role='offensive', level=meta['level'],
                       interval=.1, effect_id=0, range_override=32)
        original, old_burst, old_priority = rotation.profiles, rotation.burst, getattr(rotation, 'control_priority', False)
        rotation.profiles = [profile]
        rotation.burst = False
        rotation.control_priority = True
        try:
            action = rotation.plan(state, now, intent['target_id'])
        finally:
            rotation.profiles, rotation.burst, rotation.control_priority = original, old_burst, old_priority
        if action is None or action.get('kind') != 'skill' or action.get('skill_id') != self.prepare_id:
            return None
        return {**action, 'area_sleep_stage': 'prepare'}

    def snapshot(self):
        return {'phase': self.phase, 'seals_confirmed': self.confirmed, 'kemuri_confirmed': self.fired, 'reason': self.reason}
