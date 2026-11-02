"""REDE-69: replica of the map server walk path and step timing.

rAthena (path.cpp) and Hercules (path.c) share the same A* walk search: MOVE_COST 10,
MOVE_DIAGONAL_COST 14, Manhattan heuristic, a fixed neighbour order, diagonals only when
both orthogonal cells are free, a binary heap compared by f-cost only (their BHEAP macros
are a port of Python's heapq, so heapq's private sift helpers reproduce tie-breaking), a
32x32 node table whose index collisions abort the search, and at most 32 steps.

Timing: each step lasts the walk speed, diagonal steps speed*14/10 (integer). Emulators
differ on whether the cell changes halfway through a step or at its end, so both are
returned as candidate cells.
"""
import heapq

MOVE_COST, MOVE_DIAGONAL_COST, MAX_WALKPATH = 10, 14, 32
CELL_PHASES = (.5, 1.0)


class OpenGround:
    """Stand-in map without obstacles: the server's path on free ground (diagonal first)."""
    width = height = 1024

    @staticmethod
    def walkable(point):
        return 0 <= point[0] < 1023 and 0 <= point[1] < 1023


class _Node:
    __slots__ = ('x', 'y', 'g', 'f', 'parent', 'closed')

    def __init__(self, x, y, g, f, parent):
        self.x, self.y, self.g, self.f, self.parent, self.closed = x, y, g, f, parent, False

    def __lt__(self, other):
        return self.f < other.f


def server_path(collision, start, goal):
    """Cells from start to goal as the server walks them, or None when it would refuse."""
    x0, y0 = start
    x1, y1 = goal
    if not collision.walkable((x1, y1)):
        return None
    if (x0, y0) == (x1, y1):
        return [(x0, y0)]
    xs, ys = collision.width-1, collision.height-1
    free = lambda x, y: collision.walkable((x, y))
    heuristic = lambda x, y: MOVE_COST*(abs(x1-x)+abs(y1-y))
    index = lambda x, y: (x+y*MAX_WALKPATH) & (MAX_WALKPATH*MAX_WALKPATH-1)
    nodes, heap = {}, []
    first = _Node(x0, y0, 0, heuristic(x0, y0), None)
    nodes[index(x0, y0)] = first
    heapq.heappush(heap, first)

    def add(x, y, g, parent):
        i = index(x, y)
        node = nodes.get(i)
        if node is not None and node.x == x and node.y == y:
            if g < node.g:
                node.g, node.parent, node.f = g, parent, g+heuristic(x, y)
                if node.closed:
                    heapq.heappush(heap, node)
                else:
                    position = next((k for k, item in enumerate(heap) if item is node), None)
                    if position is None:
                        return True
                    heapq._siftdown(heap, 0, position)
                    heapq._siftup(heap, position)
                node.closed = False
            return False
        if node is not None and (node.x or node.y):
            return True  # index already taken: the server aborts the search
        node = _Node(x, y, g, g+heuristic(x, y), parent)
        nodes[i] = node
        heapq.heappush(heap, node)
        return False

    while True:
        if not heap:
            return None
        current = heapq.heappop(heap)
        current.closed = True
        x, y, g = current.x, current.y, current.g
        if (x, y) == (x1, y1):
            break
        north = y < ys and free(x, y+1)
        south = y > 0 and free(x, y-1)
        east = x < xs and free(x+1, y)
        west = x > 0 and free(x-1, y)
        error = False
        for allowed, dx, dy, cost in ((south and east, 1, -1, MOVE_DIAGONAL_COST), (east, 1, 0, MOVE_COST),
                                      (north and east, 1, 1, MOVE_DIAGONAL_COST), (north, 0, 1, MOVE_COST),
                                      (north and west, -1, 1, MOVE_DIAGONAL_COST), (west, -1, 0, MOVE_COST),
                                      (south and west, -1, -1, MOVE_DIAGONAL_COST), (south, 0, -1, MOVE_COST)):
            if allowed and (not (dx and dy) or free(x+dx, y+dy)):
                error = add(x+dx, y+dy, g+cost, current) or error
        if error:
            return None
    path = []
    node = current
    while node is not None:
        path.append((node.x, node.y))
        node = node.parent
    path.reverse()
    return path if len(path)-1 <= MAX_WALKPATH else None


def step_durations(path, speed_ms):
    return [(speed_ms*MOVE_DIAGONAL_COST//MOVE_COST if a[0] != b[0] and a[1] != b[1] else speed_ms)/1000
            for a, b in zip(path, path[1:])]


def cells_at(path, durations, elapsed):
    """Candidate cells after `elapsed` seconds of walking (both cell-change conventions)."""
    cells = []
    for phase in CELL_PHASES:
        cell, clock = path[0], 0.0
        for step, duration in enumerate(durations):
            if elapsed < clock+duration*phase:
                break
            cell = path[step+1]
            clock += duration
        if cell not in cells:
            cells.append(cell)
    return cells
