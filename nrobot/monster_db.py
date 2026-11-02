"""Monstros do jogo: catálogo do cliente, base compartilhada e o que o jogo mostrou (REDE-79/81).

- Catálogo: arquivos do cliente (nomes, sprites e mapas do Navi).
- Base compartilhada (data/monstros_base, vai para todos pelo atualizador): monstros custom do
  servidor com o sprite tirado dos dados do jogo (ou da tela) e o que o servidor informou.
  Só muda quando o desenvolvedor clica em "Publicar atualização".
- Local (data/monstros, só deste PC): o que este jogador viu; o painel junta tudo.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT/'data'/'monstros'
CAPTURED = FOLDER/'capturados.json'
SPRITES = FOLDER/'sprites'
BASE = ROOT/'data'/'monstros_base'
BASE_INFO = BASE/'monstros.json'
BASE_SPRITES = BASE/'sprites'


def is_monster_species(identity):
    # Job classes use 0-999 and 4001-4999; monsters 1001-3999 and 20000+.
    return 1001 <= identity <= 3999 or identity >= 20000


@lru_cache(maxsize=1)
def identities():
    """species_id -> client symbol (without JT_) for every monster the client knows."""
    try:
        data = json.loads((ROOT/'data/rede/identidades_cliente.json').read_text(encoding='utf-8'))['identidades']
    except (OSError, ValueError, KeyError):
        return {}
    return {identity: symbol[3:] for symbol, identity in data.items()
            if symbol.startswith('JT_') and is_monster_species(identity)}


@lru_cache(maxsize=1)
def catalog():
    """species_id -> {'species_id', 'symbol', 'name', 'sprite', 'maps'} from the client files."""
    data = ROOT/'data'
    try:
        client = json.loads((data/'catalogo/catalogo.json').read_text(encoding='utf-8'))
    except (OSError, ValueError, KeyError):
        return {}
    by_symbol = {symbol: identity for identity, symbol in identities().items()}
    maps = {}
    for map_name, symbols in client.get('por_mapa', {}).items():
        for symbol in symbols:
            maps.setdefault(symbol, []).append(map_name)
    result = {}
    for symbol, entry in client.get('monstros', {}).items():
        identity = by_symbol.get(symbol)
        if identity is None:
            continue
        result[identity] = {'species_id': identity, 'symbol': symbol, 'name': entry.get('nome') or symbol.title(),
                            'sprite': entry.get('sprite') or symbol, 'maps': sorted(maps.get(symbol, []))}
    return result


def map_key(name):
    return (name or '').lower().removesuffix('.gat').removesuffix('.rsw')


def _load(path):
    try:
        return {int(k): v for k, v in json.loads(Path(path).read_text(encoding='utf-8')).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def _save(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps({str(k): v for k, v in sorted(data.items())}, ensure_ascii=False, indent=1),
                    encoding='utf-8')
    temp.replace(path)


def load_captured(path=None):
    return _load(path or CAPTURED)


def save_captured(captured, path=None):
    _save(captured, path or CAPTURED)


def load_base():
    return _load(BASE_INFO)


def record(captured, species_id, map_name, *, name=None, max_hp=None, walk_speed_ms=None, new_entity=False,
           now=None):
    """Remember what the game showed about a monster; True when something new was learned."""
    entry = captured.setdefault(species_id, {'species_id': species_id, 'maps': {}, 'first_seen': None})
    entry.setdefault('maps', {})
    stamp = (now or datetime.now()).isoformat(timespec='seconds')

    def facts():
        return entry.get('name'), entry.get('max_hp'), entry.get('walk_speed_ms'), tuple(sorted(entry['maps']))
    before = facts()
    entry['first_seen'] = entry.get('first_seen') or stamp
    if name:
        entry['name'] = name
    if max_hp:
        entry['max_hp'] = max(max_hp, entry.get('max_hp') or 0)
    if walk_speed_ms:
        entry['walk_speed_ms'] = walk_speed_ms
    key = map_key(map_name)
    if key:
        entry['maps'][key] = entry['maps'].get(key, 0)+int(new_entity)  # sightings on that map
    entry['last_seen'] = stamp
    return facts() != before


# -- sprites ------------------------------------------------------------------------------
def sprite_path(species_id):
    """Where this PC writes a sprite."""
    return SPRITES/f'{species_id}.png'


def sprite_index():
    """species_id -> PNG path, local first, then the shared base (one directory scan each)."""
    found = {}
    for folder in (BASE_SPRITES, SPRITES):  # local overrides the base
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    stem, _, suffix = entry.name.partition('.')
                    if suffix == 'png' and stem.isdigit():
                        found[int(stem)] = Path(entry.path)
        except OSError:
            continue
    return found


def find_sprite(species_id):
    for path in (sprite_path(species_id), BASE_SPRITES/f'{species_id}.png'):
        if path.is_file():
            return path
    return None


def sprite_name(species_id):
    entry = catalog().get(species_id)
    if entry is not None:
        return entry['sprite']
    return identities().get(species_id)


def sprite_from_grf(grfs, species_id):
    """RGBA of the monster's standing frame from the client files, or None (missing/encrypted)."""
    from .sprite_reader import MONSTER_DIR, crop, decode_first_frame
    name = sprite_name(species_id)
    if name is None or grfs is None:
        return None
    try:
        image = decode_first_frame(grfs.read(MONSTER_DIR+name.lower()+'.spr'))
    except Exception:  # missing, encrypted or malformed resource
        return None
    return crop(image) if image is not None else None


def ensure_sprite(grfs, species_id):
    """'exists' / 'grf' (written from the client files) / None (the game must be captured)."""
    if find_sprite(species_id) is not None:
        return 'exists'
    image = sprite_from_grf(grfs, species_id)
    if image is None:
        return None
    from .screen_capture import write_png
    path = sprite_path(species_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_png(path, image)
    return 'grf'


# -- merged view ---------------------------------------------------------------------------
def all_monsters(captured=None):
    """Every monster known, catalog + shared base + this PC, sorted by name."""
    captured = load_captured() if captured is None else captured
    rows = {}
    for identity, entry in catalog().items():
        rows[identity] = {**entry, 'origin': 'jogo', 'max_hp': None, 'walk_speed_ms': None, 'seen_maps': [],
                          'sprite_source': 'arquivos do jogo'}
    for source, data in (('base compartilhada', load_base()), ('visto neste PC', captured)):
        for identity, entry in data.items():
            row = rows.setdefault(identity, {'species_id': identity, 'symbol': entry.get('symbol') or identities().get(identity),
                                             'name': None, 'sprite': None, 'maps': [], 'origin': source,
                                             'max_hp': None, 'walk_speed_ms': None, 'seen_maps': [],
                                             'sprite_source': entry.get('sprite_source', 'dados do jogo')})
            row['name'] = entry.get('name') or row['name']
            row['max_hp'] = entry.get('max_hp') or row['max_hp']
            row['walk_speed_ms'] = entry.get('walk_speed_ms') or row['walk_speed_ms']
            row['seen_maps'] = sorted(set(row['seen_maps']) | set(entry.get('maps', {})))
            if entry.get('captured_sprite'):
                row['sprite_source'] = 'tela do jogo'
    sprites = sprite_index()
    for row in rows.values():
        row['name'] = row['name'] or (row['symbol'] or f"Monstro {row['species_id']}").replace('_', ' ').title()
        row['has_sprite'] = row['species_id'] in sprites
    return sorted(rows.values(), key=lambda row: (row['name'].lower(), row['species_id']))


def monsters_of_map(map_name, captured=None, seen=()):
    """species ids that live on a map: Navi list of the client, plus the ones seen there."""
    key = map_key(map_name)
    if not key:
        return []
    captured = load_captured() if captured is None else captured
    ids = {identity for identity, entry in catalog().items() if key in entry['maps']}
    for data in (load_base(), captured):
        ids |= {identity for identity, entry in data.items() if key in entry.get('maps', {})}
    ids |= set(seen)
    return sorted(ids)


def name_of(species_id, captured=None):
    captured = load_captured() if captured is None else captured
    for data in (captured, load_base()):
        if data.get(species_id, {}).get('name'):
            return data[species_id]['name']
    entry = catalog().get(species_id)
    if entry:
        return entry['name']
    symbol = identities().get(species_id)
    return symbol.replace('_', ' ').title() if symbol else f'Monstro {species_id}'


# -- extraction (own process) and publishing -------------------------------------------------
def extract_all(grfs, log=print):
    """Write every monster sprite the client files have; custom ones are noted for the base."""
    captured = load_captured()
    known = sprite_index()
    ids = sorted(set(catalog()) | set(identities()))
    written = custom = 0
    for index, identity in enumerate(ids, 1):
        if identity not in known:
            image = sprite_from_grf(grfs, identity)
            if image is not None:
                from .screen_capture import write_png
                path = sprite_path(identity)
                path.parent.mkdir(parents=True, exist_ok=True)
                write_png(path, image)
                known[identity] = path
                written += 1
        if identity not in catalog() and identity in known and identity not in captured:
            # A custom monster of this server: its sprite came from the game data.
            captured[identity] = {'species_id': identity, 'symbol': identities().get(identity), 'maps': {},
                                  'first_seen': None, 'sprite_source': 'dados do jogo'}
            custom += 1
        if index % 100 == 0:
            log(f'progresso {index}/{len(ids)}')
    save_captured(captured)
    log(f'concluido {written} {custom}')
    return written, custom


def export_base(log=print):
    """Developer publishing: custom monsters learned on this PC go to the shared base."""
    base, captured, sprites = load_base(), load_captured(), sprite_index()
    added = updated = images = 0
    for identity, entry in captured.items():
        if identity in catalog() and not entry.get('captured_sprite'):
            continue  # everyone extracts these from their own client files
        merged = {**base.get(identity, {}), **{k: v for k, v in entry.items() if v not in (None, {}, [])}}
        merged['maps'] = {**base.get(identity, {}).get('maps', {}), **entry.get('maps', {})}
        merged.pop('first_seen', None)
        merged.pop('last_seen', None)
        if identity not in base:
            added += 1
        elif merged != base[identity]:
            updated += 1
        base[identity] = merged
        local = sprite_path(identity)
        target = BASE_SPRITES/f'{identity}.png'
        if local.is_file() and identity in sprites and (not target.is_file() or entry.get('captured_sprite')):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(local, target)
            images += 1
    if added or updated or images:
        _save(base, BASE_INFO)
    log(f'Base de monstros: {added} novos, {updated} atualizados, {images} sprites.')
    return added, updated, images


def main():
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    from .game_folder import find
    from .grf import GrfError, GrfSet
    folder = find()
    try:
        grfs = GrfSet(str(folder)) if folder else None
    except (GrfError, OSError):
        grfs = None
    if grfs is None:
        print('ERRO: pasta do jogo não encontrada')
        return 1
    extract_all(grfs)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
