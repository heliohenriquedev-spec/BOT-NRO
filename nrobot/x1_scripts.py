"""X1 (1x1 PvP) behaviour files: one per character, imported from a JSON file.

A file is a list of rules read top to bottom; the first rule whose conditions all hold says
what to do. Rules are data, never code: an imported file cannot run anything on the PC.

    {
      "nome": "Meu X1", "versao": 1,
      "regras": [
        {"nome": "Fugir com pouca vida", "se": {"minha_vida_pct": {"<": 30}},
         "faca": {"acao": "afastar", "celulas": 6}},
        {"nome": "Kunai de perto", "se": {"distancia_inimigo": {"<=": 3}, "habilidade_pronta": 524},
         "faca": {"acao": "habilidade", "id": 524, "nivel": 10}},
        {"nome": "Padrao", "faca": {"acao": "atacar"}}
      ]
    }
"""
import json
import shutil
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1]/'data/x1'
EXAMPLE = Path(__file__).resolve().parents[1]/'docs/exemplo_x1.json'

# Situation values a rule can test; numbers compare with < <= > >= == !=, booleans with true/false.
NUMBERS = {'minha_vida_pct': 'vida do personagem (%)', 'meu_sp_pct': 'SP do personagem (%)',
           'vida_inimigo_pct': 'vida do inimigo (%), quando o servidor informa', 'distancia_inimigo': 'distancia ate o inimigo (celulas)',
           'segundos_de_luta': 'segundos desde o inicio do X1'}
FLAGS = {'inimigo_conjurando': 'inimigo conjurando habilidade', 'inimigo_escondido': 'inimigo em hide/cloak',
         'inimigo_visivel': 'inimigo na tela'}
IDS = {'habilidade_pronta': 'habilidade (ID) sem recarga', 'tenho_efeito': 'efeito (ID) ativo no personagem',
       'inimigo_tem_efeito': 'efeito (ID) ativo no inimigo'}
OPERATORS = {'<': lambda a, b: a < b, '<=': lambda a, b: a <= b, '>': lambda a, b: a > b, '>=': lambda a, b: a >= b,
             '==': lambda a, b: a == b, '!=': lambda a, b: a != b}
ACTIONS = {'atacar': (), 'habilidade': ('id', 'nivel'), 'afastar': ('celulas',), 'aproximar': (), 'esperar': ('segundos',),
           'item': ('id',), 'parar': ()}


def validate(data):
    """The file as the bot uses it, or ValueError saying what is wrong (rule number and field)."""
    if not isinstance(data, dict) or not isinstance(data.get('regras'), list) or not data['regras']:
        raise ValueError('O arquivo precisa ter "regras": uma lista com ao menos uma regra')
    if len(data['regras']) > 200:
        raise ValueError('Limite de 200 regras')
    for number, rule in enumerate(data['regras'], 1):
        where = f"Regra {number} ({rule.get('nome', 'sem nome') if isinstance(rule, dict) else '?'})"
        if not isinstance(rule, dict) or not isinstance(rule.get('faca'), dict):
            raise ValueError(where+': falta "faca"')
        for key, test in (rule.get('se') or {}).items():
            if key in NUMBERS:
                if (not isinstance(test, dict) or not test
                        or any(op not in OPERATORS or type(value) not in (int, float) for op, value in test.items())):
                    raise ValueError(where+f': "{key}" precisa ser como {{"<": 30}}')
            elif key in FLAGS:
                if type(test) is not bool:
                    raise ValueError(where+f': "{key}" precisa ser true ou false')
            elif key in IDS:
                if type(test) is not int or test <= 0:
                    raise ValueError(where+f': "{key}" precisa ser um ID numerico')
            else:
                raise ValueError(where+f': condicao desconhecida "{key}" (use: '+', '.join([*NUMBERS, *FLAGS, *IDS])+')')
        action = rule['faca'].get('acao')
        if action not in ACTIONS:
            raise ValueError(where+': acao desconhecida "'+str(action)+'" (use: '+', '.join(ACTIONS)+')')
        for field in ACTIONS[action]:
            if type(rule['faca'].get(field)) not in (int, float) or rule['faca'][field] <= 0:
                raise ValueError(where+f': a acao "{action}" precisa de "{field}" numerico')
    return data


def matches(rule, situation):
    for key, test in (rule.get('se') or {}).items():
        value = situation.get(key)
        if key in NUMBERS:
            if value is None or not all(OPERATORS[op](value, limit) for op, limit in test.items()):
                return False
        elif key in FLAGS:
            if bool(value) != test:
                return False
        elif key == 'habilidade_pronta':
            if test not in (situation.get('habilidades_prontas') or ()):
                return False
        elif key == 'tenho_efeito':
            if test not in (situation.get('meus_efeitos') or ()):
                return False
        elif key == 'inimigo_tem_efeito':
            if test not in (situation.get('efeitos_inimigo') or ()):
                return False
    return True


def decide(data, situation):
    """(rule name, action dict) of the first rule that holds, or None."""
    for rule in data['regras']:
        if matches(rule, situation):
            return rule.get('nome') or 'sem nome', dict(rule['faca'])
    return None


def situation_from_state(state, enemy_id, started_at, now):
    """The values rules test, from the relay state (own HP/SP, enemy row, skills, effects)."""
    own = state.get('player_stats') or {}
    enemy = next((p for p in state.get('players_nearby', []) if p.get('entity_id') == enemy_id), None)
    pct = lambda value, maximum: round(100*value/maximum, 1) if value is not None and maximum else None
    ready = [s['skill_id'] for s in state.get('learned_skills', [])
             if not (state.get('skill_cooldowns') or {}).get(str(s['skill_id']))]
    return {'minha_vida_pct': pct(own.get('hp'), own.get('max_hp')), 'meu_sp_pct': pct(state.get('player_sp'), own.get('max_sp')),
            'vida_inimigo_pct': pct((enemy or {}).get('hp'), (enemy or {}).get('max_hp')),
            'distancia_inimigo': (enemy or {}).get('distance'), 'inimigo_visivel': enemy is not None,
            'inimigo_escondido': bool((enemy or {}).get('hidden')), 'inimigo_conjurando': bool((enemy or {}).get('casting')),
            'segundos_de_luta': round(now-started_at, 1), 'habilidades_prontas': ready,
            'meus_efeitos': [int(k) for k, v in (state.get('own_effects') or {}).items() if v],
            'efeitos_inimigo': list((enemy or {}).get('effects') or [])}


# -- files and the choice per character ----------------------------------------------
def scripts():
    """{file name: validated data or the error text} of every imported X1 file."""
    result = {}
    for path in sorted(FOLDER.glob('*.json')) if FOLDER.exists() else []:
        if path.name == 'personagens.json':
            continue
        try:
            result[path.name] = validate(json.loads(path.read_text(encoding='utf-8')))
        except (OSError, ValueError) as exc:
            result[path.name] = str(exc)
    return result


def import_file(source):
    """Copy a JSON file into data/x1 after checking it; returns its name there."""
    source = Path(source)
    validate(json.loads(source.read_text(encoding='utf-8')))
    FOLDER.mkdir(parents=True, exist_ok=True)
    target = FOLDER/source.name
    if target.resolve() != source.resolve():
        shutil.copyfile(source, target)
    return target.name


def chosen():
    try:
        data = json.loads((FOLDER/'personagens.json').read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def choose(character, name):
    data = chosen()
    if name:
        data[character] = name
    else:
        data.pop(character, None)
    FOLDER.mkdir(parents=True, exist_ok=True)
    (FOLDER/'personagens.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')


def for_character(character):
    """The X1 file chosen for this character (validated), or None."""
    name = chosen().get(character or '')
    data = scripts().get(name) if name else None
    return data if isinstance(data, dict) else None
