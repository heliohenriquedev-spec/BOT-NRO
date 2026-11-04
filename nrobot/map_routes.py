"""Recorded paths to hunting maps, shared by every quest route ("Mapas de caca").

A path is recorded once in the game (portals, NPC transports) and chosen by name in
"Editar rota". Paths also connect maps for the way back.
"""
import copy
import json
import uuid
from pathlib import Path

FILE = Path(__file__).resolve().parents[1]/'data/rede/rotas_mapas.json'


def validate(entries):
    from .quest_library import validate_steps
    if not isinstance(entries, list) or len(entries) > 200:
        raise ValueError('Limite de 200 rotas de mapa')
    result, seen = copy.deepcopy(entries), set()
    for entry in result:
        if not isinstance(entry, dict):
            raise ValueError('Rota de mapa invalida')
        entry.setdefault('id', uuid.uuid4().hex)
        if not isinstance(entry['id'], str) or entry['id'] in seen:
            raise ValueError('Rota de mapa duplicada')
        seen.add(entry['id'])
        entry['steps'] = validate_steps(entry.get('steps', []))
        if not entry['steps']:
            raise ValueError('Rota de mapa vazia')
        if not isinstance(entry.get('target_map'), str) or not entry['target_map']:
            raise ValueError('Informe o mapa de destino')
        entry['start_map'] = entry['steps'][0]['map']
        inner = entry.get('inner_portals', {})
        if not isinstance(inner, dict):
            raise ValueError('Portais internos invalidos')
        entry['inner_portals'] = {m: {cell: [int(target[0]), int(target[1])] for cell, target in links.items()}
                                  for m, links in inner.items() if isinstance(links, dict) and links}
        if not entry['inner_portals']:
            entry.pop('inner_portals')
        if not isinstance(entry.get('name'), str) or not entry['name'].strip():
            entry['name'] = entry['start_map']+' → '+entry['target_map']
    return result


def load(path=None):
    path = Path(path or FILE)
    return validate(json.loads(path.read_text(encoding='utf-8'))) if path.exists() else []


def save(entries, path=None):
    entries = validate(entries)
    path = Path(path or FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)
    return entries


def apply(routes, entries=None):
    """Quest routes pick up the current recording of their chosen hunting map path."""
    entries = {e['id']: e for e in (load() if entries is None else entries)}
    for route in routes:
        chosen = entries.get(route.get('map_route_id') or '')
        if chosen:
            route['steps'] = copy.deepcopy(chosen['steps'])
            route['target_map'] = chosen['target_map']
            route['needs_recording'] = False
    return routes


def inner_portals(steps, portals):
    """Inner portals (warps to another part of the same map) of every map of the route, kept with it:
    some maps (sewers) are walled off and their way out is reached only through them."""
    from .portals import PortalGuard
    maps = {PortalGuard.key(s['map']) for s in steps if s.get('map')}
    return {m: dict(portals.internal[m]) for m in sorted(maps) if portals.internal.get(m)}


def adopt_inner_portals(entries, portals):
    """Inner portals saved with the routes, for a PC that has not walked through them yet."""
    for entry in entries:
        for m, links in entry.get('inner_portals', {}).items():
            known = portals.internal.setdefault(m, {})
            for cell, target in links.items():
                if cell not in known:
                    known[cell] = list(target)
                    portals.dirty = True
                    portals.version += 1
    return entries


def compact(steps):
    """Only what the trip needs: NPCs, dialog choices, the way out of each map and the end.

    Recorded walking clicks are dropped; the bot finds the shortest walk to each kept point.
    A walk is kept only when the map is left by walking (the next step waits for the map) or
    when it is the destination."""
    kept = []
    for index, step in enumerate(steps):
        if step['kind'] == 'walk':
            following = steps[index+1] if index+1 < len(steps) else None
            if following is not None and following['kind'] not in ('wait_map', 'wait_transfer'):
                continue
        kept.append(copy.deepcopy(step))
    return kept
