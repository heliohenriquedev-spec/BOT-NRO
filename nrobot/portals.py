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

Where each portal leads (data/mapas/portais_destinos.json, {map: {"x,y": {"map", "arrival",
"confirmed"}}}): crossing a known portal into another map records that portal -> new map and
the arrival cell (confirmed). The character lands next to the portal back, so the portal
nearest the arrival cell is recorded as leading to the map just left (inferred, never
overwriting a crossing actually seen).
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
BACK_RADIUS = 8  # cells from the arrival spot to the portal taken for the way back


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
        self.destinations_path = self.path.with_name('portais_destinos.json')
        try:
            self.destinations = json.loads(self.destinations_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.destinations = {}
            try:  # the automatic routes file exists from the start; each portal crossed fills it
                self.destinations_path.parent.mkdir(parents=True, exist_ok=True)
                if not self.destinations_path.exists():
                    self.destinations_path.write_text('{}', encoding='utf-8')
            except OSError:
                pass
        self.pending_back = None  # {'map', 'arrival', 'from_map', 'from_cell'} until a portal is seen
        for map_name, cells in list(self.destinations.items()):  # a crossing seen beats an inner link
            for cell, link in cells.items():
                if link.get('confirmed') and cell in self.internal.get(map_name, {}):
                    del self.internal[map_name][cell]
        self.last_own = None
        self.last_target = None  # where the character was walking to (into the portal, usually)
        self.temporary = {}  # Warp Portal skill cells on the current map
        self.map_name = None
        self.dirty = False
        self.version = 0

    @staticmethod
    def key(map_name):
        return (map_name or '').lower().removesuffix('.gat').removesuffix('.rsw')

    def observe(self, events, map_name, own_position=None, own_destination=None):
        """map_name is the relay's current map, already the new one when a map change is in events:
        the map the change starts from is the one this guard saw last (self.map_name)."""
        before = (self.version, self.cells(map_name))
        changes = any(e['kind'] in ('map_change', 'map_transfer') for e in events)
        current = (self.map_name or map_name) if changes else map_name
        for event in events:
            kind = event['kind']
            if kind in ('map_change', 'map_transfer'):
                self.temporary.clear()
                if kind == 'map_change' and event.get('position') and self.key(event.get('map')) == self.key(current):
                    self.learn_link(current, self.last_own, event['position'])
                elif event.get('map') and event.get('position') and current:
                    self.learn_destination(current, self.last_own, event['map'], event['position'], self.last_target)
                else:
                    self.pending_back = None
                current = event.get('map') or current
                if kind == 'map_change' and event.get('position'):
                    self.arrived(current, event['position'])
            elif kind == 'player_position_init':
                self.arrived(current, event['position'])
            elif kind == 'appearance' and event.get('species_id') in WARP_SPRITES and event.get('position'):
                portals = self.known.setdefault(self.key(current), {})
                cell = '%d,%d' % tuple(event['position'])
                if cell not in portals:
                    # Standing here unwarped proves the own cell is outside the touch area.
                    near = chebyshev(own_position, event['position'])-1 if own_position else MARGIN
                    portals[cell] = max(self.floor(current, cell), min(MARGIN, near))
                    self.dirty = True
                self.resolve_back(current)
            elif kind == 'ground_effect' and event.get('effect_type') in WARP_SKILL_UNITS:
                self.temporary[event['effect_id']] = tuple(event['position'])
            elif kind == 'ground_effect_removed':
                self.temporary.pop(event['effect_id'], None)
        self.map_name = map_name
        if own_position:
            self.last_own = tuple(own_position)
        if any(e['kind'] in ('map_change', 'map_transfer') for e in events):
            self.last_target = None
        elif own_destination:
            self.last_target = tuple(own_destination)
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

    def learn_destination(self, from_map, origin, to_map, arrival, target=None):
        """Crossed a portal of from_map and landed at arrival on to_map. The last position known
        is often where a long walk into the portal began: the walk's destination counts too."""
        self.pending_back = None
        if self.key(from_map) == self.key(to_map):
            return
        near = [(chebyshev(point, cell), cell) for point in (origin, target) if point is not None
                for cell, margin in self.portals(from_map) if chebyshev(point, cell) <= margin+2]
        if not near:
            return  # teleport, NPC transport or @voltar: no portal crossed
        cell = min(near)[1]
        self.set_destination(from_map, cell, to_map, arrival, True)
        self.pending_back = {'map': to_map, 'arrival': list(arrival), 'from_map': from_map, 'from_cell': list(cell)}
        self.resolve_back(to_map)

    def resolve_back(self, map_name):
        """The portal nearest the arrival spot leads back to the map just left."""
        pending = self.pending_back
        if not pending or self.key(pending['map']) != self.key(map_name):
            return
        near = [(chebyshev(pending['arrival'], cell), cell) for cell, _ in self.portals(map_name)
                if chebyshev(pending['arrival'], cell) <= BACK_RADIUS]
        if not near:
            return
        self.pending_back = None
        cell = min(near)[1]
        current = self.destinations.get(self.key(map_name), {}).get('%d,%d' % tuple(cell))
        if current and current.get('confirmed') and self.key(current.get('map')) != self.key(pending['from_map']):
            return
        if not (current and current.get('confirmed')):
            self.set_destination(map_name, cell, pending['from_map'], pending['from_cell'], False)

    def set_destination(self, map_name, cell, to_map, arrival, confirmed):
        links = self.destinations.setdefault(self.key(map_name), {})
        key = '%d,%d' % tuple(cell)
        inner = self.internal.get(self.key(map_name), {})
        if confirmed and key in inner:
            # Crossed into another map: it was never an inner portal (an older bug took map
            # changes for inner links, e.g. kakashi 52,2). Walking into it would leave the map.
            del inner[key]
            if not inner:
                self.internal.pop(self.key(map_name), None)
            self.dirty = True
        value = {'map': self.key(to_map), 'arrival': [int(v) for v in arrival], 'confirmed': bool(confirmed)}
        current = links.get(key) or {}
        if current.get('varies') or (confirmed and current.get('confirmed') and self.key(current.get('map', '')) != value['map']):
            # Crossed twice into different maps: the portal leads back to where the character came
            # from (payon_in03 20,60: areia or nuvem). Never a way between two villages.
            value['varies'] = True
        if links.get(key) != value:
            links[key] = value
            self.dirty = True
            self.version += 1

    def destination(self, map_name, cell):
        """{'map', 'arrival', 'confirmed'} of a portal, or None."""
        return self.destinations.get(self.key(map_name), {}).get('%d,%d' % tuple(cell))

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
        self.destinations_path = self.path.with_name('portais_destinos.json')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.known, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(temporary, self.path)
        if self.internal or self.links_path.exists():
            temporary = self.links_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.internal, ensure_ascii=False, indent=1), encoding='utf-8')
            os.replace(temporary, self.links_path)
        if self.destinations or not self.destinations_path.exists():
            temporary = self.destinations_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.destinations, ensure_ascii=False, indent=1), encoding='utf-8')
            os.replace(temporary, self.destinations_path)
        if self.widened:
            temporary = self.widened_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.widened, ensure_ascii=False, indent=1), encoding='utf-8')
            os.replace(temporary, self.widened_path)
        self.dirty = False
