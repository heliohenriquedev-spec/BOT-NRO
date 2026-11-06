"""Declarative map behavior profiles: data only, never executable scripts."""
import copy
import json
import os
from pathlib import Path
import re
import tempfile

FILE = Path(__file__).resolve().parents[1]/'data/rede/comportamentos_mapas.json'
FIELDS = frozenset(('auto_attacks', 'melee_approach', 'kite', 'skills', 'ignore_attackers',
    'switch_distance', 'switch_saving', 'switch_ratio_percent'))

def map_key(value):
    if not isinstance(value, str):
        raise ValueError('Mapa deve ser texto')
    value = value.strip().lower().removesuffix('.gat')
    if not re.fullmatch(r'[a-z0-9_-]{1,64}', value):
        raise ValueError('Nome interno do mapa invalido')
    return value

def validate(data):
    from .packet_settings import validate as settings_validate
    if not isinstance(data, dict) or set(data)-{'schema', 'name', 'map', 'description', 'enabled', 'settings', 'combat'}:
        raise ValueError('Perfil invalido ou campos desconhecidos')
    if type(data.get('schema')) is not int or data['schema'] not in (1, 2):
        raise ValueError('Versao de perfil nao suportada (use schema 1 ou 2)')
    name = data.get('name')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValueError('Informe um nome de ate 100 caracteres')
    description = data.get('description', '')
    if not isinstance(description, str) or len(description) > 4000:
        raise ValueError('Descricao invalida')
    settings = data.get('settings')
    if not isinstance(settings, dict) or not settings or set(settings)-FIELDS:
        raise ValueError('Regras vazias ou nao suportadas: '+', '.join(sorted(set(settings or {})-FIELDS)))
    if type(data.get('enabled', True)) is not bool:
        raise ValueError('enabled deve ser true ou false')
    for key, value in settings.items():
        if key in ('patrol', 'patrol_avoid_walls', 'auto_movement', 'auto_attacks', 'melee_approach', 'kite', 'skills') and type(value) is not bool:
            raise ValueError(key+': use true ou false')
    settings = dict(settings)
    if settings.get('kite') is True:
        if settings.get('melee_approach') is True:
            raise ValueError('Kite e aproximacao melee sao exclusivos')
        settings['melee_approach'] = False
    elif settings.get('melee_approach') is True:
        settings['kite'] = False
    checked = settings_validate(settings)
    result = dict(schema=data['schema'], name=name.strip(), map=map_key(data.get('map')), description=description,
                enabled=data.get('enabled', True), settings={k: checked[k] for k in settings})
    if 'combat' in data:
        if data['schema'] != 2:
            raise ValueError('Regras combat exigem schema 2')
        from .map_combat import validate as combat_validate
        result['combat'] = combat_validate(data['combat'])
    return result

def load(path=None):
    path = Path(path or FILE)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, list):
        raise ValueError('Biblioteca de perfis invalida')
    profiles = [validate(p) for p in data]
    if len({p['map'] for p in profiles}) != len(profiles):
        raise ValueError('Existe mais de um perfil para o mesmo mapa')
    return profiles

def save(profiles, path=None):
    path = Path(path or FILE)
    profiles = [validate(p) for p in profiles]
    if len({p['map'] for p in profiles}) != len(profiles):
        raise ValueError('Existe mais de um perfil para o mesmo mapa')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(profiles, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def effective(base, profiles, map_name, quest_active=False):
    result = copy.deepcopy(base)
    if not map_name or quest_active:
        return result, None
    key = map_key(map_name)
    profile = next((p for p in profiles if p['map']==key and p['enabled']), None)
    if profile:
        result.update(copy.deepcopy(profile['settings']))
    return result, profile
