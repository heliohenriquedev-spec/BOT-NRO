"""Monstros do jogo: catálogo do cliente + o que o próprio jogo mostrou (REDE-79).

O catálogo vem dos arquivos do cliente (nomes, sprites e mapas do Navi). Cada monstro que
aparece no jogo é registrado com o que o servidor informa (nome, HP, velocidade, mapas). Quem
não tem sprite legível nos GRFs ganha uma captura de tela do próprio jogo, feita quando o
mouse passa sobre ele. Tudo o que é capturado fica em data/monstros (só deste PC).
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT/'data'/'monstros'
CAPTURED = FOLDER/'capturados.json'
SPRITES = FOLDER/'sprites'


@lru_cache(maxsize=1)
def catalog():
    """species_id -> {'species_id', 'symbol', 'name', 'sprite', 'maps'} from the client files."""
    data = ROOT/'data'
    try:
        identities = json.loads((data/'rede/identidades_cliente.json').read_text(encoding='utf-8'))['identidades']
        client = json.loads((data/'catalogo/catalogo.json').read_text(encoding='utf-8'))
    except (OSError, ValueError, KeyError):
        return {}
    maps = {}
    for map_name, symbols in client.get('por_mapa', {}).items():
        for symbol in symbols:
            maps.setdefault(symbol, []).append(map_name)
    result = {}
    for symbol, entry in client.get('monstros', {}).items():
        identity = identities.get('JT_'+symbol)
        if identity is None:
            continue
        result[identity] = {'species_id': identity, 'symbol': symbol, 'name': entry.get('nome') or symbol.title(),
                            'sprite': entry.get('sprite') or symbol, 'maps': sorted(maps.get(symbol, []))}
    return result


def map_key(name):
    return (name or '').lower().removesuffix('.gat').removesuffix('.rsw')


def load_captured(path=None):
    try:
        return {int(k): v for k, v in json.loads(Path(path or CAPTURED).read_text(encoding='utf-8')).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def save_captured(captured, path=None):
    path = Path(path or CAPTURED)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps({str(k): v for k, v in sorted(captured.items())}, ensure_ascii=False, indent=1),
                    encoding='utf-8')
    temp.replace(path)


def record(captured, species_id, map_name, *, name=None, max_hp=None, walk_speed_ms=None, new_entity=False,
           now=None):
    """Remember what the game showed about a monster; True when something new was learned."""
    entry = captured.setdefault(species_id, {'species_id': species_id, 'maps': {}, 'first_seen': None})
    stamp = (now or datetime.now()).isoformat(timespec='seconds')

    def facts():
        return entry.get('name'), entry.get('max_hp'), entry.get('walk_speed_ms'), tuple(sorted(entry['maps']))
    before = facts()
    entry['first_seen'] = entry['first_seen'] or stamp
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


def sprite_path(species_id):
    return SPRITES/f'{species_id}.png'


def all_monsters(captured=None):
    """Every monster known, catalog and game merged; sorted by name."""
    captured = load_captured() if captured is None else captured
    rows = {}
    for identity, entry in catalog().items():
        rows[identity] = {**entry, 'origin': 'jogo', 'max_hp': None, 'walk_speed_ms': None, 'seen_maps': []}
    for identity, entry in captured.items():
        row = rows.setdefault(identity, {'species_id': identity, 'symbol': None, 'name': f'Monstro {identity}',
                                         'sprite': None, 'maps': [], 'origin': 'capturado no jogo'})
        if entry.get('name'):
            row['name'] = entry['name']
        row['max_hp'] = entry.get('max_hp')
        row['walk_speed_ms'] = entry.get('walk_speed_ms')
        row['seen_maps'] = sorted(entry.get('maps', {}))
        row['last_seen'] = entry.get('last_seen')
        row['captured_sprite'] = entry.get('captured_sprite', False)
    for row in rows.values():
        row['has_sprite'] = sprite_path(row['species_id']).is_file()
    return sorted(rows.values(), key=lambda row: (row['name'].lower(), row['species_id']))


def monsters_of_map(map_name, captured=None, seen=()):
    """species ids that live on a map: Navi list of the client, plus the ones seen there."""
    key = map_key(map_name)
    if not key:
        return []
    captured = load_captured() if captured is None else captured
    ids = {identity for identity, entry in catalog().items() if key in entry['maps']}
    ids |= {identity for identity, entry in captured.items() if key in entry.get('maps', {})}
    ids |= set(seen)
    return sorted(ids)


def name_of(species_id, captured=None):
    captured = load_captured() if captured is None else captured
    if captured.get(species_id, {}).get('name'):
        return captured[species_id]['name']
    entry = catalog().get(species_id)
    return entry['name'] if entry else f'Monstro {species_id}'


def sprite_from_grf(grfs, species_id):
    """RGBA of the monster's standing frame from the client files, or None (missing/encrypted)."""
    from .sprite_reader import MONSTER_DIR, crop, decode_first_frame
    entry = catalog().get(species_id)
    if entry is None or grfs is None:
        return None
    try:
        image = decode_first_frame(grfs.read(MONSTER_DIR+entry['sprite'].lower()+'.spr'))
    except Exception:  # missing, encrypted or malformed resource
        return None
    return crop(image) if image is not None else None


def ensure_sprite(grfs, species_id):
    """'exists' / 'grf' (written from the client files) / None (the game must be captured)."""
    path = sprite_path(species_id)
    if path.is_file():
        return 'exists'
    image = sprite_from_grf(grfs, species_id)
    if image is None:
        return None
    from .screen_capture import write_png
    path.parent.mkdir(parents=True, exist_ok=True)
    write_png(path, image)
    return 'grf'
