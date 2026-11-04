"""REDE-75: patrol waypoints on open ground, analysed once per map.

The reachable ground is split in SPACING x SPACING blocks. Each block gets one waypoint on
its most open cell (farthest from walls), so the patrol never aims at corners, wall edges or
dead-end nooks: those are still seen from the nearby open waypoints (monsters are announced
well beyond SEEN_RADIUS). Blocks are linked when their ground touches, which gives walkable
distances between waypoints without running a cell search for every pair.
"""
from collections import defaultdict, deque
import heapq
import math

SPACING = 12
SEEN_RADIUS = 9  # a waypoint counts as visited once the walked path passes this close
MIN_OPEN = 2  # waypoint at least this many cells from any wall
MIN_CELLS = 20  # smaller pieces of ground in a block are nooks, not patrol areas
NOOK_CELLS = 40  # a dead-end block (one neighbour) smaller than this is a corner
NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def wall_distance(collision, cells, cap=6):
    """Chebyshev distance of every reachable cell to the closest non-walkable cell."""
    distance, queue = {}, deque()
    for point in cells:
        if any((point[0]+dx, point[1]+dy) not in cells for dx, dy in NEIGHBOURS):
            distance[point] = 1
            queue.append(point)
    while queue:
        point = queue.popleft()
        value = distance[point]
        if value >= cap:
            continue
        for dx, dy in NEIGHBOURS:
            other = (point[0]+dx, point[1]+dy)
            if other in cells and other not in distance:
                distance[other] = value+1
                queue.append(other)
    return defaultdict(lambda: cap, distance)


def block_of(point, spacing=SPACING):
    return (point[0]//spacing, point[1]//spacing)


class PatrolTour:
    """Nodes are (bx, by, piece): the ground of one block split in the pieces connected
    inside it, so a block lying across a wall never makes crossing that wall look short.

    spacing: cells between waypoints (configurable); a waypoint counts as passed within
    3/4 of it, so nearby points are not walked to again. wall_margin: waypoints keep at
    least this many cells from walls; avoid_walls also drops the corridor fallback, so the
    character never has to walk up to a wall."""

    def __init__(self, collision, start, *, spacing=SPACING, wall_margin=MIN_OPEN, avoid_walls=False):
        self.collision = collision
        self.spacing = spacing
        self.link_edges = {}  # (node, node beyond an inner portal) -> portal cell to step on
        self.seen_radius = max(4, round(spacing*.75)) if spacing != SPACING else SEEN_RADIUS
        # Ground reached by walking plus what inner portals lead to (the other side of the map).
        cells, pending = set(collision.reachable(start)), list(getattr(collision, 'links', ()))
        grown = True
        while grown:
            grown = False
            for source, target in pending:
                if tuple(source) in cells and tuple(target) not in cells and collision.walkable(target):
                    cells |= collision.reachable(target); grown = True
        self.cells = frozenset(cells)
        self.wall = wall_distance(collision, self.cells, cap=max(6, wall_margin+1))
        members = defaultdict(list)
        for point in self.cells:
            members[block_of(point, spacing)].append(point)
        self.node_of, self.pieces = {}, defaultdict(list)
        for block, cells in members.items():
            inside, piece = set(cells), 0
            for seed in sorted(cells):
                if seed in self.node_of:
                    continue
                node = (*block, piece)
                piece += 1
                self.node_of[seed], queue = node, deque([seed])
                while queue:
                    point = queue.popleft()
                    for dx, dy in NEIGHBOURS:
                        other = (point[0]+dx, point[1]+dy)
                        if other in inside and other not in self.node_of and collision.edge(point, other):
                            self.node_of[other] = node
                            queue.append(other)
                self.pieces[block].append(node)
        groups = defaultdict(list)
        for point, node in self.node_of.items():
            groups[node].append(point)
        self.transit, self.points, self.sizes = {}, {}, {}
        for node, cells in groups.items():
            centre = (sum(p[0] for p in cells)/len(cells), sum(p[1] for p in cells)/len(cells))
            best = max(cells, key=lambda p: (min(self.wall[p], max(4, wall_margin)), -math.dist(p, centre), p))
            self.transit[node], self.sizes[node] = best, len(cells)
            if len(cells) >= min(MIN_CELLS, spacing*2) and self.wall[best] >= wall_margin:
                self.points[node] = best
        self.graph = defaultdict(set)
        for point in self.cells:
            node = self.node_of[point]
            for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
                other = (point[0]+dx, point[1]+dy)
                neighbour = self.node_of.get(other)
                if neighbour is not None and neighbour != node and collision.edge(point, other):
                    self.graph[node].add(neighbour)
                    self.graph[neighbour].add(node)
        for source, target in getattr(collision, 'links', ()):
            a, b = self.node_of.get(tuple(source)), self.node_of.get(tuple(target))
            if a is not None and b is not None and a != b:
                self.graph[a].add(b)  # one way: stepping on the portal lands there
                self.link_edges[(a, b)] = tuple(source)
        for node in list(self.points):
            if len(self.graph[node]) <= 1 and self.sizes[node] < NOOK_CELLS and len(self.points) > 1:
                del self.points[node]  # dead-end corner: seen from the neighbouring waypoint
        # Mazes of narrow corridors have no open ground at all: a corridor piece with no
        # waypoint around it still needs one, even if it touches the walls.
        for node in sorted(self.transit):
            if avoid_walls or node in self.points or self.sizes[node] < 8:
                continue
            around = (other for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                      for other in self.pieces.get((node[0]+dx, node[1]+dy), ()))
            best = self.transit[node]
            if not any(other in self.points and math.dist(best, self.points[other]) <= self.seen_radius+3 for other in around):
                self.points[node] = self.transit[node]

    def edge_penalty(self, node):
        """How much a waypoint lies at the border of the ground: missing neighbours (walls, map
        edge) and closeness of its cell to a wall. Open ground first, borders last."""
        point = self.points.get(node, self.transit[node])
        return max(0, 8-len(self.graph[node]))+max(0, 4-min(self.wall[point], 4))

    def done_around(self, node, remaining):
        return sum(other not in remaining for other in self.graph[node])

    def closed(self, node, remaining):
        """Neighbouring ground already done, plus missing neighbours (walls, map edge)."""
        neighbours = self.graph[node]
        return sum(other not in remaining for other in neighbours)+max(0, 8-len(neighbours))

    def block_near(self, position):
        node = self.node_of.get(tuple(position))
        if node is not None:
            return node
        return min(self.transit, key=lambda key: math.dist(position, self.transit[key]))

    def distances(self, position, parents=None):
        """Walkable distance estimate from position to every node (Dijkstra on the node graph)."""
        start = self.block_near(position)
        best = {start: math.dist(position, self.transit[start])}
        heap = [(best[start], start)]
        while heap:
            cost, node = heapq.heappop(heap)
            if cost != best[node]:
                continue
            for neighbour in self.graph[node]:
                value = cost+math.dist(self.transit[node], self.transit[neighbour])
                if value < best.get(neighbour, math.inf):
                    best[neighbour] = value
                    if parents is not None:
                        parents[neighbour] = node
                    heapq.heappush(heap, (value, neighbour))
        return best

    def portal_on_way(self, position, node):
        """The inner portal to step on first when node lies beyond one, else None."""
        if not self.link_edges:
            return None
        parents = {}
        if node not in self.distances(position, parents):
            return None
        path = [node]
        while path[-1] in parents:
            path.append(parents[path[-1]])
        path.reverse()
        for a, b in zip(path, path[1:]):
            if (a, b) in self.link_edges:
                return self.link_edges[(a, b)]
        return None

    def stepping_stone(self, position, node, hops=3):
        """A cell a few nodes along the node path to node, so cell searches stay short."""
        parents = {}
        if node not in self.distances(position, parents):
            return None
        path = [node]
        while path[-1] in parents:
            path.append(parents[path[-1]])
        path.reverse()  # starts next to position
        return self.transit[path[min(hops, len(path)-1)]]

    def seen_from(self, position):
        """Waypoints close enough to position to count as visited."""
        reach = self.seen_radius//self.spacing+1
        base = block_of(position, self.spacing)
        for bx in range(base[0]-reach, base[0]+reach+1):
            for by in range(base[1]-reach, base[1]+reach+1):
                for node in self.pieces.get((bx, by), ()):
                    point = self.points.get(node)
                    if point is not None and math.dist(position, point) <= self.seen_radius:
                        yield node

    def coverage(self, done):
        return len(done)/len(self.points) if self.points else 1.0
