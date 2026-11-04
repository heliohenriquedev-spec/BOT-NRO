"""Every character ever seen in the game, kept between sessions (aba Jogadores).

Facts come only from server packets: the game id, the name/guild the client asks for when a
character appears, the class (sprite id) of appearance packets, the map and the last cell.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .network_targets import is_player_id
from .presence_guard import monster_sprite, HIDDEN_OPTIONS

FILE = Path(__file__).resolve().parents[1]/'data'/'jogadores'/'registro.json'


def load(path=None):
    try:
        return json.loads(Path(path or FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


class PlayerRegistry:
    def __init__(self, path=None):
        self.path = Path(path or FILE)
        self.players = load(self.path)
        self.dirty = False
        self.in_view = set()

    def observe(self, events, own_id, map_name, now=None):
        stamp = (now or datetime.now()).isoformat(timespec='seconds')
        for event in events:
            kind = event['kind']
            if kind in ('map_change', 'map_transfer'):
                self.in_view.clear()
                continue
            identity = event.get('entity_id')
            if identity is None or identity == own_id or not is_player_id(identity):
                continue
            if kind == 'remove':
                self.in_view.discard(identity)
                continue
            if kind == 'actor_signal' and event.get('signal') == 'chat' and event.get('name'):
                kind, event = 'name', {**event, 'kind': 'name'}  # "Name : text" in public chat names the speaker
            if kind not in ('appearance', 'name', 'move', 'position', 'option_change'):
                continue
            entry = self.players.setdefault(str(identity), {'entity_id': identity, 'first_seen': stamp,
                                                            'sightings': 0, 'maps': []})
            if kind == 'appearance':
                if identity not in self.in_view:
                    entry['sightings'] += 1
                self.in_view.add(identity)
                species = event.get('species_id')
                if species is not None and monster_sprite(species):
                    entry['disguised'] = species
                elif species is not None:
                    entry['job'] = species
                look = event.get('look')
                if look and not entry.get('disguised') == species:
                    for field in ('level', 'sex', 'guild_id'):
                        if look.get(field) is not None:
                            entry[field] = look[field]
                    entry['look'] = {k: v for k, v in look.items() if k not in ('level', 'sex', 'guild_id')}
            if kind == 'name' and event.get('name'):
                if entry.get('name') and entry['name'] != event['name']:
                    history = entry.setdefault('former_names', [])
                    if entry['name'] not in history:
                        history.append(entry['name'])  # same id, another name: renamed or another character
                entry['name'] = event['name']
                for field in ('guild', 'guild_title', 'party'):
                    if event.get(field):
                        entry[field] = event[field]
            if event.get('option', 0) & HIDDEN_OPTIONS:
                entry['hidden_seen'] = 'gm' if event['option'] & 0x40 else 'hide'
            if 'position' in event:
                entry['last_position'] = list(event.get('destination') or event['position'])
            if map_name:
                entry['last_map'] = map_name
                if map_name not in entry['maps']:
                    entry['maps'].append(map_name)
            entry['last_seen'] = stamp
            self.dirty = True

    def save(self):
        if not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.players, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(temporary, self.path)
        self.dirty = False
