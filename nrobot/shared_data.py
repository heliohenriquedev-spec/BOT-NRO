"""Quests, boards, missions, hunting map routes and portals published for every user.

Publishing copies the developer's files to data/compartilhado (it goes with the version).
On each user's PC the shared data is merged into theirs once per new published copy:
- what the developer published (same id, or the same mission/map path) is replaced by the
  published version, so fixes reach everybody;
- what the user created is kept, and the user's own choices stay (queue order, enabled,
  missions done today, slots, progress, @voltar, Switch, login are never shared).
Before merging, the user's files are copied to backups/.
"""
from __future__ import annotations

import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SHARED = 'data/compartilhado'
MARKER = 'data/rede/compartilhado_importado.json'
# shared name -> the user's file
FILES = {'rotas_quests.json': 'data/rede/rotas_quests.json',
         'quadros_missoes.json': 'data/rede/quadros_missoes.json',
         'rotas_mapas.json': 'data/rede/rotas_mapas.json',
         'portais.json': 'data/mapas/portais.json',
         'portais_internos.json': 'data/mapas/portais_internos.json'}
PERSONAL_LIBRARY = ('checked_missions',)


def _read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return copy.deepcopy(default)


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    temporary.replace(path)


def digest(root=ROOT):
    folder = Path(root)/SHARED
    h = hashlib.sha256()
    for name in sorted(FILES):
        source = folder/name
        if source.is_file():
            h.update(name.encode()+b'\0'+source.read_bytes())
    return h.hexdigest()[:16]


def export(log=print, root=ROOT):
    """Developer publishing: the current quests, routes and portals go with the version."""
    root = Path(root)
    count = 0
    for name, own in FILES.items():
        data = _read(root/own, None)
        if data is None:
            continue
        if name == 'quadros_missoes.json':
            data = {k: v for k, v in data.items() if k not in PERSONAL_LIBRARY}
        _write(root/SHARED/name, data)
        count += 1
    _write(root/MARKER, {'digest': digest(root)})  # the developer already has all of it
    log(f'Quests, quadros, rotas de mapa e portais preparados para os usuarios ({count} arquivos).')


# -- merging on the user's PC ----------------------------------------------------------------
def _by_id(mine, theirs, same=None):
    """Lists of dicts with 'id': published entries replace the user's copy (same id or same()),
    new ones are appended, the user's own stay. Returns (merged, {old id: published id})."""
    result, renamed = [copy.deepcopy(e) for e in mine], {}
    for entry in theirs:
        index = next((i for i, e in enumerate(result) if e.get('id') == entry.get('id')), None)
        if index is None and same:
            index = next((i for i, e in enumerate(result) if same(e, entry)), None)
            if index is not None and result[index].get('id'):
                renamed[result[index]['id']] = entry.get('id')
        if index is None:
            result.append(copy.deepcopy(entry))
        else:
            result[index] = copy.deepcopy(entry)
    return result, renamed


def _key(name):
    return (name or '').lower().removesuffix('.gat').removesuffix('.rsw')


def merge_library(mine, theirs):
    mine = mine or {}
    result = copy.deepcopy(mine)
    renamed = {}
    result['boards'], _ = _by_id(mine.get('boards', []), theirs.get('boards', []))
    result['access_paths'], _ = _by_id(mine.get('access_paths', []), theirs.get('access_paths', []),
                                       lambda a, b: a.get('board_id') == b.get('board_id') and a.get('name') == b.get('name'))
    result['missions'], renamed = _by_id(
        mine.get('missions', []), theirs.get('missions', []),
        lambda a, b: a.get('board_id') == b.get('board_id') and (a.get('menu_option') or a.get('name')) == (b.get('menu_option') or b.get('name')))
    menus = copy.deepcopy(mine.get('menus', {}))
    for board_id, published in theirs.get('menus', {}).items():
        known = menus.setdefault(board_id, [])
        for menu in published:
            if menu not in known:
                known.append(copy.deepcopy(menu))
    result['menus'] = menus
    for field in ('option_details', 'return_paths', 'board_templates'):
        merged = copy.deepcopy(mine.get(field, {}))
        for board_id, value in theirs.get(field, {}).items():
            if isinstance(value, dict) and isinstance(merged.get(board_id), dict) and field == 'option_details':
                merged[board_id].update(copy.deepcopy(value))
            else:
                merged[board_id] = copy.deepcopy(value)
        result[field] = merged
    for field, value in theirs.items():
        if field not in result and field not in PERSONAL_LIBRARY:
            result[field] = copy.deepcopy(value)
    return result, renamed


def merge_map_routes(mine, theirs):
    return _by_id(mine or [], theirs, lambda a, b: _key(a.get('target_map')) == _key(b.get('target_map'))
                  and _key((a.get('steps') or [{}])[0].get('map')) == _key((b.get('steps') or [{}])[0].get('map')))


def merge_quests(mine, theirs, missions_renamed, maps_renamed):
    mine = copy.deepcopy(mine or [])
    for route in mine:  # the user's quests follow the published missions and map paths
        route['mission_ids'] = [missions_renamed.get(i, i) for i in route.get('mission_ids', [])]
        if route.get('map_route_id') in maps_renamed:
            route['map_route_id'] = maps_renamed[route['map_route_id']]
    result = mine
    for entry in theirs:
        index = next((i for i, e in enumerate(result) if e.get('id') == entry.get('id')
                      or (e.get('name') or '').strip().casefold() == (entry.get('name') or '').strip().casefold()), None)
        if index is None:
            result.append(copy.deepcopy(entry))
        else:
            enabled = result[index].get('enabled', True)
            result[index] = dict(copy.deepcopy(entry), enabled=enabled)  # the user's queue choice stays
    return result


def merge_portals(mine, theirs, *, smallest=False):
    result = copy.deepcopy(mine or {})
    for map_name, cells in (theirs or {}).items():
        known = result.setdefault(map_name, {})
        for cell, value in cells.items():
            if cell not in known:
                known[cell] = copy.deepcopy(value)
            elif smallest and isinstance(value, int) and isinstance(known[cell], int):
                known[cell] = min(known[cell], value)
    return result


def backup(root, log):
    root = Path(root)
    present = [own for own in FILES.values() if (root/own).is_file()]
    if not present:
        return None
    target = root/'backups'/f"antes-dos-dados-compartilhados-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for own in present:
            bundle.write(root/own, own)
    return target


def merge(root=ROOT, log=print, force=False):
    """Bring the published quests, routes and portals into this PC's files, once per publication."""
    root = Path(root)
    folder = root/SHARED
    if not any((folder/name).is_file() for name in FILES):
        return False
    current = digest(root)
    if not force and _read(root/MARKER, {}).get('digest') == current:
        return False
    shared = {name: _read(folder/name, None) for name in FILES}
    own = {name: _read(root/path, None) for name, path in FILES.items()}
    result, missions_renamed, maps_renamed = {}, {}, {}
    if shared['quadros_missoes.json'] is not None:
        result['quadros_missoes.json'], missions_renamed = merge_library(own['quadros_missoes.json'], shared['quadros_missoes.json'])
    if shared['rotas_mapas.json'] is not None:
        result['rotas_mapas.json'], maps_renamed = merge_map_routes(own['rotas_mapas.json'], shared['rotas_mapas.json'])
    if shared['rotas_quests.json'] is not None:
        result['rotas_quests.json'] = merge_quests(own['rotas_quests.json'], shared['rotas_quests.json'], missions_renamed, maps_renamed)
    if shared['portais.json'] is not None:
        result['portais.json'] = merge_portals(own['portais.json'], shared['portais.json'], smallest=True)
    if shared['portais_internos.json'] is not None:
        result['portais_internos.json'] = merge_portals(own['portais_internos.json'], shared['portais_internos.json'])
    try:  # everything checked before anything is written: a bad publication changes nothing
        from . import map_routes, quest_library, quest_routes
        if 'quadros_missoes.json' in result:
            result['quadros_missoes.json'] = quest_library.validate(result['quadros_missoes.json'])
        if 'rotas_mapas.json' in result:
            result['rotas_mapas.json'] = map_routes.validate(result['rotas_mapas.json'])
        if 'rotas_quests.json' in result:
            result['rotas_quests.json'] = quest_routes.validate_routes(result['rotas_quests.json'])
    except (ValueError, KeyError, TypeError) as exc:
        log(f'Dados compartilhados nao aplicados (invalidos): {exc}')
        return False
    saved = backup(root, log)
    if saved:
        log(f'Copia dos seus dados antes de receber os compartilhados: {saved.relative_to(root).as_posix()}')
    for name, data in result.items():
        _write(root/FILES[name], data)
    _write(root/MARKER, {'digest': current, 'imported_at': datetime.now().isoformat(timespec='seconds')})
    log('Quests, quadros, rotas de mapa e portais publicados foram recebidos.')
    return True
