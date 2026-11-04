"""Confirmed corrections and transient entities are separate from natural map spawns."""
from .npc_labels import plain


def map_key(value):
    return (value or '').lower().removesuffix('.gat').removesuffix('.rsw')


def excluded_spawn(species_id, map_name, name=None):
    key = map_key(map_name)
    # User-verified server corrections. Species are not globally banned: NRO reuses sprites.
    if key == 'hospital2' and species_id in (1031, 1188):
        return True
    if key == 'tur_dun03' and (species_id == 1315 or plain(name or '') == 'ninkame'):
        return True
    return temporary_reason(dict(species_id=species_id, name=name)) is not None


def temporary_reason(entity):
    if entity.get('owner_id') or entity.get('summoned'):
        return 'Invocacao de jogador; nao e respawn natural'
    name = plain(entity.get('name') or '')
    if name == 'tronco de madeira' or entity.get('species_id') == 1188 and not name:
        return 'Tronco de substituicao/hide observado; nao e respawn natural (dono nao identificado)'
    return None


def clean_records(records):
    """Suppress old false sightings too, including copies already present on other PCs."""
    import copy
    result = copy.deepcopy(records)
    for identity, entry in result.items():
        entry['maps'] = {m: count for m, count in entry.get('maps', {}).items()
                         if not excluded_spawn(identity, m, entry.get('name'))}
        if 'names_by_map' in entry:
            names_by_map = {m: [n for n in names if not excluded_spawn(identity, m, n)]
                            for m, names in entry['names_by_map'].items()}
            entry['names_by_map'] = {m: names for m, names in names_by_map.items() if names}
        if entry.get('owner_id') or entry.get('summoned'):
            entry['maps'] = {}; entry['names_by_map'] = {}
    return result
