"""REDE-31: read-only GAT maps and bounded collision-aware routing."""
from __future__ import annotations

import base64
import heapq
import json
import math
from pathlib import Path, PureWindowsPath
import struct
import zlib
from collections import deque

from .grf import GrfSet, GrfError


WALKABLE_TYPES = (0, 2, 3, 4, 6)


def read_map_caches(folder):
    """REDE-64: server-side map caches; the client GRFs of NRO are encrypted (SecureGRF).

    Supports rAthena/eAthena map_cache.dat (8-byte header, then name[12], xs, ys, len and
    zlib cells per map) and Hercules *.mcache (version, md5[16], xs, ys, len, zlib cells).
    Returns {map name without extension: (width, height, compressed cells)}.
    """
    maps = {}
    folder = Path(folder)
    if not folder.is_dir():
        return maps
    for path in sorted(folder.rglob('*')):
        if path.suffix.lower() == '.dat':
            data = path.read_bytes()
            if len(data) < 8:
                continue
            count = struct.unpack_from('<H', data, 4)[0]
            for header in (8, 6):
                offset, found = header, {}
                try:
                    for _ in range(count):
                        name = data[offset:offset+12].split(b'\0')[0].decode('latin-1').lower()
                        xs, ys, length = struct.unpack_from('<hhi', data, offset+12)
                        offset += 20
                        if not name or not 1 <= xs <= 1024 or not 1 <= ys <= 1024 or not 0 < length <= len(data)-offset:
                            raise ValueError
                        found[name] = (xs, ys, data[offset:offset+length])
                        offset += length
                except (ValueError, struct.error):
                    continue
                if found and offset == len(data):
                    maps.update(found)
                    break
        elif path.suffix.lower() == '.mcache':
            data = path.read_bytes()
            for header in (26, 28):
                try:
                    xs, ys, length = struct.unpack_from('<hhi', data, header-8)
                    if (1 <= xs <= 1024 and 1 <= ys <= 1024 and header+length == len(data)
                            and len(zlib.decompress(data[header:])) == xs*ys):
                        maps[path.stem.lower()] = (xs, ys, data[header:])
                        break
                except (struct.error, zlib.error):
                    continue
    return maps


BUNDLED_MAPS = Path(__file__).resolve().parents[1]/'data'/'recursos'/'colisoes.json'


def read_bundled_maps(path):
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return {name: (width, height, base64.b64decode(cells))
            for name, (width, height, cells) in payload.items()}


class CollisionMap:
    def __init__(self, width, height, cells):
        self.width, self.height, self.cells = width, height, bytes(cells)
        self.components = {}
        self.clearances = {}
        self.forbidden = frozenset()  # portal areas: walking in would change the map
        self.links = ()  # inner portals: (cell, arrival) on this same map
        if not 1 <= width <= 1024 or not 1 <= height <= 1024 or len(cells) != width*height:
            raise ValueError('Dimensões de colisão inválidas')

    @classmethod
    def from_gat(cls, data):
        if len(data) < 14 or data[:6] != b'GRAT\x01\x02':
            raise ValueError('GAT ausente ou versão não suportada')
        width, height = struct.unpack_from('<II', data, 6)
        if not 1 <= width <= 1024 or not 1 <= height <= 1024 or len(data) != 14+width*height*20:
            raise ValueError('GAT truncado ou dimensões inválidas')
        cells = [struct.unpack_from('<I', data, 30+i*20)[0] in WALKABLE_TYPES
                 for i in range(width*height)]
        return cls(width, height, cells)

    @classmethod
    def from_cell_types(cls, width, height, types):
        """Server map cache: one GAT cell type per byte."""
        if len(types) != width*height:
            raise ValueError('Cache de mapa com tamanho inconsistente')
        return cls(width, height, [t in WALKABLE_TYPES for t in types])

    def walkable(self, point):
        x, y = point
        return (0 <= x < self.width-1 and 0 <= y < self.height-1 and bool(self.cells[y*self.width+x])
                and (not self.forbidden or (x, y) not in self.forbidden))

    def ground(self, point):
        """Walkable ground, portal areas included."""
        x, y = point
        return 0 <= x < self.width-1 and 0 <= y < self.height-1 and bool(self.cells[y*self.width+x])

    def start_ok(self, point):
        """Where a walk may start: the character can stand inside a portal's area (it arrives
        there); only stepping onto one of its cells warps, so leaving it is allowed."""
        return self.walkable(point) or self.ground(point)

    def plain(self):
        """The same ground without the forbidden cells (portal areas, enemy skill areas): for
        "is there a wall in between?" questions. An area skill on the floor is not a wall: with
        the character standing in one, every monster around was taken as behind a wall and none
        was attacked (ra_fild03 2026-11-06, died standing still)."""
        if not self.forbidden:
            return self
        view = getattr(self, '_plain_view', None)
        if view is None or view.cells is not self.cells:
            view = object.__new__(type(self))
            view.__dict__.update({k: v for k, v in self.__dict__.items() if k != '_plain_view'})
            view.forbidden = frozenset()
            view.components, view.clearances = {}, {}
            self._plain_view = view
        return view

    def set_forbidden(self, cells):
        """Cells no route, step or patrol may use (portal areas); clears derived caches."""
        cells = frozenset(cells)
        if cells != self.forbidden:
            self.forbidden = cells
            self.components, self.clearances = {}, {}

    def edge(self, start, end, blocked=frozenset()):
        dx, dy = end[0]-start[0], end[1]-start[1]
        if max(abs(dx), abs(dy)) != 1 or tuple(end) in blocked or not self.walkable(end):
            return False
        if dx and dy:
            return all(self.walkable(p) and p not in blocked
                       for p in ((start[0]+dx, start[1]), (start[0], start[1]+dy)))
        return True

    def melee_reachable(self, start, target):
        """The same adjacent-cell rule is used to plan and authorize a basic attack."""
        start, target = tuple(start), tuple(target)
        return self.walkable(start) and self.walkable(target) and (start == target or self.edge(start, target))

    def clearance(self, point):
        point = tuple(point)
        if point in self.clearances:
            return self.clearances[point]
        for distance in (1, 2):
            for dx in range(-distance, distance+1):
                for dy in range(-distance, distance+1):
                    if max(abs(dx), abs(dy)) == distance and not self.walkable((point[0]+dx, point[1]+dy)):
                        self.clearances[point] = distance
                        return distance
        self.clearances[point] = 3
        return 3

    def segment(self, start, end, blocked=frozenset(), *, max_steps=4, wall_margin=0):
        """The cells the server walks for a move request: its direct path goes diagonally first,
        then straight (rAthena path_search). Checking an even line instead let gl_sew02's first step
        go diagonally into its portal while the bot thought it walked straight past it."""
        start, end = tuple(start), tuple(end)
        steps = max(abs(end[0]-start[0]), abs(end[1]-start[1]))
        if not self.start_ok(start) or not 1 <= steps <= max_steps:
            return False
        point = start
        for nxt in server_line(start, end):
            if not self.edge(point, nxt, blocked) or (wall_margin and self.clearance(nxt) < wall_margin):
                return False
            point = nxt
        return True

    def route(self, start, target, blocked=frozenset(), max_nodes=6000, *, exact=False, visited_sectors=frozenset(),
              revisit_cost=2.5, greed=1.0, partial=False, wall_cost=2):
        """A* path. greed > 1 weights the heuristic (much faster, slightly longer paths);
        partial returns the path to the expanded cell closest to target when the budget runs out."""
        start, target = tuple(start), tuple(target)
        if not self.start_ok(start) or not self.walkable(target):
            return None
        # Adjacent ground avoids attacking through thin walls or across a gap.
        def goal(p):
            return p == target or (not exact and max(abs(p[i]-target[i]) for i in (0, 1)) == 1
                                   and self.edge(p, target))
        def heuristic(p):
            dx, dy = abs(p[0]-target[0]), abs(p[1]-target[1])
            return max(0, max(dx, dy)+(math.sqrt(2)-1)*min(dx, dy)-math.sqrt(2))
        heap, costs, parents = [(heuristic(start)*greed, 0, start)], {start: 0}, {}
        expanded = 0
        closest = (heuristic(start), start)
        while heap and expanded < max_nodes:
            _, cost, point = heapq.heappop(heap)
            if cost != costs[point]:
                continue
            expanded += 1
            if partial:
                closest = min(closest, (heuristic(point), point))
            if goal(point):
                path = [point]
                while point in parents:
                    point = parents[point]
                    path.append(point)
                return path[::-1]
            for dx, dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                nxt = (point[0]+dx, point[1]+dy)
                if not self.edge(point, nxt, blocked):
                    continue
                new_cost = cost+(math.sqrt(2) if dx and dy else 1)
                new_cost += max(0, 3-self.clearance(nxt))*wall_cost
                if (nxt[0]//4, nxt[1]//4) in visited_sectors and (nxt[0]//4, nxt[1]//4) != (start[0]//4, start[1]//4):
                    new_cost += revisit_cost
                if new_cost < costs.get(nxt, float('inf')):
                    costs[nxt], parents[nxt] = new_cost, point
                    heapq.heappush(heap, (new_cost+heuristic(nxt)*greed, new_cost, nxt))
        if partial and closest[1] != start:
            point, path = closest[1], [closest[1]]
            while point in parents:
                point = parents[point]
                path.append(point)
            return path[::-1]
        return None

    def reachable(self, start):
        start = tuple(start)
        if not self.start_ok(start):
            return frozenset()
        if start in self.components:
            return self.components[start]
        visited, queue = {start}, deque([start])
        while queue:
            point = queue.popleft()
            for dx, dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                nxt = (point[0]+dx, point[1]+dy)
                if nxt not in visited and self.edge(point, nxt):
                    visited.add(nxt)
                    queue.append(nxt)
        component = frozenset(visited)
        # One shared component object per cell; avoids recomputing on each start.
        for point in visited:
            self.components[point] = component
        return component

    def line_clear(self, start, end):
        # Conservative supercover: use walkable ground as a safe subset of shootable cells.
        start, end = tuple(start), tuple(end)
        length = max(abs(end[i]-start[i]) for i in (0, 1))
        if not self.walkable(start):
            return False
        previous = start
        for step in range(1, length+1):
            point = tuple(round(start[i]+(end[i]-start[i])*step/length) for i in (0, 1))
            if point != previous and not self.edge(previous, point):
                return False
            previous = point
        return True


class MapRepository:
    CACHE_FOLDER = Path(__file__).resolve().parents[1]/'data'/'mapas'

    def __init__(self, game_dir, cache_folder=None, *, independent=False):
        self.root = Path(game_dir)
        self.independent = independent
        self.grfs = None if independent else GrfSet(str(self.root))
        self.cache_folder = Path(cache_folder or self.CACHE_FOLDER)
        self.server_maps = read_map_caches(self.cache_folder)
        self.bundled_maps = read_bundled_maps(BUNDLED_MAPS)
        self.cache = {}
        self.errors = {}
        self.sources = {}
        self.aliases = None
        self.alias_error = None

    def resource(self, key):
        path = PureWindowsPath(key)
        if path.is_absolute() or path.drive or '..' in path.parts or not path.parts or path.parts[0].lower() != 'data':
            raise ValueError('Caminho de recurso inválido')
        loose = self.root.joinpath(*path.parts)
        return loose.read_bytes() if loose.is_file() else self.grfs.read(str(path).lower())

    def collision_resource(self, key):
        try:
            return CollisionMap.from_gat(self.resource(key)), key
        except (GrfError, ValueError, OSError, zlib.error):
            bundled = self.bundled_collision(PureWindowsPath(key).stem)
            if bundled is not None:
                return bundled, 'colisão distribuída com o bot'
            for entry in getattr(self.grfs, 'alternates', {}).get(key, ()):
                try:
                    collision = CollisionMap.from_gat(self.grfs.read_entry(entry))
                except (GrfError, ValueError, OSError, zlib.error):
                    continue
                return collision, f'{key} ({Path(entry.path).name})'
            recovered = self.cache_folder/'recuperados'/PureWindowsPath(key).name
            expected = getattr(self.grfs, 'entries', {}).get(key)
            if expected is not None and recovered.is_file():
                data = recovered.read_bytes()
                if len(data) == expected.size:
                    return CollisionMap.from_gat(data), str(recovered)
            raise

    def bundled_collision(self, name):
        bundled = self.bundled_maps.get(name)
        if bundled is None:
            return None
        width, height, packed = bundled
        return CollisionMap.from_cell_types(width, height, zlib.decompress(packed))

    def resolve_alias(self, key):
        if self.aliases is None:
            self.aliases = {}
            try:
                table_key = 'data\\resnametable.txt'
                try:
                    raw = self.resource(table_key)
                except GrfError as original:
                    for entry in getattr(self.grfs, 'alternates', {}).get(table_key, ()):
                        try:
                            raw = self.grfs.read_entry(entry)
                            break
                        except GrfError:
                            continue
                    else:
                        raise original
                text = raw.decode('cp949', 'replace')
                for line in text.splitlines():
                    fields = line.split('//', 1)[0].strip().split('#')
                    if len(fields) >= 2 and fields[0] and fields[1]:
                        source, target = [v.strip().replace('/', '\\').lower() for v in fields[:2]]
                        if not source.startswith('data\\'):
                            source = 'data\\'+source
                        if not target.startswith('data\\'):
                            target = 'data\\'+target
                        self.aliases[source] = target
            except (GrfError, KeyError, ValueError, OSError) as exc:
                self.alias_error = str(exc)
        target = self.aliases.get(key)
        if target is None:
            detail = f'; tabela de nomes indisponível: {self.alias_error}' if self.alias_error else '; sem associação na tabela de nomes'
            raise ValueError(f'Mapa não encontrado: {key}{detail}')
        return target

    def get(self, name):
        name = (name or '').lower()
        if name in self.cache:
            return self.cache[name]
        try:
            p = PureWindowsPath(name)
            if not name or p.name != name or p.suffix not in ('.gat', '.rsw'):
                raise ValueError('Nome do mapa ausente ou inválido')
            key = p.with_suffix('.gat').name
            cached = self.server_maps.get(p.stem)
            if cached is not None:
                # The server's own walkability is authoritative and never encrypted.
                width, height, packed = cached
                result = CollisionMap.from_cell_types(width, height, zlib.decompress(packed))
                self.sources[name] = 'map cache do servidor'
            else:
                if getattr(self, 'independent', False):
                    result = self.bundled_collision(p.stem)
                    if result is None:
                        raise ValueError('Mapa sem colisao na base do bot; atualize os recursos do bot: '+name)
                    self.sources[name] = 'base independente do bot (GRFs visuais ignoradas)'
                    result.name = PureWindowsPath(name).name.lower()
                    self.cache[name] = result
                    return result
                resource = 'data\\'+key
                try:
                    try:
                        result, source = self.collision_resource(resource)
                    except KeyError:
                        resource = self.resolve_alias(resource)
                        result, source = self.collision_resource(resource)
                except (GrfError, KeyError, ValueError, OSError, zlib.error):
                    result = self.bundled_collision(p.stem)
                    if result is None:
                        raise
                    source = 'colisão distribuída com o bot'
                self.sources[name] = source
        except (GrfError, KeyError, ValueError, OSError, zlib.error) as exc:
            self.errors[name] = str(exc)+('' if self.server_maps else
                f'; copie o map_cache.dat (rAthena) ou os .mcache (Hercules) do servidor para {self.CACHE_FOLDER}')
            result = None
        if result is not None:
            result.name = PureWindowsPath(name).name.lower()  # e.g. 'gl_sew02.gat'
        self.cache[name] = result
        return result


def server_line(start, end):
    """Cells of the server's direct walk from start to end: diagonal first, then straight."""
    x, y = start
    sx, sy = (end[0] > x)-(end[0] < x), (end[1] > y)-(end[1] < y)
    cells = []
    while (x, y) != tuple(end):
        x, y = x+sx, y+sy
        cells.append((x, y))
        if x == end[0]:
            sx = 0
        if y == end[1]:
            sy = 0
    return cells
