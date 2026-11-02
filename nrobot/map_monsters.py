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


def confirmed_types(inventory, player_id=None):
    result = {}
    assets = monster_assets()
    for entity in inventory.entities.values():
        identity = entity['species_id']
        # REDE-63: HP text in the name reply is sent by the server only for monsters, so
        # custom monsters (e.g. training dummies) missing from the client catalog still count.
        if (entity['entity_id'] == player_id or is_player_id(entity['entity_id'])
            or not entity.get('name') or not entity.get('max_hp', 0) > 0):
            continue
        evidence = ('aparencia do catalogo de monstros e HP recebido do servidor' if identity in assets
                    else 'HP de monstro recebido do servidor (fora do catalogo do cliente)')
        entry = result.setdefault(identity, {'species_id': identity, 'name': entity['name'], 'present': 0,
                                              'evidence': evidence})
        entry['present'] += int(entity['present_last_observation'] and entity.get('hp', 1) > 0)
    return result
