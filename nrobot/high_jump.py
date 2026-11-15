"""Salto Ninja (TK_HIGHJUMP, habilidade 426) para cortar caminho por cima de paredes.

Medido no NRO (prt_fild02, 2026-11-11): o personagem sai da celula onde esta e cai 2 celulas por
nivel (nivel 5 = 10) na direcao para onde esta virado, tambem nas diagonais (10 em cada eixo),
passando por cima do que houver no meio. O servidor responde com 01FF (posicao de chegada).
A direcao vem do ultimo passo dado: para saltar para d, o personagem anda de P = A-d ate A.
A celula de chegada precisa ser chao livre; caso contrario o salto nao sai do lugar.

plan() compara andar ate o objetivo com: andar ate P, um passo ate A, saltar ate L e andar de L
ate o objetivo. O salto custa JUMP_COST celulas (descer da montaria, conjurar, montar de novo) e
so vale quando economiza pelo menos MIN_SAVING celulas de caminhada.
"""
from __future__ import annotations

import heapq
import math

SKILL_ID = 426
DIRECTIONS = ((0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1))
JUMP_COST = 30.0
MIN_SAVING = 40.0


def distances(collision, seeds, limit=float('inf')):
    """Dijkstra a partir das celulas seeds ({celula: custo inicial}) com os passos do servidor."""
    best = dict(seeds)
    heap = [(cost, cell) for cell, cost in seeds.items()]
    heapq.heapify(heap)
    while heap:
        cost, cell = heapq.heappop(heap)
        if cost != best.get(cell) or cost > limit:
            continue
        for dx, dy in DIRECTIONS:
            nxt = (cell[0]+dx, cell[1]+dy)
            if not collision.edge(cell, nxt):
                continue
            new = cost+(math.sqrt(2) if dx and dy else 1.0)
            if new < best.get(nxt, float('inf')):
                best[nxt] = new
                heapq.heappush(heap, (new, nxt))
    return best


def goal_seeds(collision, goal):
    """Onde a caminhada termina: a propria celula, ou ao lado dela (portal, NPC)."""
    goal = tuple(goal)
    if collision.walkable(goal):
        return {goal: 0.0}
    return {(goal[0]+dx, goal[1]+dy): 1.0 for dx, dy in DIRECTIONS if collision.walkable((goal[0]+dx, goal[1]+dy))}


def plan(collision, start, goal, *, reach=10, jump_cost=JUMP_COST, min_saving=MIN_SAVING, banned=frozenset()):
    """O primeiro salto do melhor caminho ate goal, que pode ter varios saltos seguidos (areas
    cercadas por paredes), ou None quando andar e melhor (ou nao ha caminho nem saltando).

    {'prep', 'takeoff', 'landing', 'direction', 'walk', 'with_jump', 'jumps'}; walk None = nao da
    para chegar andando. Depois de cada salto o caminho e calculado de novo de onde caiu."""
    start = tuple(start)
    if reach < 1 or not collision.start_ok(start):
        return None
    seeds = goal_seeds(collision, goal)
    if not seeds:
        return None
    from_start = distances(collision, {start: 0.0})
    walk = min((from_start[c]+v for c, v in seeds.items() if c in from_start), default=float('inf'))
    # Dijkstra with walking steps and jumps. A jump toward d from A needs the step P=A-d -> A to
    # turn the character: up to 2 extra steps (back to P and forward again) are counted for it.
    best = {start: 0.0}
    parent = {}
    heap = [(0.0, start)]
    found = None
    while heap:
        cost, cell = heapq.heappop(heap)
        if cost != best.get(cell):
            continue
        if cost >= walk:
            break  # walking is already as good
        if cell in seeds:
            total = cost+seeds[cell]
            if found is None or total < found[0]:
                found = (total, cell)
            break
        for dx, dy in DIRECTIONS:
            nxt = (cell[0]+dx, cell[1]+dy)
            if collision.edge(cell, nxt):
                new = cost+(math.sqrt(2) if dx and dy else 1.0)
                if new < best.get(nxt, float('inf')):
                    best[nxt], parent[nxt] = new, (cell, None)
                    heapq.heappush(heap, (new, nxt))
            prep = (cell[0]-dx, cell[1]-dy)
            landing = (cell[0]+dx*reach, cell[1]+dy*reach)
            if ((cell, (dx, dy)) in banned or not collision.walkable(landing)
                    or not collision.edge(prep, cell)):
                continue
            new = cost+jump_cost+2*(math.sqrt(2) if dx and dy else 1.0)
            if new < best.get(landing, float('inf')):
                best[landing], parent[landing] = new, (cell, (dx, dy))
                heapq.heappush(heap, (new, landing))
    if found is None or walk-found[0] < min_saving:
        return None
    total, cell = found
    jumps = []
    while cell in parent:
        previous, direction = parent[cell]
        if direction is not None:
            jumps.append((previous, direction, cell))
        cell = previous
    if not jumps:
        return None
    takeoff, (dx, dy), landing = jumps[-1]  # the first jump on the way
    return {'prep': [takeoff[0]-dx, takeoff[1]-dy], 'takeoff': list(takeoff), 'landing': list(landing),
            'direction': [dx, dy], 'walk': None if walk == float('inf') else round(walk, 1),
            'with_jump': round(total, 1), 'jumps': len(jumps)}


def plan_cells(width, height, cells, forbidden, start, goal, **options):
    """plan() on a fresh copy of the map: runs in a worker process (no relay lag from the GIL)."""
    from .map_navigation import CollisionMap
    collision = CollisionMap(width, height, cells)
    collision.set_forbidden(forbidden)
    return plan(collision, start, goal, **options)


_POOL = None


def submit(loop, collision, start, goal, **options):
    """Future of plan() in one worker process kept for the session; a thread if that fails."""
    import functools
    global _POOL
    call = functools.partial(plan_cells, collision.width, collision.height, bytes(collision.cells),
                             frozenset(collision.forbidden), tuple(start), tuple(goal), **options)
    try:
        if _POOL is None:
            from concurrent.futures import ProcessPoolExecutor
            _POOL = ProcessPoolExecutor(max_workers=1)
        return loop.run_in_executor(_POOL, call)
    except (OSError, RuntimeError):
        _POOL = None
        return loop.run_in_executor(None, call)
