"""One summon at a time. Duration, execution ACK and cooldown are separate facts."""
import copy
import math


def validated_learning(data):
    result = {}
    if not isinstance(data, dict):
        return result
    for key, entry in data.items():
        parts = str(key).split(':')
        if len(parts) != 2 or not all(p.isdigit() and 0 < int(p) <= 65535 for p in parts) or not isinstance(entry, dict):
            continue
        effect = entry.get('effect_id', 0)
        if type(effect) is not int or not 0 <= effect <= 65535:
            continue
        record = {'effect_id': effect}
        if entry.get('creature') is True:
            record['creature'] = True
        for name in ('last_observed_duration', 'user_observed_duration'):
            value = entry.get(name)
            if type(value) in (int, float) and math.isfinite(value) and 0 < value <= 86400:
                record[name] = value
        samples = entry.get('samples', [])
        record['samples'] = [v for v in samples if type(v) in (int, float) and math.isfinite(v) and 0 < v <= 86400][-10:] if isinstance(samples, list) else []
        result[key] = record
    return result


class SummonQueue:
    def __init__(self):
        self.mode = 'cycle'
        self.active = None
        self.waiting = None
        self.last_completed = None
        self.learned = {}
        self.log = []
        self.dirty = False
        self.reason = ''
        self.silent_misses = 0

    @staticmethod
    def key(skill_id, level):
        return f'{skill_id}:{level}'

    def reset(self):
        self.active = self.waiting = None
        self.last_completed = None

    def ordered(self, profiles):
        rows = sorted((p for p in profiles if p['enabled'] and p['role'] == 'summon'),
                      key=lambda p: (p.get('summon_priority', 0), p['skill_id']))
        ids = [p['skill_id'] for p in rows]
        if self.mode == 'cycle' and self.last_completed in ids:
            i = ids.index(self.last_completed)+1
            rows = rows[i:]+rows[:i]
        return rows

    def effect(self, profile):
        learned = self.learned.get(self.key(profile['skill_id'], profile['level']), {})
        # An observed status may be the skill's cooldown icon, not summon lifetime.
        # Explicit duration must not inherit that automatic association.
        return profile.get('effect_id', 0) or (0 if profile.get('summon_duration', 0) else learned.get('effect_id', 0))

    def may_invoke(self, profile, now):
        if self.waiting is not None:
            return False
        if self.active is None:
            return True
        active = self.active
        if active['effect_id'] or active['expires_at'] is not None or active['skill_id'] != profile['skill_id']:
            return False
        if active.get('visible_creatures'):
            return False  # its living creature is still on screen: no probe/recast is needed
        # An unknown lifetime must not suspend maintenance forever. Probe only the
        # same summon, at its configured interval; this is not proof it has expired.
        return now-active.get('last_attempt_at', active['started_at'] or now) >= max(2, profile['interval'])

    def reserve(self, action, now):
        if self.active is not None:
            self.active['last_attempt_at'] = now
        self.waiting = {**copy.deepcopy(action), 'sent_at': now, 'candidates': set(), 'ack_at': None,
                        'effect_id': self.effect(action)}
        self.reason = 'aguardando confirmacao da invocacao; fila reservada'

    def start(self, now, evidence):
        entry = self.waiting
        if entry is None:
            return
        learned = self.learned.get(self.key(entry['skill_id'], entry['level']), {})
        duration = entry.get('summon_duration', 0) or learned.get('user_observed_duration', 0)
        if evidence == 'unconfirmed':
            now = entry['sent_at']
        self.active = {'skill_id': entry['skill_id'], 'level': entry['level'], 'started_at': now,
                       'effect_id': entry['effect_id'], 'expires_at': now+duration if duration else None,
                       'duration_source': 'configured' if entry.get('summon_duration', 0) else 'user_observed' if duration else 'effect',
                       'evidence': evidence, 'candidates': set(entry['candidates']),
                       'learn_until': now+.5, 'initial_effects': entry.get('initial_effects', []),
                       'confirmed': evidence != 'unconfirmed', 'last_attempt_at': entry['sent_at']}
        self.waiting = None
        self.log.append({'kind': 'summon_started', 'skill_id': entry['skill_id'], 'evidence': evidence})

    def finish(self, now, evidence):
        active = self.active
        if active is None:
            return
        duration = round(now-active['started_at'], 3) if active['started_at'] is not None else None
        if duration is not None and .1 <= duration <= 86400 and (evidence == 'user_observed_end' or evidence == 'effect_ended' and active['confirmed']):
            key = self.key(active['skill_id'], active['level'])
            record = self.learned.setdefault(key, {})
            record['effect_id'] = active['effect_id']
            record['last_observed_duration'] = duration
            if evidence == 'user_observed_end':
                record['user_observed_duration'] = duration
            record['samples'] = record.get('samples', [])[-9:]+[duration]
            self.dirty = True
        self.last_completed = active['skill_id']
        self.log.append({'kind': 'summon_ended', 'skill_id': active['skill_id'],
                         'observed_seconds': duration, 'evidence': evidence})
        self.active = None
        self.reason = 'invocacao encerrada; proxima da fila'

    # The server never answers a summon; the creature it creates is the proof. A summon whose
    # creature did not appear was not cast (sent during the delay after other skills, or walking):
    # 41 of 78 on 2026-11-05, while the bot believed one was up and waited 20 s.
    SILENT_LIMIT = 12  # misses in a row before assuming a summon that creates nothing visible

    def creates_creature(self, skill_id, level):
        return bool(self.learned.get(self.key(skill_id, level), {}).get('creature'))

    def failed(self, skill_id, now, explicit):
        if self.waiting and self.waiting['skill_id'] == skill_id:
            if explicit:
                self.waiting = None
                self.reason = 'invocacao recusada; tentando proxima disponivel'
            elif self.creates_creature(skill_id, self.waiting['level']) and self.silent_misses < self.SILENT_LIMIT:
                self.silent_misses += 1
                self.log.append({'kind': 'summon_not_created', 'skill_id': skill_id, 'misses': self.silent_misses})
                self.waiting = None
                self.reason = 'invocacao nao saiu (nenhuma criatura criada); tentando de novo'
                return 'not_created'
            else:
                # Do not create a second summon when an execution may have succeeded silently.
                self.start(now, 'unconfirmed')

    def creature_created(self, creature_id, now):
        """Own creature born right after the summon: it is out for sure."""
        entry = self.waiting or (self.active if self.active is not None and now-(self.active.get('started_at') or now) <= 3 else None)
        if entry is not None:
            key = self.key(entry['skill_id'], entry['level'])
            if not self.learned.get(key, {}).get('creature'):
                self.learned.setdefault(key, {})['creature'] = True
                self.dirty = True
            if self.waiting is not None:
                self.start(now, 'creature_created')
            self.silent_misses = 0
        elif self.active is not None and now-(self.active.get('started_at') or now) > 3:
            return  # an old summon's creature (e.g. back into view): not a new one
        if self.active is not None:
            self.active.setdefault('creatures', set()).add(creature_id)
            self.active.setdefault('visible_creatures', set()).add(creature_id)
            self.active['confirmed'] = True

    def creature_gone(self, creature_id, now):
        """Its creature died or vanished: the summon is over, the next one goes at once."""
        active = self.active
        if active is not None and creature_id in active.get('creatures', ()):
            active['creatures'].discard(creature_id)
            active.get('visible_creatures', set()).discard(creature_id)
            if not active['creatures']:
                self.finish(now, 'creature_gone')

    def observe(self, events, player_id, now):
        for event in events:
            kind = event['kind']
            if kind in ('map_change', 'map_transfer'):
                self.reset()
                continue
            if self.active is not None and event.get('entity_id') in self.active.get('creatures', ()):
                if kind=='appearance':
                    self.active.setdefault('visible_creatures',set()).add(event['entity_id'])
                elif kind=='remove':
                    self.active.get('visible_creatures',set()).discard(event['entity_id'])
            entry = self.waiting or self.active
            if entry is None:
                continue
            if kind in ('skill_cast', 'skill_no_damage') and event.get('source_id') == player_id and event.get('skill_id') != entry['skill_id']:
                entry['candidates'].add(-1)  # another skill makes attribution ambiguous
            if kind == 'status_effect' and event.get('entity_id') == player_id:
                effect = event['effect_id']
                if event['active'] and effect not in entry.get('initial_effects', []):
                    if self.waiting or now <= entry.get('learn_until', 0):
                        entry['candidates'].add(effect)
                if effect == entry.get('effect_id'):
                    if event['active'] and self.waiting:
                        self.start(now, 'linked_effect')
                    elif not event['active'] and self.active:
                        self.finish(now, 'effect_ended')
            if kind == 'skill_no_damage' and self.waiting and event.get('skill_id') == self.waiting['skill_id']:
                if event.get('source_id') == player_id and event.get('target_id') == player_id:
                    if event['success']:
                        self.start(now, 'skill_ack')
                    else:
                        self.failed(self.waiting['skill_id'], now, True)
            if kind == 'skill_no_damage' and self.active and event.get('skill_id') == self.active['skill_id']:
                if event.get('source_id') == player_id and event.get('target_id') == player_id and event.get('success'):
                    if self.active['evidence'] != 'skill_ack':
                        self.active['evidence'] = 'skill_ack'
                        self.active['confirmed'] = True
                        self.active['learn_until'] = now+.5
            if kind == 'ground_effect' and self.waiting and event.get('source_id') == player_id:
                point = self.waiting.get('ground_position')
                if point and list(event.get('position', [])) == list(point):
                    self.start(now, 'own_ground_created')
                    # Ground animation removal is NOT proof that a summoned creature died.

    def update(self, state, profiles, now):
        active = self.active
        if active and active['expires_at'] is None:
            profile = next((p for p in profiles if p['skill_id'] == active['skill_id']), {})
            if profile.get('summon_duration', 0) and active['started_at'] is not None:
                active['expires_at'] = active['started_at']+profile['summon_duration']
                active['duration_source'] = 'configured'
        effects = state.get('own_effects', {})
        if active:
            if not active['effect_id'] and not active.get('learning_done') and now > active.get('learn_until', 0) and active['evidence'] == 'skill_ack' and active.get('duration_source') != 'configured':
                candidates = active['candidates']
                if len(candidates) == 1 and next(iter(candidates)) > 0:
                    effect = next(iter(candidates))
                    if effects.get(effect, effects.get(str(effect))) is True:
                        active['effect_id'] = effect
                        key = self.key(active['skill_id'], active['level'])
                        self.learned.setdefault(key, {})['effect_id'] = effect
                        self.dirty = True
                        self.log.append({'kind': 'summon_effect_linked', 'skill_id': active['skill_id'], 'effect_id': effect})
                active['learning_done'] = True
                active['learn_until'] = -1  # do not bind later unrelated effects
            effect = active['effect_id']
            if effect and effects.get(effect, effects.get(str(effect))) is False:
                self.finish(now, 'effect_ended')
            elif active['expires_at'] is not None and now >= active['expires_at'] and (not effect or active.get('duration_source') == 'configured'):
                self.finish(now, 'configured_duration')
        elif self.waiting is None:
            # An already active linked summon survives pause/configuration application.
            for profile in profiles:
                if profile['role'] != 'summon' or profile.get('summon_duration', 0):
                    continue
                effect = self.effect(profile)
                if effect and effects.get(effect, effects.get(str(effect))) is True:
                    self.active = {'skill_id': profile['skill_id'], 'level': profile['level'], 'started_at': None,
                                   'effect_id': effect, 'expires_at': None, 'confirmed': True,
                                   'evidence': 'already_active_effect', 'candidates': set(), 'learn_until': 0}
                    break
        if self.active:
            a = self.active
            self.reason = ('invocacao ativa; aguardando fim do efeito' if a['effect_id'] else
                           'invocacao por duracao configurada' if a['expires_at'] else
                           'duracao desconhecida: aguardando efeito vinculado ou duracao configurada')

    def snapshot(self, profiles, now):
        active = {k:v for k,v in (self.active or {}).items() if k not in ('candidates', 'initial_effects', 'learn_until', 'creatures', 'visible_creatures')}
        if active:
            active['remaining_seconds'] = max(0, active['expires_at']-now) if active['expires_at'] else None
        return {'active': active or None, 'waiting_skill_id': self.waiting['skill_id'] if self.waiting else None,
                'queue': [p['skill_id'] for p in self.ordered(profiles)], 'reason': self.reason,
                'durations': copy.deepcopy(self.learned)}
