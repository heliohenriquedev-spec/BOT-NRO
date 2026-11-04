"""REDE-61: hold the bot while a character is disguised as a monster or hidden nearby.
REDE-66: any other character in view also holds the bot until it leaves.

Only server facts are used: the account-range game id (kept while disguised), the sprite
announced for it, and the option bits of appearance/option-change packets. A character
that is already invisible (GM @hide) when it enters the area is not sent to the client at
all, so only the moment it hides inside our view can be detected.

An invisible character still has some actions relayed by the server to everyone around it:
public chat, emotes, turning, attacks/item pickup/sitting, skills, status effects and ground
effects all carry its game id. Such a packet from a character id that is not visible means
someone invisible is next to us (the server only relays them inside the view area), even
when it was already hidden before we arrived. Nothing is ever asked to the server for this.
"""
import math
import unicodedata

from .network_targets import is_player_id

OPTION_HIDE, OPTION_CLOAK, OPTION_INVISIBLE, OPTION_CHASEWALK = 0x2, 0x4, 0x40, 0x4000
HIDDEN_OPTIONS = OPTION_HIDE | OPTION_CLOAK | OPTION_INVISIBLE | OPTION_CHASEWALK


def monster_sprite(species_id):
    # Job classes use 0-999 and 4001-4999; monsters 1001-3999 and 20000+.
    return 1001 <= species_id <= 3999 or species_id >= 20000


def normalize_player_name(name):
    return ' '.join(unicodedata.normalize('NFKC', name).split()).casefold()


class PresenceGuard:
    VIEW_RANGE = 14
    # Invisible characters send nothing more; keep holding this long after the last sign.
    HIDDEN_HOLD = 120
    # REDE-82: a player who left counts as gone only after walking this far (map packets) or
    # logging out / teleporting; one who vanished close by may be hiding and is held longer.
    FAR_ENOUGH = VIEW_RANGE+4
    NEAR_DEPARTURE_HOLD = 60
    REMOVE_LOGOUT, REMOVE_TELEPORT = 2, 3

    GHOST_GRACE = 2  # seconds after a character left the view: late packets are not a sign
    # Only signals the server sends to those right next to the actor prove an invisible character
    # beside us. Attacks, skills and ground effects also arrive from players who simply walked out
    # of the screen (they hit a monster still on it): those never count.
    CLOSE_SIGNALS = {'chat', 'emote', 'direction', 'status_effect', 'body_action'}
    SIGNALS = {'chat': 'falou no chat', 'emote': 'usou emoticon', 'direction': 'virou de direcao',
               'body_action': 'sentou/levantou/pegou item',
               'normal_attack': 'atacou/pegou item/sentou', 'skill_damage': 'usou habilidade',
               'skill_no_damage': 'usou habilidade', 'skill_cast': 'conjurou habilidade',
               'status_effect': 'recebeu efeito de status', 'ground_effect': 'criou efeito no chao'}

    def __init__(self):
        self.resume_delay = 10  # seconds after a player left before the hunt resumes
        self.allowed_names = set()
        self.allowed = set()  # captured targets never hold the bot
        # REDE-70: each kind of presence can be set not to hold the bot (alerts still happen).
        self.hold_players = self.hold_disguised = self.hold_hidden = True
        self.alerts = []
        self.names = {}
        self.name_labels = {}
        self.reset()

    def drain_alerts(self):
        alerts, self.alerts = self.alerts, []
        return alerts

    def reset(self):
        self.disguised = {}
        self.hidden = {}
        self.positions = {}
        self.last_seen_cells = {}  # kept after removal: a hiding character is cleared first
        self.outside_since = {}
        self.players = set()
        self.departures = {}  # identity -> {'left_at', 'position', 'reason', 'far'}
        self.ghosts = {}  # invisible characters revealed only by their actions
        self.last_removed = {}

    @staticmethod
    def signal_source(event):
        kind = event['kind']
        if kind in ('actor_signal', 'status_effect'):
            return event.get('entity_id'), event.get('signal', kind)
        if kind in ('normal_attack', 'skill_damage', 'skill_no_damage', 'skill_cast', 'ground_effect'):
            return event.get('source_id'), kind
        return None, None

    def ghost_signal(self, event, player_id, now):
        identity, signal = self.signal_source(event)
        if signal == 'normal_attack' and event.get('action_type') in (1, 2, 3):
            signal = 'body_action'  # pick up / sit / stand: done where the character stands
        if signal not in self.CLOSE_SIGNALS:
            return
        if (identity is None or identity == player_id or not is_player_id(identity) or identity in self.players
                or now-self.last_removed.get(identity, -1e9) <= self.GHOST_GRACE):
            return
        if event.get('name'):
            self.remember_names({identity: event['name']})
        label = self.SIGNALS.get(signal, signal)
        old = self.ghosts.get(identity)
        if old is None:
            self.alerts.append({'kind': 'ghost', 'entity_id': identity, 'signal': label})
        self.ghosts[identity] = {'seen_at': now, 'signal': label, 'count': (old['count'] if old else 0)+1,
                                 'position': event.get('position') or (old or {}).get('position')
                                 or self.last_seen_cells.get(identity)}

    def observe(self, events, player_id, now, own_position=None):
        for event in events:
            kind = event['kind']
            if kind in ('map_change', 'map_transfer'):
                self.reset()
                continue
            self.ghost_signal(event, player_id, now)
            identity = event.get('entity_id')
            if identity is None or identity == player_id or not is_player_id(identity):
                continue
            if kind == 'name' and event.get('name'):
                self.remember_names({identity:event['name']})
            if 'position' in event:
                self.positions[identity] = event.get('destination') or event['position']
                self.last_seen_cells[identity] = list(event['position'])
                if identity in self.hidden:
                    self.hidden[identity]['seen_at'] = now
                    self.hidden[identity]['position'] = list(event['position'])
            if kind == 'appearance':
                self.departures.pop(identity, None)  # back in view
                self.ghosts.pop(identity, None)
                if identity not in self.players:
                    self.alerts.append({'kind': 'player', 'entity_id': identity})
                self.players.add(identity)
                if monster_sprite(event['species_id']):
                    if identity not in self.disguised:
                        self.alerts.append({'kind': 'disguised', 'entity_id': identity, 'species_id': event['species_id']})
                    self.disguised[identity] = event['species_id']
                else:
                    self.disguised.pop(identity, None)
                self.update_option(identity, event.get('option', 0), now)
            elif kind == 'option_change':
                self.update_option(identity, event['option'], now)
            elif kind == 'remove':
                self.last_removed[identity] = now
                self.ghosts.pop(identity, None)
                if identity in self.players:
                    self.departures[identity] = self.departure(identity, event.get('reason', 0), now, own_position)
                self.players.discard(identity)
                self.disguised.pop(identity, None)
                self.positions.pop(identity, None)
                hidden = self.hidden.get(identity)
                # Removal alone does not prove that a known hidden character reappeared.
                if hidden is not None and event.get('reason') in (self.REMOVE_LOGOUT, self.REMOVE_TELEPORT):
                    self.hidden.pop(identity)

    def departure(self, identity, reason, now, own_position):
        position = self.positions.get(identity) or self.last_seen_cells.get(identity)
        if reason in (self.REMOVE_LOGOUT, self.REMOVE_TELEPORT):
            far = True
        elif position is None or own_position is None:
            far = False
        else:  # left the view: its last destination tells how far it went
            far = math.dist(position, own_position) >= self.FAR_ENOUGH
        return {'left_at': now, 'position': position, 'reason': reason, 'far': far}

    def update_option(self, identity, option, now):
        if option & HIDDEN_OPTIONS:
            if identity not in self.hidden:
                self.alerts.append({'kind': 'hidden', 'entity_id': identity, 'option': option & HIDDEN_OPTIONS})
            self.hidden[identity] = {'option': option & HIDDEN_OPTIONS, 'seen_at': now,
                                     'position': self.last_seen_cells.get(identity) or self.positions.get(identity)}
        else:
            self.hidden.pop(identity, None)

    def remember_names(self, names):
        for identity, name in names.items():
            if is_player_id(identity) and isinstance(name, str) and name.strip():
                self.names[identity] = normalize_player_name(name)
                self.name_labels[identity] = name.strip()

    def ignored(self, identity):
        allowed = {normalize_player_name(n) for n in self.allowed_names}
        return identity in self.allowed or self.names.get(identity) in allowed

    def reason(self, player_position, now):
        # A visible actor may walk beyond the radius without a removal packet.
        for identity in self.players:
            position = self.positions.get(identity)
            if position is not None and player_position is not None and math.dist(position, player_position) > self.VIEW_RANGE:
                self.outside_since.setdefault(identity, now)
            else:
                self.outside_since.pop(identity, None)

        self.hidden = {i: h for i, h in self.hidden.items() if now-h['seen_at'] <= self.HIDDEN_HOLD}
        for identity, species in self.disguised.items():
            if self.ignored(identity) or not self.hold_disguised:
                continue
            position = self.positions.get(identity)
            if position is None or player_position is None or math.dist(position, player_position) <= self.VIEW_RANGE:
                return f'personagem {identity} disfarcado de monstro (sprite {species}) no campo de visao'
        for identity, hidden in self.hidden.items():
            if self.ignored(identity) or not self.hold_hidden:
                continue
            kind = '@hide/invisivel' if hidden['option'] & OPTION_INVISIBLE else 'escondido/furtivo'
            remaining = round(self.HIDDEN_HOLD-(now-hidden['seen_at']))
            return f'personagem {identity} {kind} por perto; retomada em ate {remaining} s sem novos sinais'
        self.ghosts = {i: g for i, g in self.ghosts.items() if now-g['seen_at'] <= self.HIDDEN_HOLD}
        for identity, ghost in self.ghosts.items():
            if self.ignored(identity) or not self.hold_hidden:
                continue
            remaining = round(self.HIDDEN_HOLD-(now-ghost['seen_at']))
            return (f"personagem invisivel {identity} ao lado ({ghost['signal']}, sem aparecer na tela); "
                    f"retomada em ate {remaining} s sem novos sinais")
        for identity in sorted(self.players) if self.hold_players else ():
            if self.ignored(identity):
                continue
            position = self.positions.get(identity)
            if position is None or player_position is None or math.dist(position, player_position) <= self.VIEW_RANGE:
                return f'jogador {identity} no campo de visao'
            left = self.resume_delay-(now-self.outside_since.get(identity, now))
            if left > 0:
                return f'jogador {identity} afastado; retomada em {left:.0f} s'
        for identity, gone in sorted(self.departures.items()):
            wait = self.resume_delay
            left = wait-(now-gone['left_at'])
            if left <= 0:
                del self.departures[identity]
                continue
            if self.ignored(identity) or not self.hold_players:
                continue
            how = {self.REMOVE_LOGOUT: 'deslogou', self.REMOVE_TELEPORT: 'teleportou'}.get(gone['reason'])
            how = how or ('foi para longe' if gone['far'] else 'sumiu perto (pode estar escondido)')
            return f'jogador {identity} {how}; retomada em {left:.0f} s'
        return None

    def snapshot(self, player_position, now):
        self.reason(player_position, now)  # expire stale markers before building the drawing list
        hidden = [{'entity_id': identity, 'name': self.name_labels.get(identity),
                   'last_known': True, 'allowed': self.ignored(identity),
                   'position': entry.get('position') or self.last_seen_cells.get(identity) or self.positions.get(identity),
                   'gm_invisible': bool(entry['option'] & OPTION_INVISIBLE), 'age_seconds': round(now-entry['seen_at'], 1)}
                  for identity, entry in self.hidden.items()]
        shadows = list(hidden)
        shadows += [{'entity_id': identity, 'name': self.name_labels.get(identity), 'last_known': True,
                     'invisible_signal': ghost['signal'], 'signals': ghost['count'], 'gm_invisible': True,
                     'allowed': self.ignored(identity), 'position': ghost.get('position'),
                     'age_seconds': round(now-ghost['seen_at'], 1)}
                    for identity, ghost in self.ghosts.items() if identity not in self.hidden]
        for identity, gone in self.departures.items():
            if identity in self.hidden or gone['far'] or gone['reason'] != 0 or gone.get('position') is None or now-gone['left_at'] >= self.resume_delay:
                continue
            shadows.append({'entity_id': identity, 'name': self.name_labels.get(identity),
                            'position': self.last_seen_cells.get(identity) or gone['position'],
                            'last_known': True, 'possible_hidden': True, 'gm_invisible': False,
                            'allowed': self.ignored(identity), 'age_seconds': round(now-gone['left_at'], 1)})
        return {'reason': self.reason(player_position, now), 'disguised': sorted(self.disguised),
                'hidden': sorted(self.hidden), 'hidden_details': hidden, 'invisible': sorted(self.ghosts), 'shadow_details': shadows,
                'players': sorted(self.players)}
