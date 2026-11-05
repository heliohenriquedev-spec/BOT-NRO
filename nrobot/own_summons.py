"""The character's own summons and homunculus, known from packets only.

Summons: the server never says whose a summon is (the appearance byte that could is always 0
here). Evidence, strongest first: a creature CREATED (spawn packet 007C) in the few seconds after
one of the character's summon skills, up to 8 cells away (3 when only seen walking into view);
then it keeps walking to the character (confirmed). One that hits the character is not ours.
Leaving the view does not forget it: only its death or disappearance does.
Homunculus: the server names it in 0230 (state 0) and reports its hunger in 022E/0230 (state 2).
Feeding is the client's own homunculus menu command (022D, command 1), as the game sends it."""
import struct

from .network_targets import is_player_id

HOMUNCULUS_MENU = 0x22d
FEED = 1  # 0 = status, 1 = feed, 2 = DELETE: never anything but 1 is sent


def feed_packet(menu_type=0):
    return struct.pack('<HHB', HOMUNCULUS_MENU, menu_type, FEED)


class OwnSummons:
    WINDOW = 3.0  # seconds after a summon skill in which the creature appears
    DISTANCE = 3  # cells from the character, for a creature only seen entering the view
    SPAWN_DISTANCE = 8  # cells, for one the server says was just created
    FOLLOW = 3  # its walk ends this close to the character: it follows us
    FEED_WAIT = 8.0  # an unanswered feed is tried again after this
    NO_FOOD_WAIT = 120.0  # the server said no (no food in the bag): try again much later
    UNANSWERED = 3  # feeds with no answer at all (homunculus resting): wait as long as for no food

    def __init__(self):
        self.ids = set()
        self.confirmed = set()
        self.seen = set()
        self.until = 0.0
        self.homunculus = None
        self.hunger = None
        self.homunculus_name = None
        self.feed_type = 0
        self.feed_sent_at = None
        self.feed_blocked_until = 0.0
        self.unanswered = 0
        self.dead = False  # its death was seen: Remontar Marionete brings it back
        self.log = []

    def cast(self, now):
        """One of the character's summon skills went out (bot or player)."""
        self.until = now+self.WINDOW

    def forget(self, identity, reason):
        if identity in self.ids and reason:
            self.log.append({'kind': 'own_summon_dropped', 'entity_id': identity, 'reason': reason})
        self.ids.discard(identity)
        self.confirmed.discard(identity)

    def allies(self):
        return self.ids | ({self.homunculus} if self.homunculus else set())

    def observe(self, events, own_id, own_position, now, summon_skills=()):
        for event in events:
            kind = event['kind']
            identity = event.get('entity_id')
            if identity is not None and identity == self.homunculus:
                if kind == 'remove' and event.get('reason') == 1 and not self.dead:
                    self.dead = True
                    self.log.append({'kind': 'homunculus_died', 'entity_id': identity})
                elif kind == 'appearance':
                    self.dead = False
            if kind in ('map_change', 'map_transfer'):
                self.ids.clear()  # summons stay behind; the homunculus follows and is named again
                self.confirmed.clear()
                self.seen.clear()
            elif kind in ('skill_cast', 'skill_no_damage') and event.get('source_id') == own_id and event.get('skill_id') in summon_skills:
                self.cast(now)
            elif kind == 'appearance' and identity is not None and identity not in self.seen:
                self.seen.add(identity)
                position = event.get('position')
                reach = self.SPAWN_DISTANCE if event.get('spawned') else self.DISTANCE
                if (now <= self.until and identity != own_id and not is_player_id(identity)
                        and identity not in self.ids and own_position is not None and position is not None
                        and cells(position, own_position) <= reach):
                    self.ids.add(identity)
                    self.log.append({'kind': 'own_summon_seen', 'entity_id': identity, 'species_id': event.get('species_id'),
                                     'position': position, 'cells': cells(position, own_position),
                                     'evidence': 'criada agora' if event.get('spawned') else 'entrou na tela ao lado'})
            elif kind == 'move' and identity in self.ids and identity not in self.confirmed and own_position is not None:
                if event.get('destination') and cells(event['destination'], own_position) <= self.FOLLOW:
                    self.confirmed.add(identity)
                    self.log.append({'kind': 'own_summon_follows', 'entity_id': identity})
            elif (kind in ('normal_attack', 'skill_damage') and event.get('source_id') in self.ids
                  and event.get('target_id') == own_id):
                self.forget(event['source_id'], 'atacou o personagem: nao e sua')
            elif kind == 'remove' and identity is not None:
                self.seen.discard(identity)
                if event.get('reason') != 0:  # 0 = only left the view: it is still ours
                    self.forget(identity, None)
            elif kind == 'homunculus_state':
                if event['state'] == 0 and event['entity_id']:
                    self.dead = False
                    if event['entity_id'] != self.homunculus:
                        self.log.append({'kind': 'homunculus_seen', 'entity_id': event['entity_id']})
                    self.homunculus = event['entity_id']
                elif event['state'] == 2 and event['value'] <= 100:
                    self.hunger = event['value']
            elif kind == 'homunculus_status':
                self.hunger, self.homunculus_name = event['hunger'], event['name']
            elif kind == 'homunculus_fed':
                self.feed_sent_at = None
                self.unanswered = 0
                self.log.append({'kind': 'homunculus_fed', 'success': event['success'], 'item_id': event['item_id'],
                                 'hunger_before': self.hunger})
                # After a meal the new hunger comes in the same batch; a short wait keeps a late
                # update from causing a second feed.
                self.feed_blocked_until = now+(2.0 if event['success'] else self.NO_FOOD_WAIT)

    def learn_feed(self, frame):
        """The player fed it by hand: the same menu type is used from then on."""
        if len(frame) == 5 and frame[4] == FEED:
            self.feed_type = struct.unpack_from('<H', frame, 2)[0]
            self.log.append({'kind': 'homunculus_feed_by_player', 'packet_hex': frame.hex(), 'hunger': self.hunger})
            self.feed_sent_at = None
            return True
        return False

    def should_feed(self, threshold, now):
        """Hunger (only sent while a homunculus is out) at or below the chosen number, and no
        feed still waiting for the server's answer."""
        if self.hunger is None or self.hunger > threshold or now < self.feed_blocked_until:
            return False
        if self.feed_sent_at is not None and now-self.feed_sent_at < self.FEED_WAIT:
            return False
        if self.unanswered >= self.UNANSWERED:
            self.unanswered = 0
            self.feed_blocked_until = now+self.NO_FOOD_WAIT
            return False
        return True

    def sent(self, now):
        self.feed_sent_at = now
        self.unanswered += 1
        self.log.append({'kind': 'homunculus_feed_sent', 'hunger': self.hunger})

    def snapshot(self):
        return {'homunculus_id': self.homunculus, 'homunculus_name': self.homunculus_name,
                'hunger': self.hunger, 'summons': sorted(self.ids), 'summons_following': sorted(self.confirmed)}


def cells(a, b):
    return max(abs(a[0]-b[0]), abs(a[1]-b[1]))

