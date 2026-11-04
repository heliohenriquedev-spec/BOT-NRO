"""REDE-54: discover NRO monster types from local assets and server HP metadata."""
from functools import lru_cache
import json
from pathlib import Path

from .network_targets import is_player_id


@lru_cache(maxsize=1)
def monster_assets():
    root = Path(__file__).resolve().parents[1]/'data'
    try:
        identities = json.loads((root/'rede/identidades_cliente.json').read_text(encoding='utf-8'))['identidades']
        monsters = json.loads((root/'catalogo/catalogo.json').read_text(encoding='utf-8'))['monstros']
        return {identity: monsters[symbol[3:]]['nome'] for symbol, identity in identities.items()
                if symbol.startswith('JT_') and symbol[3:] in monsters}
    except (OSError, ValueError, KeyError):
        return {}


def is_confirmed_monster(entity, player_id=None):
    from .monster_db import is_known_player

    identity = entity['entity_id']
    # The client can receive a disguise as the negated account ID in an unsigned field.
    if identity == player_id or is_player_id(identity) or is_player_id((-identity) & 0xffffffff):
        return False
    if entity.get('object_type_raw') not in (None, 0, 5) or entity.get('owner_id') or entity.get('summoned'):
        return False
    name = entity.get('name')
    if not name or is_known_player(name):
        return False
    # The server writes "HP: x/y" in the name reply of monsters; when that reply comes without it
    # (seen on other PCs), a named unit with a monster sprite is still a monster, otherwise
    # nothing was ever confirmed there and the bot only patrolled.
    from .monster_db import is_monster_species
    return entity.get('max_hp', 0) > 0 or is_monster_species(entity.get('species_id') or 0)


def confirmed_types(inventory, player_id=None, *, by_name=False):
    result = {}
    assets = monster_assets()
    for entity in inventory.entities.values():
        identity = entity['species_id']
        # REDE-63: HP text in the name reply is sent by the server only for monsters, so
        # custom monsters (e.g. training dummies) missing from the client catalog still count.
        if not is_confirmed_monster(entity, player_id):
            continue
        evidence = ('aparencia do catalogo de monstros e HP recebido do servidor' if identity in assets
                    else 'HP de monstro recebido do servidor (fora do catalogo do cliente)')
        key = (identity, entity['name']) if by_name else identity
        entry = result.setdefault(key, {'species_id': identity, 'name': entity['name'], 'present': 0,
                                              'evidence': evidence})
        entry['present'] += int(entity['present_last_observation'] and entity.get('hp', 1) > 0)
    return result
