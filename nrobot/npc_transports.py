"""NPC transports learned while playing: the Kakashi return, the VIP room access, the VIP room...

When the player clicks an NPC, goes through its dialog (next, options) and the map changes right
after, that conversation becomes a link between the two maps, with the same steps a recorded path
has (npc, next, select ..., wait_map). auto_routes joins these links with the portals crossed, so
the quests, the BG entry and the database hunt reach maps through NPCs too, without recording.
Saved in data/mapas/npc_transportes.json: {map: {key: {'steps', 'to', 'arrival', 'name'}}}.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import time

from .portals import PortalGuard

FILE = Path(__file__).resolve().parents[1]/'data'/'mapas'/'npc_transportes.json'
WINDOW = 15.0  # s between the last dialog action and the map change
ROUTES_ONLY = {0x90, 0xb8, 0xb9, 0x146}  # click NPC, menu choice, next, close


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
        self.dirty = False

    def client(self, opcode, frame, map_name, actors, now=None):
        """A frame the game client sent (the player's own clicks)."""
        now = time.monotonic() if now is None else now
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
        first = steps[0]
        choices = '|'.join(s.get('option', '') for s in steps if s['kind'] == 'select')
        key = '%d,%d>%s>%s' % (first['position'][0], first['position'][1], PortalGuard.key(to_map), choices)
        links = self.known.setdefault(PortalGuard.key(talk['map']), {})
        value = dict(steps=steps, to=PortalGuard.key(to_map), name=first.get('name', ''),
                     arrival=list(arrival) if arrival else None)
        if links.get(key) != value:
            links[key] = value
            self.dirty = True

    def save(self):
        if not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.known, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(temporary, self.path)
        self.dirty = False


def as_entries(known):
    """The learned transports in the shape of recorded paths, for auto_routes and the quests."""
    entries = []
    for links in (known or {}).values():
        for value in (links or {}).values():
            if isinstance(value, dict) and value.get('steps') and value.get('to'):
                steps = [dict(s) for s in value['steps']]
                if value.get('arrival'):
                    steps.append(dict(kind='walk', map=gat(value['to']), position=list(value['arrival'])))
                entries.append(dict(id='', name=value.get('name') or 'NPC', target_map=gat(value['to']), steps=steps,
                                    needs_recording=False))
    return entries
