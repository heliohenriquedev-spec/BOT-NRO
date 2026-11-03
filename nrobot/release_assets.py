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


def prepare(log=print):
    source = ROOT/'Arquivos_grf'
    index = source/'prioridade.tsv'
    if not index.is_file():
        return
    repo = MapRepository(str(GAME))
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
    (destination/'colisoes.json').write_text(
        json.dumps(maps, ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf-8')
    log(f'Recursos de atualização: {len(sprites)} ícones e {len(maps)} mapas, incluindo aliases.')
