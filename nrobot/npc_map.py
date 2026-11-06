"""NPCs of each map for the minimap: cell and name, remembered between sessions.

The server sends NPCs like monsters, but with a server-side id from the NPC pool (rAthena
START_NPC_NUM, 110000000+) and a sprite below 1000. Warps and invisible NPCs are not shown.
The client asks an NPC's name only when the mouse passes over it, so names arrive over time;
NPC steps of recorded routes also bring their names. Saved in data/mapas/npcs.json:
{map: {"x,y": {"name": str, "sprite": int}}}.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .npc_labels import clean
from .portals import PortalGuard

FILE = Path(__file__).resolve().parents[1]/'data'/'mapas'/'npcs.json'
NPC_IDS = 100_000_000
HIDDEN = {45, 111, 139, 844}  # warp, invisible NPC, invisible warp, hidden warp


def is_npc(entity):
    species = entity.get('species_id')
    return (type(species) is int and 0 <= species < 1000 and species not in HIDDEN
            and (entity.get('entity_id') or 0) >= NPC_IDS and not entity.get('owner_id'))


def display_name(name):
    return clean(name or '').split('#', 1)[0].strip()


class NpcMap:
    def __init__(self, path=None):
        self.path = Path(path or FILE)
        try:
            self.known = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.known = {}
        self.dirty = False

    def add(self, map_name, position, name='', sprite=None):
        if not map_name or not position or len(position) != 2:
            return
        if any(type(v) is not int or not 0 <= v < 1024 for v in position):
            return
        cells = self.known.setdefault(PortalGuard.key(map_name), {})
        cell = '%d,%d' % tuple(position)
        entry = cells.get(cell)
        name = display_name(name)
        if entry is None:
            cells[cell] = {'name': name, 'sprite': sprite}
            self.dirty = True
        elif name and entry.get('name') != name:
            entry['name'] = name
            self.dirty = True

    def observe(self, entities, map_name):
        for entity in entities:
            if is_npc(entity) and entity.get('position'):
                self.add(map_name, list(entity['position']), entity.get('name') or '', entity.get('species_id'))

    def learn_steps(self, steps):
        """NPC steps of recorded routes carry the NPC's name and cell."""
        for step in steps or []:
            if step.get('kind') == 'npc' and step.get('map') and step.get('position'):
                self.add(step['map'], list(step['position']), step.get('name') or '')

    def for_map(self, map_name):
        cells = self.known.get(PortalGuard.key(map_name), {})
        return [{'position': [int(v) for v in cell.split(',')], 'name': entry.get('name') or ''}
                for cell, entry in cells.items()]

    def save(self):
        if not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.known, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(temporary, self.path)
        self.dirty = False
