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
import sqlite3
from pathlib import Path
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SHARED = 'data/compartilhado'
MARKER = 'data/rede/compartilhado_importado.json'
# shared name -> the user's file
FILES = {'database.json':'data/database/observacoes.sqlite3',
         'rotas_quests.json': 'data/rede/rotas_quests.json',
         'quadros_missoes.json': 'data/rede/quadros_missoes.json',
         'rotas_mapas.json': 'data/rede/rotas_mapas.json',
         'portais.json': 'data/mapas/portais.json',
         'portais_internos.json': 'data/mapas/portais_internos.json',
         'portais_ampliados.json': 'data/mapas/portais_ampliados.json',
         'portais_destinos.json': 'data/mapas/portais_destinos.json',
         'npcs.json': 'data/mapas/npcs.json',
         'npc_transportes.json': 'data/mapas/npc_transportes.json',
         'quest_extras.json': 'data/rede/quest_extras.json',
         'gm_sinais.json': 'data/jogadores/gm_sinais.json',
         'showmobs_monstros.json': 'data/rede/showmobs_monstros.json',
         'caca_patrulha.json': 'data/rede/caca_patrulha.json'}
PERSONAL_LIBRARY = ('checked_missions',)
# @voltar learned once by the developer works for everybody (the speaker's name is swapped when
# sent); the Switch (mount and items of each character) and the learned mount stay personal.
SHARED_EXTRAS = ('voltar_frame', 'voltar_enabled')  # what the routes need; the numbers are each PC's own
# Never published: skill setups (buffs aprendidos), the Monstros tab targets and every other
# hunt/combat/PvP setting. Each PC keeps its own, per character (data/rede/personagens).
# Except how the hunt walks: the developer's patrol (caca_patrulha.json, from the panel settings)
# and the monsters marked "usar @showmobs" go to everybody, so the patrol works the same on every
# PC (common hunt, quests, database hunt). See hunt_share.


def _read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return copy.deepcopy(default)


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    # LF on every PC: GitHub delivers these files with LF whatever this PC's git does.
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    temporary.replace(path)


def content_hash(data):
    """Hash of a shared file whatever its line endings. The manifest was hashed with this PC's
    CRLF while users get LF from GitHub: every import was refused as "alterado" and the queue
    of quests stayed empty on the other PCs."""
    return hashlib.sha256(bytes(data).replace(b'\r\n', b'\n')).hexdigest()


def matches(data, expected):
    """The manifests already published hold the hash of the CRLF bytes: those still match."""
    data = bytes(data)
    lf = data.replace(b'\r\n', b'\n')
    return expected in (hashlib.sha256(lf).hexdigest(), hashlib.sha256(data).hexdigest(),
                        hashlib.sha256(lf.replace(b'\n', b'\r\n')).hexdigest())


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
    payload = {}
    for name, own in FILES.items():
        path = root/own
        if name=='database.json':
            from .database_share import snapshot
            data=snapshot(root)
            if data is not None:payload[name]=data
            continue
        if name == 'caca_patrulha.json':
            from .hunt_share import snapshot as patrol_snapshot
            data = patrol_snapshot(root)
            if data is not None:
                payload[name] = data
            continue
        data = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None
        if data is None:
            continue
        if name == 'quadros_missoes.json':
            data = {k: v for k, v in data.items() if k not in PERSONAL_LIBRARY}
        if name == 'quest_extras.json':
            data = {k: v for k, v in data.items() if k in SHARED_EXTRAS}
        payload[name] = data
    validate_references(payload)
    for name in FILES:
        if name in payload:
            _write(root/SHARED/name, payload[name])
        else:
            (root/SHARED/name).unlink(missing_ok=True)
    manifest = {name: content_hash((root/SHARED/name).read_bytes()) for name in payload}
    _write(root/SHARED/'manifesto.json', {'schema': 1, 'files': manifest})
    _write(root/MARKER, {'digest': digest(root)})  # the developer already has all of it
    (root/SHARED/'alvos_monstros.json').unlink(missing_ok=True)  # published before: personal now
    if 'database.json' in payload:
        log('Database preparado: '+', '.join(str(len(rows))+' '+table for table,rows in payload['database.json']['tables'].items()))
    log(f'Quests, quadros, rotas de mapa, portais, @voltar, sinais de GM e patrulha da caca preparados para os usuarios ({len(payload)} arquivos).')


def validate_references(payload):
    """A quest cannot depend on a mission or map route present only on the author's PC."""
    if payload.get('database.json') is not None:
        from .database_share import validate
        validate(payload['database.json'])
    library = payload.get('quadros_missoes.json') or {}
    missions = {m['id'] for m in library.get('missions', [])}
    routes = {r['id'] for r in payload.get('rotas_mapas.json') or []}
    validated_library = None
    for quest in payload.get('rotas_quests.json') or []:
        missing = set(quest.get('mission_ids', []))-missions
        if missing:
            raise ValueError(f"Quest {quest.get('name')}: missoes nao incluidas: {', '.join(sorted(missing))}")
        route = quest.get('map_route_id')
        if route and route not in routes:
            raise ValueError(f"Quest {quest.get('name')}: rota de mapa nao incluida: {route}")
        if quest.get('enabled', True) and quest.get('mission_ids'):
            from . import quest_library
            if validated_library is None:
                validated_library = quest_library.validate(library)
            for identity in quest['mission_ids']:
                mission = quest_library.ready_mission(validated_library, identity)
                if not any(p['board_id'] == mission['board_id'] for p in validated_library['access_paths']):
                    raise ValueError(f"Quest {quest.get('name')}: percurso ate o quadro {mission['board_id']} nao incluido")


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


def merge_portals(mine, theirs, *, smallest=False, largest=False):
    result = copy.deepcopy(mine or {})
    for map_name, cells in (theirs or {}).items():
        known = result.setdefault(map_name, {})
        for cell, value in cells.items():
            if cell not in known:
                known[cell] = copy.deepcopy(value)
            elif smallest and isinstance(value, int) and isinstance(known[cell], int):
                known[cell] = min(known[cell], value)
            elif largest and isinstance(value, int) and isinstance(known[cell], int):
                known[cell] = max(known[cell], value)
    return result


def merge_destinations(mine, theirs):
    result = copy.deepcopy(mine) if isinstance(mine, dict) else {}
    for map_name, cells in (theirs or {}).items():
        known = result.setdefault(map_name, {})
        for cell, value in (cells or {}).items():
            if cell not in known or (value.get('confirmed') and not known[cell].get('confirmed')):
                known[cell] = copy.deepcopy(value)
    return result


def merge_npcs(mine, theirs):
    """NPC cells of every map; a name learned on another PC fills a nameless one here."""
    result = copy.deepcopy(mine) if isinstance(mine, dict) else {}
    for map_name, cells in (theirs or {}).items():
        known = result.setdefault(map_name, {})
        for cell, value in (cells or {}).items():
            if cell not in known:
                known[cell] = copy.deepcopy(value)
            elif value.get('name') and not known[cell].get('name'):
                known[cell]['name'] = value['name']
    return result


def merge_extras(mine, theirs):
    """@voltar: the published one only where this PC has not learned its own; the numbers only
    for a PC that never set them."""
    result = copy.deepcopy(mine) if isinstance(mine, dict) else {}
    fresh = not result
    if theirs.get('voltar_frame') and not result.get('voltar_frame'):
        result['voltar_frame'] = theirs['voltar_frame']
        result['voltar_enabled'] = theirs.get('voltar_enabled', True)
        result['voltar_name'] = ''  # the sender's name is put in when sending
    if fresh:
        for key in ('calm_seconds', 'clear_radius', 'cast_timeout', 'attempts'):
            if key in theirs:
                result[key] = theirs[key]
    return result


def merge_lists(mine, theirs):
    """{name: [values]} (GM signs): union, the user's order first."""
    result = copy.deepcopy(mine) if isinstance(mine, dict) else {}
    for key, values in (theirs or {}).items():
        known = result.setdefault(key, [])
        if isinstance(known, list) and isinstance(values, list):
            known.extend(copy.deepcopy(v) for v in values if v not in known)
    return result


def backup(root, log):
    root = Path(root)
    present = [own for name,own in FILES.items() if name!='database.json' and (root/own).is_file()]
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
    try:
        manifest = _read(folder/'manifesto.json', None)
        if manifest is not None:
            for name, expected in manifest['files'].items():
                if name not in FILES or not (folder/name).is_file() or not matches((folder/name).read_bytes(), expected):
                    raise ValueError(f'Arquivo compartilhado ausente ou alterado: {name}')
            validate_references(shared)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        log(f'Dados compartilhados nao aplicados: {exc}')
        return False
    own = {name: None if name=='database.json' else _read(root/path,None) for name,path in FILES.items()}
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
    if shared.get('portais_ampliados.json') is not None:
        # Areas proved by accidental warps: the larger one wins.
        result['portais_ampliados.json'] = merge_portals(own['portais_ampliados.json'], shared['portais_ampliados.json'], largest=True)
    if shared.get('portais_destinos.json') is not None:
        # Where each portal leads: a crossing seen here stays; inferred ways back give way to seen ones.
        result['portais_destinos.json'] = merge_destinations(own.get('portais_destinos.json'), shared['portais_destinos.json'])
    if shared.get('npc_transportes.json') is not None:
        # NPCs that change the map: what this PC learned stays, the others' are added.
        result['npc_transportes.json'] = merge_portals(own.get('npc_transportes.json'), shared['npc_transportes.json'])
        from .npc_transports import purge
        purge(result['npc_transportes.json'])  # a transport found false on any PC goes everywhere
    if shared.get('npcs.json') is not None:
        result['npcs.json'] = merge_npcs(own.get('npcs.json'), shared['npcs.json'])
    if shared['quest_extras.json'] is not None:
        result['quest_extras.json'] = merge_extras(own['quest_extras.json'], shared['quest_extras.json'])
    if shared['gm_sinais.json'] is not None:
        result['gm_sinais.json'] = merge_lists(own['gm_sinais.json'], shared['gm_sinais.json'])
    if isinstance(shared.get('showmobs_monstros.json'), list):
        # Monsters searched with @showmobs: the published ones plus the ones marked on this PC.
        mine = own.get('showmobs_monstros.json') if isinstance(own.get('showmobs_monstros.json'), list) else []
        result['showmobs_monstros.json'] = sorted({int(s) for s in mine+shared['showmobs_monstros.json'] if type(s) is int})
    if isinstance(shared.get('caca_patrulha.json'), dict):
        result['caca_patrulha.json'] = copy.deepcopy(shared['caca_patrulha.json'])  # the same patrol for everybody
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
    if shared.get('database.json') is not None:
        from .database_share import merge as merge_database
        try:merge_database(shared['database.json'],root,log)
        except (OSError,ValueError,sqlite3.Error) as exc:
            log('Database nao aplicado; importacao sera tentada novamente: '+str(exc));return False
    saved = backup(root, log)
    if saved:
        log(f'Copia dos seus dados antes de receber os compartilhados: {saved.relative_to(root).as_posix()}')
    for name, data in result.items():
        _write(root/FILES[name], data)
    _write(root/MARKER, {'digest': current, 'imported_at': datetime.now().isoformat(timespec='seconds')})
    log('Quests, quadros, rotas de mapa, portais, @voltar, sinais de GM e patrulha da caca publicados foram recebidos.')
    return True
