"""REDE-61: hold the bot while a character is disguised as a monster or hidden nearby.
REDE-66: any other character in view also holds the bot until it leaves.

Only server facts are used: the account-range game id (kept while disguised), the sprite
announced for it, and the option bits of appearance/option-change packets. A character
that is already invisible (GM @hide) when it enters the area is not sent to the client at
all, so only the moment it hides inside our view can be detected.
"""
import math

from .network_targets import is_player_id

OPTION_HIDE, OPTION_CLOAK, OPTION_INVISIBLE, OPTION_CHASEWALK = 0x2, 0x4, 0x40, 0x4000
HIDDEN_OPTIONS = OPTION_HIDE | OPTION_CLOAK | OPTION_INVISIBLE | OPTION_CHASEWALK


def monster_sprite(species_id):
    # Job classes use 0-999 and 4001-4999; monsters 1001-3999 and 20000+.
    return 1001 <= species_id <= 3999 or species_id >= 20000


class PresenceGuard:
    VIEW_RANGE = 14
    # Invisible characters send nothing more; keep holding this long after the last sign.
    HIDDEN_HOLD = 120
    # REDE-82: a player who left counts as gone only after walking this far (map packets) or
    # logging out / teleporting; one who vanished close by may be hiding and is held longer.
    FAR_ENOUGH = VIEW_RANGE+4
    NEAR_DEPARTURE_HOLD = 60
    REMOVE_LOGOUT, REMOVE_TELEPORT = 2, 3

    def __init__(self):
        self.resume_delay = 10  # seconds after a player left before the hunt resumes
        self.allowed = set()  # captured targets never hold the bot
        # REDE-70: each kind of presence can be set not to hold the bot (alerts still happen).
        self.hold_players = self.hold_disguised = self.hold_hidden = True
        self.alerts = []
        self.reset()

    def drain_alerts(self):
        alerts, self.alerts = self.alerts, []
        return alerts

    def reset(self):
        self.disguised = {}
        self.hidden = {}
        self.positions = {}
        self.last_seen_cells = {}  # kept after removal: a hiding character is cleared first
        self.players = set()
        self.departures = {}  # identity -> {'left_at', 'position', 'reason', 'far'}

    def observe(self, events, player_id, now, own_position=None):
        for event in events:
            kind = event['kind']
            if kind in ('map_change', 'map_transfer'):
                self.reset()
                continue
            identity = event.get('entity_id')
            if identity is None or identity == player_id or not is_player_id(identity):
                continue
            if 'position' in event:
                self.positions[identity] = event.get('destination') or event['position']
                self.last_seen_cells[identity] = self.positions[identity]
                if identity in self.hidden:
                    self.hidden[identity]['seen_at'] = now
            if kind == 'appearance':
                self.departures.pop(identity, None)  # back in view
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
                if identity in self.players:
                    self.departures[identity] = self.departure(identity, event.get('reason', 0), now, own_position)
                self.players.discard(identity)
                self.disguised.pop(identity, None)
                self.positions.pop(identity, None)
                hidden = self.hidden.get(identity)
                # Ordinary hiding ends with removal; GM invisibility may also clear the unit.
                if hidden is not None and not hidden['option'] & OPTION_INVISIBLE:
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
                                     'position': self.positions.get(identity) or self.last_seen_cells.get(identity)}
        else:
            self.hidden.pop(identity, None)

    def reason(self, player_position, now):
        self.hidden = {i: h for i, h in self.hidden.items() if now-h['seen_at'] <= self.HIDDEN_HOLD}
        for identity, species in self.disguised.items():
            if identity in self.allowed or not self.hold_disguised:
                continue
            position = self.positions.get(identity)
            if position is None or player_position is None or math.dist(position, player_position) <= self.VIEW_RANGE:
                return f'personagem {identity} disfarcado de monstro (sprite {species}) no campo de visao'
        for identity, hidden in self.hidden.items():
            if identity in self.allowed or not self.hold_hidden:
                continue
            kind = '@hide/invisivel' if hidden['option'] & OPTION_INVISIBLE else 'escondido/furtivo'
            remaining = round(self.HIDDEN_HOLD-(now-hidden['seen_at']))
            return f'personagem {identity} {kind} por perto; retomada em ate {remaining} s sem novos sinais'
        for identity in sorted(self.players-self.allowed) if self.hold_players else ():
            position = self.positions.get(identity)
            if position is None or player_position is None or math.dist(position, player_position) <= self.VIEW_RANGE:
                return f'jogador {identity} no campo de visao'
        for identity, gone in sorted(self.departures.items()):
            wait = self.resume_delay if gone['far'] else max(self.resume_delay, self.NEAR_DEPARTURE_HOLD)
            left = wait-(now-gone['left_at'])
            if left <= 0:
                del self.departures[identity]
                continue
            if identity in self.allowed or not self.hold_players:
                continue
            how = {self.REMOVE_LOGOUT: 'deslogou', self.REMOVE_TELEPORT: 'teleportou'}.get(gone['reason'])
            how = how or ('foi para longe' if gone['far'] else 'sumiu perto (pode estar escondido)')
            return f'jogador {identity} {how}; retomada em {left:.0f} s'
        return None

    def snapshot(self, player_position, now):
        hidden = [{'entity_id': identity,
                   'position': self.positions.get(identity) or entry.get('position') or self.last_seen_cells.get(identity),
                   'gm_invisible': bool(entry['option'] & OPTION_INVISIBLE), 'age_seconds': round(now-entry['seen_at'], 1)}
                  for identity, entry in self.hidden.items()]
        return {'reason': self.reason(player_position, now), 'disguised': sorted(self.disguised),
                'hidden': sorted(self.hidden), 'hidden_details': hidden, 'players': sorted(self.players)}
