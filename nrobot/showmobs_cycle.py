"""Ciclo de @showmobs: uma lista de mapas visitados em ordem, sem parar.

Cada etapa: viaja do ponto salvo ate o mapa (caminho gravado, portais aprendidos e NPCs de
transporte como o Viajante Ninja), pede @showmobs <id> do monstro, vai ate a marca e mata 1,
da @voltar e so entao segue para a etapa seguinte. Depois da ultima, recomeca pela primeira.

Monstro ainda nao renasceu (o @showmobs nao marca nada): o personagem fica no mapa e pergunta de
novo a cada MobScan.CYCLE_INTERVAL segundos, ate ele aparecer. O tempo de renascimento fica no servidor e nao
chega ao cliente; o horario de cada morte e guardado para mostrar ha quanto tempo foi.

Configuracao em data/rede/ciclo_showmobs.json (editavel na aba "Ciclo @showmobs").
Uma etapa pode trazer "portal": {"map": "areia", "position": [153, 21]} para sair por um
portal conhecido em vez do caminho calculado (a saida da Vila Areia para o moc_fild01 leva
a lugares diferentes conforme de onde se veio, entao o calculo automatico nao a usa).
"""
from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

from .portals import PortalGuard

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT/'data'/'rede'/'ciclo_showmobs.json'
STATE_FILE = ROOT/'data'/'rede'/'ciclo_showmobs_mortes.json'

DEFAULT = {
    'save_map': 'hospital2',
    # Salto Ninja por cima das paredes na viagem: so quando economiza "economia_minima" celulas;
    # "custo" e quanto vale (em celulas) descer da montaria, saltar e montar de novo.
    'salto_ninja': {'ativo': True, 'economia_minima': 40, 'custo': 30},
    'stages': [
        {'name': 'Mamute Nevoa', 'map': 'gef_fild04', 'species': 1083},
        {'name': 'Mamute Konoha', 'map': 'prt_fild02', 'species': 1079},
        {'name': 'Mamute Nuvem', 'map': 'yuno_fild08', 'species': 1081},
        {'name': 'Vila Areia -> moc_fild01', 'map': 'moc_fild01', 'species': 1078,
         'portal': {'map': 'areia', 'position': [153, 21]}},
    ],
}


def validate(data):
    if not isinstance(data, dict):
        raise ValueError('Configuracao do ciclo invalida')
    save = PortalGuard.key(str(data.get('save_map') or ''))
    if not save:
        raise ValueError('Informe o mapa do ponto salvo (save_map)')
    stages = data.get('stages')
    if not isinstance(stages, list) or not 1 <= len(stages) <= 30:
        raise ValueError('O ciclo precisa de 1 a 30 etapas')
    result = []
    for i, s in enumerate(stages, 1):
        if not isinstance(s, dict):
            raise ValueError(f'Etapa {i} invalida')
        target = PortalGuard.key(str(s.get('map') or ''))
        species = s.get('species')
        if not target:
            raise ValueError(f'Etapa {i}: informe o mapa')
        if type(species) is not int or not 1 <= species <= 65535:
            raise ValueError(f'Etapa {i}: informe o numero do monstro do @showmobs')
        stage = {'name': str(s.get('name') or target)[:60], 'map': target, 'species': species}
        portal = s.get('portal')
        if portal is not None:
            pos = (portal or {}).get('position') if isinstance(portal, dict) else None
            if (not isinstance(portal, dict) or not PortalGuard.key(str(portal.get('map') or ''))
                    or not isinstance(pos, list) or len(pos) != 2 or any(type(v) is not int for v in pos)):
                raise ValueError(f'Etapa {i}: portal invalido (use {{"map": "areia", "position": [x, y]}})')
            stage['portal'] = {'map': PortalGuard.key(portal['map']), 'position': list(pos)}
        result.append(stage)
    jump = data.get('salto_ninja', DEFAULT['salto_ninja'])
    if not isinstance(jump, dict) or type(jump.get('ativo', True)) is not bool:
        raise ValueError('salto_ninja invalido (use {"ativo": true, "economia_minima": 40, "custo": 30})')
    numbers = {}
    for field, default in (('economia_minima', 40), ('custo', 30)):
        value = jump.get(field, default)
        if type(value) not in (int, float) or not 0 <= value <= 1000:
            raise ValueError(f'salto_ninja.{field} deve ser um numero de 0 a 1000')
        numbers[field] = value
    return {'save_map': save, 'salto_ninja': {'ativo': jump.get('ativo', True), **numbers}, 'stages': result}


def load(path=None):
    target = Path(path or FILE)
    try:
        return validate(json.loads(target.read_text(encoding='utf-8-sig')))
    except FileNotFoundError:
        save(DEFAULT, target)
        return validate(DEFAULT)


def save(data, path=None):
    data = validate(data)
    target = Path(path or FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(target)
    return data


def stage_steps(stage, save_map, destinations, entries):
    """Passos de save_map (o ponto salvo, ou o mapa onde o personagem esta) ate o mapa da etapa;
    ValueError quando nao ha caminho conhecido."""
    from .auto_routes import path
    portal = stage.get('portal')
    if portal:
        steps = path(save_map, portal['map'], destinations, entries)
        if steps is None:
            raise ValueError(f"{stage['name']}: sem caminho conhecido de {save_map} ate {portal['map']}")
        if steps and steps[-1]['kind'] == 'walk':
            steps = steps[:-1]  # anda direto ao portal, sem parar no ponto de chegada
        return steps+[dict(kind='portal', map=portal['map']+'.gat', position=list(portal['position'])),
                      dict(kind='wait_map', map=stage['map']+'.gat')]
    steps = path(save_map, stage['map'], destinations, entries)
    if not steps:
        raise ValueError(f"{stage['name']}: sem caminho conhecido de {save_map} ate {stage['map']}. "
                         'Atravesse os portais ate la uma vez (o bot aprende) ou grave a rota.')
    return steps


def build_routes(config, destinations, entries):
    """Uma rota temporaria por etapa (mesmo formato da caca pela database), marcada como ciclo."""
    from .database_hunt import DATABASE_HUNT
    routes = []
    for i, stage in enumerate(config['stages']):
        steps = stage_steps(stage, config['save_map'], destinations, entries)
        species = [stage['species']]
        routes.append(dict(id=f'{DATABASE_HUNT}#{i+1}', name=f"Ciclo {i+1}/{len(config['stages'])}: {stage['name']}",
                           enabled=True, map_route_id='', target_map=stage['map']+'.gat', steps=copy.deepcopy(steps),
                           species=species, always_attack=species, attack_priority={}, showmobs_species=species,
                           kills=1, lifecycle_enabled=False, cycle=True, cycle_stage=i,
                           high_jump={'enabled': config['salto_ninja']['ativo'], 'min_saving': config['salto_ninja']['economia_minima'],
                                      'cost': config['salto_ninja']['custo']},
                           goal_minutes=0, goal_item_id=0, goal_item_amount=0, goal_item_name=''))
    return routes


def record_kill(stage_name, species, path=None):
    """Guarda o horario da morte; devolve ha quantos minutos tinha sido a anterior (ou None)."""
    target = Path(path or STATE_FILE)
    try:
        data = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    key = f'{stage_name}|{species}'
    now = datetime.now()
    previous = data.get(key)
    data[key] = now.isoformat(timespec='seconds')
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    except OSError:
        pass
    try:
        return round((now-datetime.fromisoformat(previous)).total_seconds()/60, 1) if previous else None
    except ValueError:
        return None


def stage_on_the_way(routes, here):
    """Indice da etapa cujo caminho passa pelo mapa here (o personagem parou no meio dele), ou None."""
    for i, route in enumerate(routes):
        maps = {PortalGuard.key(s.get('map') or '') for s in route['steps']}
        if here in maps:
            return i
    return None


def steps_from_here(stage, here, destinations, entries):
    """Caminho dinamico do mapa atual ate a etapa (portais e NPCs aprendidos), ou None."""
    try:
        return stage_steps(stage, here, destinations, entries)
    except ValueError:
        return None
