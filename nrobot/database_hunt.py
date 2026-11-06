"""Hunting chosen from the monster/item database: which maps have each monster, which of them
have a recorded path ("Mapas de caca"), and the temporary quest that goes there and hunts.

The quest has no missions: it travels along the recorded path, then hunts the checked monsters
in the order of their priority (1 first) with the normal combat settings. It is never saved in
the quest queue and does not replace the queue's resume point.

Goals (whichever comes first ends the hunt): kills, minutes hunting on the map, or a number of
one item gained in the inventory since arriving. No goal: hunt until stopped.
"""
from __future__ import annotations

import re

from .portals import PortalGuard

DATABASE_HUNT = 'database_hunt'
ENDLESS = 100000  # "until stopped": the largest kill count a quest accepts


def monsters_by_map(monsters):
    """{map key: [monster rows]} from the database rows (registered and seen maps)."""
    result = {}
    for row in monsters:
        for map_name in set(row.get('maps') or []) | set(row.get('seen_maps') or []):
            key = PortalGuard.key(map_name)
            if key:
                result.setdefault(key, []).append(row)
    for rows in result.values():
        rows.sort(key=lambda r: (str(r.get('name') or ''), r['species_id']))
    return result


def routes_by_map(entries):
    """{map key: recorded path} of the hunting map paths, the newest recording winning."""
    return {PortalGuard.key(e['target_map']): e for e in entries if e.get('target_map')}


def database_hunt_route(request, entries, from_map=None, destinations=None, from_position=None):
    """The temporary quest for the relay; ValueError with a message for the user. Without a
    recorded path to the map, the way learned from the portals crossed (auto_routes) is used."""
    target = PortalGuard.key(request.get('target_map') or '')
    if not target:
        raise ValueError('Escolha o mapa de caca')
    chosen = routes_by_map(entries).get(target)
    if request.get('map_route_id'):
        chosen = next((e for e in entries if e['id'] == request['map_route_id']), chosen)
    automatic = None
    if chosen is None and from_map:
        from .auto_routes import path
        automatic = path(from_map, target, destinations or {}, entries)
        if automatic == [] and from_position:  # already on the hunting map: just hunt here
            automatic = [dict(kind='walk', map=target+'.gat', position=[int(v) for v in from_position])]
    if chosen is None and not automatic:
        raise ValueError(f'Nenhum caminho conhecido ate {target}: entre uma vez nos portais ate la '
                         '(o bot aprende sozinho) ou grave o percurso em Rotas > Mapas de caca')
    priority = {}
    for key, value in (request.get('priority') or {}).items():
        if str(key).isdigit() and type(value) is int and 1 <= value <= 99:
            priority[str(int(key))] = value
    species = sorted({int(s) for s in request.get('species') or [] if type(s) is int and 1 <= s <= 65535})
    if not species:
        raise ValueError('Marque ao menos um monstro para cacar')
    kills = request.get('kills') or 0
    if type(kills) is not int or kills < 0:
        raise ValueError('Quantidade de mortes invalida')
    minutes, item, amount = (request.get(k) or 0 for k in ('goal_minutes', 'goal_item_id', 'goal_item_amount'))
    if any(type(v) is not int or v < 0 for v in (minutes, item, amount)) or minutes > 24*60 or item > 65535:
        raise ValueError('Meta de tempo ou de item invalida')
    if bool(item) != bool(amount):
        raise ValueError('Para a meta de item, escolha o item e a quantidade')
    if chosen is None:
        chosen = dict(id='', target_map=target+'.gat')  # learned way: steps given here, nothing to apply
    showmobs = sorted({int(s) for s in request.get('showmobs') or [] if type(s) is int and int(s) in species})
    return dict(steps=automatic or [], showmobs_species=showmobs, goal_minutes=minutes, goal_item_id=item, goal_item_amount=amount,
                goal_item_name=str(request.get('goal_item_name') or '')[:60],id=DATABASE_HUNT, name='Caca: '+target, enabled=True, map_route_id=chosen['id'],
                target_map=chosen['target_map'], species=species, always_attack=species,
                attack_priority={k: v for k, v in priority.items() if int(k) in species},
                kills=min(kills, ENDLESS) if kills else ENDLESS, lifecycle_enabled=False)


def item_count(items, item_id):
    return sum(i.get('amount') or 0 for i in items if i.get('item_id') == item_id)


def goal_reached(route, items, now):
    """Text of the goal reached, or None. The clock and the item count start on the first call
    on the hunting map (so the trip there does not count) and are kept in the route."""
    route.setdefault('goal_started_at', now)
    if route.get('goal_item_id'):
        route.setdefault('goal_item_baseline', item_count(items, route['goal_item_id']))
    minutes = route.get('goal_minutes') or 0
    if minutes and now-route['goal_started_at'] >= minutes*60:
        return f'{minutes} min de caca'
    if route.get('goal_item_id'):
        gained = item_count(items, route['goal_item_id'])-route['goal_item_baseline']
        if gained >= route['goal_item_amount']:
            return f"{route['goal_item_amount']}x {route.get('goal_item_name') or 'item ' + str(route['goal_item_id'])}"
    return None


LOOT_COMMAND = re.compile(r'@alootid [+-]\d{1,6}|@alootid reset|@autoloot( \d{1,3}(\.\d{1,2})?)?')


def loot_command(text):
    """Only the loot commands the hunt window offers go to the game chat."""
    text = ' '.join(str(text or '').split())
    if not LOOT_COMMAND.fullmatch(text):
        raise ValueError('Comando de loot invalido')
    return text


SHOWMOBS_FILE = __import__('pathlib').Path(__file__).resolve().parents[1]/'data'/'rede'/'showmobs_monstros.json'


def showmobs_marked(path=None):
    """Monsters marked "usar @showmobs" (window of the monster's loot / hunt window)."""
    import json
    try:
        return {int(s) for s in json.loads((path or SHOWMOBS_FILE).read_text(encoding='utf-8'))}
    except (OSError, ValueError, TypeError):
        return set()


def mark_showmobs(species_id, enabled, path=None):
    import json
    marked = showmobs_marked(path)
    (marked.add if enabled else marked.discard)(int(species_id))
    target = path or SHOWMOBS_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sorted(marked)), encoding='utf-8')
    return marked
