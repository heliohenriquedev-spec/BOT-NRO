"""Routes between maps that build themselves while the player plays.

Every portal crossed is remembered with the map it leads to (portals.PortalGuard, file
data/mapas/portais_destinos.json): crossing it is a confirmed link, the portal next to the arrival
spot an inferred way back. With the recorded hunting-map paths (which also carry NPC transports)
they form a graph of maps; the shortest way from the current map to any map reached before is
turned into the same steps a recorded path has: walk into the portal, wait for the next map...
and walk to the arrival cell at the end. No recording button is needed: each portal entered once
feeds it.
"""
from __future__ import annotations

import heapq
import json
from pathlib import Path

from .portals import PortalGuard

FILE = Path(__file__).resolve().parents[1]/'data'/'mapas'/'portais_destinos.json'
CONFIRMED, INFERRED = 1.0, 2.0  # a way back only deduced costs more than a crossing actually seen


def gat(map_name):
    return PortalGuard.key(map_name)+'.gat'


def load_destinations(path=None):
    try:
        return json.loads(Path(path or FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def edges(destinations, entries=()):
    """{map key: [(cost, next map key, steps, arrival cell or None)]}."""
    graph = {}
    for map_name, cells in (destinations or {}).items():
        for cell, link in (cells or {}).items():
            if not isinstance(link, dict) or not link.get('map'):
                continue
            here, there = PortalGuard.key(map_name), PortalGuard.key(link['map'])
            if here == there:
                continue
            x, y = (int(v) for v in cell.split(','))
            steps = [dict(kind='portal', map=gat(here), position=[x, y]), dict(kind='wait_map', map=gat(there))]
            cost = CONFIRMED if link.get('confirmed') else INFERRED
            graph.setdefault(here, []).append((cost, there, steps, link.get('arrival')))
    for entry in entries or ():
        steps = entry.get('steps') or []
        if not steps or not entry.get('target_map'):
            continue
        here, there = PortalGuard.key(steps[0]['map']), PortalGuard.key(entry['target_map'])
        if here == there:
            continue
        cost = max(1, sum(s['kind'] in ('wait_map', 'wait_transfer') for s in steps))
        arrival = steps[-1].get('position') if steps[-1]['kind'] == 'walk' else None
        graph.setdefault(here, []).append((float(cost), there, [dict(s) for s in steps], arrival))
    return graph


def path(from_map, to_map, destinations, entries=()):
    """Steps from from_map to to_map, or None when no way is known yet."""
    start, goal = PortalGuard.key(from_map), PortalGuard.key(to_map)
    if not start or not goal:
        return None
    if start == goal:
        return []
    graph = edges(destinations, entries)
    queue, seen, counter = [(0.0, 0, start, [], None)], set(), 1
    while queue:
        cost, _, here, steps, arrival = heapq.heappop(queue)
        if here == goal:
            if arrival and len(arrival) == 2 and not (steps and steps[-1]['kind'] == 'walk'):
                steps = steps+[dict(kind='walk', map=gat(goal), position=[int(arrival[0]), int(arrival[1])])]
            return steps
        if here in seen:
            continue
        seen.add(here)
        for step_cost, there, more, landing in graph.get(here, ()):
            if there not in seen:
                heapq.heappush(queue, (cost+step_cost, counter, there, steps+more, landing))
                counter += 1
    return None


def reachable(from_map, destinations, entries=()):
    """Every map a way is known to from from_map."""
    start = PortalGuard.key(from_map)
    graph, seen, stack = edges(destinations, entries), {start}, [start]
    while stack:
        for _, there, _, _ in graph.get(stack.pop(), ()):
            if there not in seen:
                seen.add(there)
                stack.append(there)
    return seen
