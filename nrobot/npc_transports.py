"""NPC transports learned while playing: the Kakashi return, the VIP room access, the VIP room...

When the player clicks an NPC, goes through its dialog (next, options) and the map changes right
after, that conversation becomes a link between the two maps, with the same steps a recorded path
has (npc, next, select ..., wait_map). auto_routes joins these links with the portals crossed, so
the quests, the BG entry and the database hunt reach maps through NPCs too, without recording.
Saved in data/mapas/npc_transportes.json: {map: {key: {'steps', 'to', 'arrival', 'name'}}}.
Walking after the talk means the map changed through a portal, not the NPC: nothing is learned
(the hospital healers became "transports" to areia that way, 2026-11-07). A transport that does
not change the map when used is discarded: DISCARDED lists it, and the list travels with the
shared data so the other PCs drop it too.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import time

from .portals import PortalGuard

FILE = Path(__file__).resolve().parents[1]/'data'/'mapas'/'npc_transportes.json'
SHARED_FILE = Path(__file__).resolve().parents[1]/'data'/'compartilhado'/'npc_transportes.json'
WINDOW = 15.0  # s between the last dialog action and the map change
ROUTES_ONLY = {0x90, 0xb8, 0xb9, 0x146}  # click NPC, menu choice, next, close
WALK = 0xa7  # the player's own walk request: a map change after it came from a portal
DISCARDED = '_descartados'  # {map: {key: reason}}: transports that proved false


def read_discarded(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8-sig')).get(DISCARDED)
    except (OSError, ValueError, AttributeError):
        return {}
    return value if isinstance(value, dict) else {}


def add_discarded(known, discarded):
    """Union of discard lists. Returns True if something new was added."""
    added = False
    for map_name, keys in (discarded or {}).items():
        if not isinstance(keys, dict):
            continue
        mine = known.setdefault(DISCARDED, {}).setdefault(map_name, {})
        for key, reason in keys.items():
            if key not in mine:
                mine[key] = reason
                added = True
    return added


def harmful(steps):
    """A talk whose menu gives up a mission (the boards send the character away after it) is
    never a transport: taking it would abandon the mission."""
    return any(s.get('kind') == 'select' and 'desistir' in str(s.get('option', '')).casefold() for s in steps or [])


def purge(known):
    """Drops the transports listed as discarded (here or on another PC) and the harmful ones.
    Returns True if any."""
    removed = False
    for map_name, links in list((known or {}).items()):
        if map_name == DISCARDED or not isinstance(links, dict):
            continue
        for key, value in list(links.items()):
            if isinstance(value, dict) and harmful(value.get('steps')):
                del links[key]
                removed = True
    for map_name, keys in ((known or {}).get(DISCARDED) or {}).items():
        links = known.get(map_name)
        if not isinstance(links, dict) or not isinstance(keys, dict):
            continue
        for key in keys:
            if key in links:
                del links[key]
                removed = True
    return removed


def gat(map_name):
    return PortalGuard.key(map_name)+'.gat'


class NpcTransports:
    def __init__(self, path=None):
        self.path = Path(path or FILE)
        try:
            self.known = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.known = {}
        self.talk = None  # conversation in progress: {'map', 'npc', 'steps', 'at'}
        self.options = {}  # NPC id -> menu options last shown
        # The published discard list counts here too: an older connection rewrote this file with
        # the hospital healers back in it and no list (2026-11-07).
        added = add_discarded(self.known, read_discarded(SHARED_FILE)) if self.path == FILE else False
        self.dirty = purge(self.known) or added

    def client(self, opcode, frame, map_name, actors, now=None):
        """A frame the game client sent (the player's own clicks)."""
        now = time.monotonic() if now is None else now
        if opcode == WALK:
            self.talk = None  # walked away: a map change now is a portal's
            return
        if opcode not in ROUTES_ONLY or not map_name:
            return
        identity = struct.unpack_from('<I', frame, 2)[0] if len(frame) >= 6 else None
        if opcode == 0x90:
            actor = actors.get(identity) or {}
            if not actor.get('position'):
                self.talk = None
                return
            self.talk = dict(map=map_name, npc=identity, at=now,
                             steps=[dict(kind='npc', map=gat(map_name), position=list(actor['position']),
                                         name=actor.get('name') or '')])
            return
        talk = self.talk
        if not talk or talk['npc'] != identity or PortalGuard.key(talk['map']) != PortalGuard.key(map_name):
            return
        if opcode == 0xb9:
            talk['steps'].append(dict(kind='next', map=gat(map_name)))
        elif opcode == 0x146:
            talk['steps'].append(dict(kind='close', map=gat(map_name)))
        else:
            choice = frame[6] if len(frame) == 7 else 0
            options = self.options.get(identity) or []
            if choice == 255 or not 1 <= choice <= len(options):
                self.talk = None  # cancelled: no transport here
                return
            talk['steps'].append(dict(kind='select', map=gat(map_name), option=options[choice-1]))
        talk['at'] = now

    def observe(self, events, map_name, now=None):
        """Server events: menus shown and the map change that ends a transport conversation."""
        now = time.monotonic() if now is None else now
        for event in events:
            if event['kind'] == 'npc_dialog' and event.get('options'):
                self.options[event.get('entity_id')] = list(event['options'])
            elif event['kind'] in ('map_change', 'map_transfer') and event.get('map'):
                talk, self.talk = self.talk, None
                if (talk and now-talk['at'] <= WINDOW and len(talk['steps']) >= 1
                        and PortalGuard.key(event['map']) != PortalGuard.key(talk['map'])):
                    self.learn(talk, event['map'], event.get('position'))

    def learn(self, talk, to_map, arrival):
        steps = [s for s in talk['steps'] if s['kind'] != 'close']+[dict(kind='wait_map', map=gat(to_map))]
        if harmful(steps):
            return
        first = steps[0]
        choices = '|'.join(s.get('option', '') for s in steps if s['kind'] == 'select')
        key = '%d,%d>%s>%s' % (first['position'][0], first['position'][1], PortalGuard.key(to_map), choices)
        links = self.known.setdefault(PortalGuard.key(talk['map']), {})
        discarded = (self.known.get(DISCARDED) or {}).get(PortalGuard.key(talk['map'])) or {}
        if key in discarded:
            del discarded[key]  # really seen changing the map again (no walk in between)
            self.dirty = True
        value = dict(steps=steps, to=PortalGuard.key(to_map), name=first.get('name', ''),
                     arrival=list(arrival) if arrival else None)
        if links.get(key) != value:
            links[key] = value
            self.dirty = True

    def forget(self, map_name, position, to_map, reason='nao trocou de mapa'):
        """The NPC at this cell did not take the character to to_map: the transport is dropped and
        listed as discarded. Returns the NPC names dropped."""
        here, there = PortalGuard.key(map_name), PortalGuard.key(to_map)
        links = self.known.get(here) or {}
        names = []
        for key, value in list(links.items()):
            first = (value.get('steps') or [{}])[0] if isinstance(value, dict) else {}
            if value.get('to') == there and list(first.get('position') or []) == list(position):
                del links[key]
                self.known.setdefault(DISCARDED, {}).setdefault(here, {})[key] = reason
                names.append(value.get('name') or 'NPC')
                self.dirty = True
        return names

    def save(self):
        if not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Discards written meanwhile by another connection are kept, and never written back.
        add_discarded(self.known, read_discarded(self.path))
        purge(self.known)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.known, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(temporary, self.path)
        self.dirty = False


def talk_key(steps):
    """The NPC cell and the options chosen, without the map reached."""
    first = steps[0] if steps else {}
    choices = '|'.join(s.get('option', '') for s in steps if s.get('kind') == 'select')
    return (tuple(first.get('position') or ()), choices)


def as_entries(known):
    """The learned transports in the shape of recorded paths, for auto_routes and the quests."""
    entries = []
    for links in (known or {}).values():
        targets = {}
        for value in (links or {}).values():
            if isinstance(value, dict) and value.get('steps') and value.get('to'):
                targets.setdefault(talk_key(value['steps']), set()).add(value['to'])
        for value in (links or {}).values():
            if isinstance(value, dict) and value.get('steps') and value.get('to'):
                if len(targets.get(talk_key(value['steps']), ())) > 1:
                    # The same talk took the character to different maps: Retorno and other save-point
                    # NPCs (hospital2 or hospital4, depending on where it is saved). Not a fixed way.
                    continue
                steps = [dict(s) for s in value['steps']]
                if value.get('arrival'):
                    steps.append(dict(kind='walk', map=gat(value['to']), position=list(value['arrival'])))
                entries.append(dict(id='', name=value.get('name') or 'NPC', target_map=gat(value['to']), steps=steps,
                                    needs_recording=False))
    return entries
