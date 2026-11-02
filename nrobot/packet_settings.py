"""REDE-37: validated persistent settings for the packet relay."""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT/'data/rede/painel_config.json'
SPECIES = {1212: 'Akino', 1051: 'Bikouchuu', 1783: 'Filhote de Katsuyu',
           1037: 'Filhote de Cobra', 1034: 'Girino', 1214: 'Onbba', 1836: 'Boneco de Treino'}
DEFAULTS = {'species': [1037], 'radius': 28, 'patrol': True, 'patrol_step': 8, 'skills': True,
            'skill_interval': .5, 'skill_timeout': 1.5, 'skill_attempts': 3, 'target_defer': 8,
            'switch_distance': 6, 'switch_saving': 3, 'switch_ratio_percent': 65}
DEFAULTS.update(auto_map_targets=True, skill_global_delay=.12, require_collision=True, skill_profiles=[], auto_attacks=True, advanced_combat=True)
# REDE-68: user-defined skill order; 'throws' is the alternating Shuriken/Kunai pair.
DEFAULTS.update(skill_priority=[])
# REDE-70: which presences hold the bot.
DEFAULTS.update(pause_on_players=True, pause_on_disguised=True, pause_on_hidden=True)
THROWS_TOKEN = 'throws'


def learned_buff_links(path=None):
    path = Path(path) if path is not None else CONFIG.with_name('buffs_aprendidos.json')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return {int(key): value for key, value in data.items()
                if str(key).isdigit() and type(value) is int and 1 <= value <= 65535}
    except (OSError, ValueError, AttributeError):
        return {}


def validate(data):
    if not isinstance(data, dict):
        raise ValueError('Configuração deve ser um objeto')
    result = {**DEFAULTS, **data}
    ids = result['species']
    from .map_monsters import monster_assets
    from .presence_guard import monster_sprite
    # Monsters discovered by server HP may be missing from the client catalog (REDE-63).
    if (not isinstance(ids, list) or (not ids and not result['auto_map_targets'])
        or any(type(i) is not int or (i not in SPECIES and i not in monster_assets() and not monster_sprite(i)) for i in ids)):
        raise ValueError('Selecione ao menos um monstro conhecido')
    for key, minimum, maximum in (('radius', 8, 60), ('patrol_step', 1, 8), ('skill_attempts', 1, 5),
                                  ('target_defer', 2, 30), ('switch_distance', 4, 28),
                                  ('switch_saving', 1, 10), ('switch_ratio_percent', 25, 90)):
        if type(result[key]) is not int or not minimum <= result[key] <= maximum:
            raise ValueError(f'{key}: valor deve estar entre {minimum} e {maximum}')
    for key, minimum, maximum in (('skill_interval', .25, 3), ('skill_timeout', .75, 8), ('skill_global_delay', .1, 10)):
        if type(result[key]) not in (int, float) or not math.isfinite(result[key]) or not minimum <= result[key] <= maximum:
            raise ValueError(f'{key}: valor deve estar entre {minimum} e {maximum}')
    if result['skill_timeout'] < result['skill_interval']:
        raise ValueError('Espera por resposta deve ser maior ou igual ao intervalo da habilidade')
    for key in ('patrol', 'skills', 'require_collision', 'auto_attacks', 'advanced_combat', 'auto_map_targets',
                'pause_on_players', 'pause_on_disguised', 'pause_on_hidden'):
        if type(result[key]) is not bool:
            raise ValueError(f'{key}: valor deve ser booleano')
    profiles = result['skill_profiles']
    if not isinstance(profiles, list) or len(profiles) > 300:
        raise ValueError('Lista de habilidades inválida')
    normalized, seen = [], set()
    links = learned_buff_links()
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError('Perfil de habilidade inválido')
        p = {'enabled': False, 'role': 'offensive', 'level': 1, 'interval': .5, 'effect_id': 0, **profile}
        if type(p.get('skill_id')) is not int or not 1 <= p['skill_id'] <= 65535 or p['skill_id'] in seen:
            raise ValueError('ID de habilidade inválido ou duplicado')
        if p['role'] not in ('offensive', 'buff') or type(p['enabled']) is not bool:
            raise ValueError('Tipo/habilitação de habilidade inválido')
        if type(p['level']) is not int or not 1 <= p['level'] <= 100:
            raise ValueError('Nível de habilidade inválido')
        if type(p['interval']) not in (int, float) or not math.isfinite(p['interval']) or not .1 <= p['interval'] <= 300:
            raise ValueError('Intervalo da habilidade deve estar entre 0,1 e 300 segundos')
        if type(p['effect_id']) is not int or not 0 <= p['effect_id'] <= 65535:
            raise ValueError('Efeito de buff inválido')
        if p['role'] == 'buff' and not p['effect_id'] and p['skill_id'] in links:
            p['effect_id'] = links[p['skill_id']]
        normalized.append({k: p[k] for k in ('skill_id', 'enabled', 'role', 'level', 'interval', 'effect_id')})
        seen.add(p['skill_id'])
    result['skill_profiles'] = normalized
    priority = result['skill_priority']
    if (not isinstance(priority, list) or len(priority) > 64 or len(set(map(str, priority))) != len(priority)
            or any(token != THROWS_TOKEN and (type(token) is not int or not 1 <= token <= 65535) for token in priority)):
        raise ValueError('Prioridade de habilidades inválida')
    return {key: sorted(set(ids)) if key == 'species' else result[key] for key in DEFAULTS}


def read(path=CONFIG):
    path = Path(path)
    return validate(json.loads(path.read_text(encoding='utf-8'))) if path.is_file() else validate({})


def save(data, path=CONFIG):
    data = validate(data)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)
    links_path = path.with_name('buffs_aprendidos.json')
    links = learned_buff_links(links_path)
    links.update({p['skill_id']: p['effect_id'] for p in data['skill_profiles']
                  if p['role'] == 'buff' and p['effect_id']})
    if links:
        links_temp = links_path.with_suffix('.tmp')
        links_temp.write_text(json.dumps(links, indent=2), encoding='utf-8')
        links_temp.replace(links_path)
    return data
