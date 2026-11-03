"""Portals (warps) the bot must never walk into: crossing one changes the map.

Warps are server NPCs, so the client learns them only from packets: an appearance with the
warp sprite (45, or 139 for invisible warps) or a Warp Portal skill cell (ground effect
0x80/0x81). The server does not send the size of the touch area, so a margin is kept around
each portal. Every portal seen is remembered per map (data/mapas/portais.json), so the area is
avoided from the moment the map loads, before the portal is in view again.

The arrival cell after a warp (and the cell the character stands on when a portal comes into
view) lies outside every touch area (otherwise the character would be
warped again), so a portal closer than the margin to that cell has its margin reduced to keep
the way out of the arrival spot open.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

FILE = Path(__file__).resolve().parents[1]/'data'/'mapas'/'portais.json'
WARP_SPRITES = {45, 139}
WARP_SKILL_UNITS = {0x80, 0x81}
MARGIN = 3  # cells around the portal (Chebyshev); common warps trigger within 1-2


def chebyshev(a, b):
    return max(abs(a[0]-b[0]), abs(a[1]-b[1]))


class PortalGuard:
    def __init__(self, path=None):
        self.path = Path(path or FILE)
        try:
            self.known = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.known = {}  # {map: {"x,y": margin}}
        self.temporary = {}  # Warp Portal skill cells on the current map
        self.map_name = None
        self.dirty = False
        self.version = 0

    @staticmethod
    def key(map_name):
        return (map_name or '').lower().removesuffix('.gat').removesuffix('.rsw')

    def observe(self, events, map_name, own_position=None):
        before = (self.version, self.cells(map_name))
        for event in events:
            kind = event['kind']
            if kind in ('map_change', 'map_transfer'):
                self.temporary.clear()
                if kind == 'map_change':
                    map_name = event.get('map') or map_name
                    if event.get('position'):
                        self.arrived(map_name, event['position'])
            elif kind == 'player_position_init':
                self.arrived(map_name, event['position'])
            elif kind == 'appearance' and event.get('species_id') in WARP_SPRITES and event.get('position'):
                portals = self.known.setdefault(self.key(map_name), {})
                cell = '%d,%d' % tuple(event['position'])
                if cell not in portals:
                    # Standing here unwarped proves the own cell is outside the touch area.
                    near = chebyshev(own_position, event['position'])-1 if own_position else MARGIN
                    portals[cell] = max(0, min(MARGIN, near))
                    self.dirty = True
            elif kind == 'ground_effect' and event.get('effect_type') in WARP_SKILL_UNITS:
                self.temporary[event['effect_id']] = tuple(event['position'])
            elif kind == 'ground_effect_removed':
                self.temporary.pop(event['effect_id'], None)
        self.map_name = map_name
        if (self.version, self.cells(map_name)) != before:
            self.version += 1
            return True
        return False

    def arrived(self, map_name, position):
        for cell, margin in self.known.get(self.key(map_name), {}).items():
            distance = chebyshev(position, tuple(map(int, cell.split(','))))
            if distance-1 < margin:
                self.known[self.key(map_name)][cell] = max(0, distance-1)
                self.dirty = True

    def portals(self, map_name):
        known = [(tuple(map(int, cell.split(','))), margin) for cell, margin in self.known.get(self.key(map_name), {}).items()]
        return known+[(cell, MARGIN) for cell in self.temporary.values()]

    def cells(self, map_name):
        result = set()
        for (x, y), margin in self.portals(map_name):
            result.update((x+dx, y+dy) for dx in range(-margin, margin+1) for dy in range(-margin, margin+1))
        return frozenset(result)

    def save(self):
        if not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.known, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(temporary, self.path)
        self.dirty = False
