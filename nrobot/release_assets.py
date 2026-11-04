"""Build only the assets required by installed clients before publishing."""
from __future__ import annotations

import base64
import csv
import json
from pathlib import Path
import shutil
import zlib

from . import monster_db
from .map_navigation import MapRepository

ROOT = Path(__file__).resolve().parents[1]
GAME = Path(r'C:\NRO - Jogo COMPLETO')


def prepare(log=print, *, refresh_combat=False):
    from . import game_folder
    from .ammo import names_from_grfs, names_from_catalog
    destination = ROOT/'data'/'recursos'
    if not refresh_combat and (destination/'municao.json').is_file() and (destination/'colisoes.json').is_file():
        names_from_catalog()
        from .map_navigation import read_bundled_maps, CollisionMap
        maps = read_bundled_maps(destination/'colisoes.json')
        if not maps:
            raise ValueError('Base de colisao vazia; restaure os recursos do bot')
        for width, height, cells in maps.values():
            CollisionMap.from_cell_types(width, height, zlib.decompress(cells))
        log(f'Base de combate preservada: {len(maps)} mapas; GRFs visuais nao alteram os recursos publicados.')
        prepare_icons(log)
        return
    game = game_folder.saved() or GAME
    repo = MapRepository(str(game))
    destination = ROOT/'data'/'recursos'
    destination.mkdir(parents=True, exist_ok=True)
    ammo = names_from_grfs(repo.grfs, bundled=False)
    from .drop_db import prepare_item_names
    prepare_item_names(repo.grfs)
    if not ammo:
        raise ValueError('Catalogo de municao indisponivel; confira DATA.INI e as GRFs antes de publicar')
    (destination/'municao.json').write_text(json.dumps(ammo, ensure_ascii=False, indent=1)+'\n', encoding='utf-8')
    log(f'Catalogo portatil: {len(ammo)} municoes. Pasta do jogo: {game}')
    # Export the collision from the priority GRF set, independent of user caches.
    repo.server_maps.clear()
    repo.bundled_maps.clear()
    try:
        repo.resolve_alias('data\\pvp_n_1-1.gat')
    except ValueError:
        pass
    keys = {key for key in repo.grfs.entries if key.endswith('.gat') and key.count('\\') == 1}
    aliases = {key for key in (repo.aliases or {}) if key.endswith('.gat') and key.count('\\') == 1}
    maps, missing = {}, []
    # Store the server's cell types compactly, preserving the exact walkable grid.
    cell_types = bytes([1, 0]) + bytes(254)
    for key in sorted(keys | aliases):
        name = key.split('\\')[-1]
        collision = repo.get(name)
        repo.cache.clear()
        if collision is None:
            if key in keys:
                missing.append(name)
            continue
        packed = zlib.compress(collision.cells.translate(cell_types), 9)
        maps[name.removesuffix('.gat')] = [
            collision.width, collision.height, base64.b64encode(packed).decode('ascii')]
    if missing:
        raise ValueError('GATs ausentes no pacote: '+', '.join(missing))
    (destination/'colisoes.json').write_text(
        json.dumps(maps, ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf-8')
    log(f'Colisoes portateis: {len(maps)} mapas, incluindo aliases.')
    prepare_icons(log)


def prepare_icons(log=print):
    """Visual updates can change icons, never operational map cells or item IDs."""
    index = ROOT/'Arquivos_grf'/'prioridade.tsv'
    if not index.is_file():
        return
    sprites = monster_db.priority_sprites()
    if not sprites:
        raise ValueError('Índice de sprites prioritários vazio')
    destination = ROOT/'data'/'recursos'
    icons = destination/'sprites_por_nome'
    icons.mkdir(parents=True, exist_ok=True)
    for name, path in sprites.items():
        shutil.copyfile(path, icons/f'{name}.png')
    for path in icons.glob('*.png'):
        if path.stem not in sprites:
            path.unlink()
    with index.open(encoding='utf-8', newline='') as source_table, (destination/'prioridade.tsv').open(
            'w', encoding='utf-8', newline='') as target_table:
        fields = ('tipo', 'nome', 'prioridade', 'grf', 'estado')
        writer = csv.DictWriter(target_table, fieldnames=fields, delimiter='\t', extrasaction='ignore')
        writer.writeheader()
        for row in csv.DictReader(source_table, delimiter='\t'):
            if row['tipo'] == '.spr' and row['nome'] in sprites:
                writer.writerow(row)
    log(f'Recursos visuais de atualizacao: {len(sprites)} icones.')


def validate_quest_maps(root=ROOT):
    """Check paths against distributed grids, never the developer's private map cache."""
    from .shared_data import SHARED
    required = set()
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ('map', 'target_map') and isinstance(child, str) and child.strip():
                    required.add(child.strip().lower().removesuffix('.gat').removesuffix('.rsw'))
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    root = Path(root)
    for name in ('rotas_quests.json', 'rotas_mapas.json', 'quadros_missoes.json'):
        path = root/SHARED/name
        if path.is_file():
            visit(json.loads(path.read_text(encoding='utf-8')))
    from .map_navigation import read_bundled_maps, CollisionMap
    available = read_bundled_maps(root/'data/recursos/colisoes.json')
    missing = sorted(required-set(available))
    if missing:
        raise ValueError('Mapas das quests sem colisao no pacote: '+', '.join(missing))
    for name in required:
        width, height, packed = available[name]
        CollisionMap(width, height, zlib.decompress(packed))
    return len(required)
