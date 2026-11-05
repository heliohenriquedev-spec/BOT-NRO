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
WIDEST = 5  # an area learned from an accidental warp never grows past this


def chebyshev(a, b):
    return max(abs(a[0]-b[0]), abs(a[1]-b[1]))


class PortalGuard:
    def __init__(self, path=None):
        self.path = Path(path or FILE)
        try:
            self.known = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.known = {}  # {map: {"x,y": margin}}
        self.links_path = self.path.with_name('portais_internos.json')
        # Areas proved by an accidental warp: never shrunk again (arriving next to a portal does).
        self.widened_path = self.path.with_name('portais_ampliados.json')
        try:
            self.widened = json.loads(self.widened_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.widened = {}  # {map: {"x,y": margin}}
        try:
            self.internal = json.loads(self.links_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.internal = {}  # {map: {"x,y": [x, y]}}: portals leading elsewhere on the same map
        self.last_own = None
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
                if kind == 'map_change' and event.get('position') and self.key(event.get('map')) == self.key(map_name):
                    self.learn_link(map_name, self.last_own, event['position'])
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
                    portals[cell] = max(self.floor(map_name, cell), min(MARGIN, near))
                    self.dirty = True
            elif kind == 'ground_effect' and event.get('effect_type') in WARP_SKILL_UNITS:
                self.temporary[event['effect_id']] = tuple(event['position'])
            elif kind == 'ground_effect_removed':
                self.temporary.pop(event['effect_id'], None)
        self.map_name = map_name
        if own_position:
            self.last_own = tuple(own_position)
        if (self.version, self.cells(map_name)) != before:
            self.version += 1
            return True
        return False

    def floor(self, map_name, cell):
        return self.widened.get(self.key(map_name), {}).get(cell, 0)

    def arrived(self, map_name, position):
        """Landing next to a portal usually means its area ends before there; not for the ones an
        accidental warp proved wider (gl_sew02 lands the character inside its portal's area)."""
        for cell, margin in self.known.get(self.key(map_name), {}).items():
            distance = chebyshev(position, tuple(map(int, cell.split(','))))
            smaller = max(distance-1, self.floor(map_name, cell))
            if smaller < margin:
                self.known[self.key(map_name)][cell] = max(0, smaller)
                self.dirty = True

    def learn_link(self, map_name, origin, destination):
        """Stepping on a known portal and landing far away on the same map: an inner portal, to
        another part of the map. Random teleports far from portals are not taken for one."""
        if origin is None or chebyshev(origin, destination) <= 5:
            return
        near = [(chebyshev(origin, cell), cell) for cell, margin in self.portals(map_name)
                if chebyshev(origin, cell) <= margin+2]
        if not near:
            return
        cell = min(near)[1]
        links = self.internal.setdefault(self.key(map_name), {})
        key = '%d,%d' % tuple(cell)
        if links.get(key) != list(destination):
            links[key] = list(destination)
            self.dirty = True
            self.version += 1

    def widen(self, map_name, path):
        """The character was warped walking along path: the nearest portal's area reached it.
        Returns (portal cell, new margin) or None."""
        best = None
        for cell, margin in self.portals(map_name):
            if cell in {c for c, _ in self.links(map_name)}:
                continue
            distance = min(chebyshev(point, cell) for point in path)
            if distance <= WIDEST and (best is None or distance < best[0]):
                best = (distance, cell, margin)
        if best is None:
            return None
        distance, cell, margin = best
        key = '%d,%d' % tuple(cell)
        portals = self.known.setdefault(self.key(map_name), {})
        if key not in portals or distance <= margin:
            return None
        portals[key] = distance
        self.widened.setdefault(self.key(map_name), {})[key] = distance
        self.dirty = True
        self.version += 1
        return cell, distance

    def links(self, map_name):
        """[(portal cell, arrival cell)] of the inner portals of this map."""
        return [(tuple(map(int, cell.split(','))), tuple(target)) for cell, target in self.internal.get(self.key(map_name), {}).items()]

    def portals(self, map_name):
        known = [(tuple(map(int, cell.split(','))), max(margin, self.floor(map_name, cell)))
                 for cell, margin in self.known.get(self.key(map_name), {}).items()]
        return known+[(cell, MARGIN) for cell in self.temporary.values()]

    def cells(self, map_name):
        """Cells never to walk on: portals to other maps. Inner portals stay free to use."""
        inner = {cell for cell, _ in self.links(map_name)}
        result = set()
        for (x, y), margin in self.portals(map_name):
            if (x, y) in inner:
                continue
            result.update((x+dx, y+dy) for dx in range(-margin, margin+1) for dy in range(-margin, margin+1))
        return frozenset(result)

    def save(self):
        if not self.dirty:
            return
        # The companion files always sit next to the main one (a test pointing path elsewhere
        # wrote the real portais_ampliados.json through the old names).
        self.links_path = self.path.with_name('portais_internos.json')
        self.widened_path = self.path.with_name('portais_ampliados.json')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.known, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(temporary, self.path)
        if self.internal:
            temporary = self.links_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.internal, ensure_ascii=False, indent=1), encoding='utf-8')
            os.replace(temporary, self.links_path)
        if self.widened:
            temporary = self.widened_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.widened, ensure_ascii=False, indent=1), encoding='utf-8')
            os.replace(temporary, self.widened_path)
        self.dirty = False
