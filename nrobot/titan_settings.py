"""Titan: local-only size/colour changes and hide shortcuts. Shared by the panel and the relay.

Everything here changes only what the own game client draws; the server never receives anything
from Titan. Colour and hiding go through the packets the relay hands the client; size is the
client's own per-unit zoom, set by the panel (titan_zoom).
"""
import copy
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT/'data/rede/titan.json'
SCREEN_FILE = ROOT/'data/rede/titan_tela.json'

SCALE_MIN, SCALE_MAX = 0.3, 4.0
OLD_SIZES = {-2: .5, -1: .75, 0: 1.0, 1: 1.5, 2: 2.0}  # files from the first version (5-step bar)

# Colours the client can tint a body with, each one a status look the client already draws.
# field: opt1 = body state (a value), opt2 = health state (bits), opt3 = 028A visual bits.
COLORS = {
    'none': dict(label='Original', field=None, value=0),
    'red': dict(label='Vermelho', field='opt3', value=0x80),
    'blue': dict(label='Azul (para a animação)', field='opt1', value=2),
    'gray': dict(label='Cinza metálico', field='opt3', value=0x10),
    'stone': dict(label='Pedra (para a animação)', field='opt1', value=1),
    'purple': dict(label='Roxo', field='opt2', value=0x01),
    'dark': dict(label='Escuro', field='opt2', value=0x80),
}

RULE_KINDS = {'entity': 'Só este', 'name': 'Todos com este nome', 'species': 'Toda a espécie'}

NO_KEY = 'Nenhuma'
# Keys a shortcut may use: the number row first (1 = Ishida grande, 2 = ...), then the panel's keys.
KEYS = {str(n): 0x30+n for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 0)}
KEYS.update({f'F{i}': 0x6f+i for i in range(1, 13)})
KEYS.update({'Insert': 0x2d, 'Delete': 0x2e, 'Home': 0x24, 'End': 0x23, 'Page Up': 0x21, 'Page Down': 0x22,
             'Pause': 0x13, 'Scroll Lock': 0x91})
KEYS.update({f'Num {i}': 0x60+i for i in range(10)})

HIDE_WHAT = {
    'players': ('Jogadores', dict(players=True)),
    'summons': ('Invocações', dict(summons=True)),
    'monsters': ('Monstros', dict(monsters=True)),
    'npcs': ('NPCs', dict(npcs=True)),
    'all': ('Tudo', dict(players=True, npcs=True, monsters=True, summons=True)),
}
# mode 'except': hide the group but the marked ones; 'only': hide just the marked ones.
# Marked: except_ids (one unit/player), except_names (everyone with that name), except_species.
HIDE_DEFAULT = dict(what='players', key=NO_KEY, active=False, mode='except', except_ids=[], except_names=[],
                    except_species=[],
                    players=False, npcs=False, monsters=False, summons=False)
DEFAULTS = dict(enabled=True, rules=[], hide_groups=[
    dict(HIDE_DEFAULT, what='players', key='F9', players=True, except_ids=[], except_species=[]),
    dict(HIDE_DEFAULT, what='summons', key='F10', summons=True, except_ids=[], except_species=[]),
    dict(HIDE_DEFAULT, what='monsters', key='F11', monsters=True, except_ids=[], except_species=[])], summon_species=[],
                overlay=dict(visible=False, position=None))


def _int_list(values):
    result = []
    for value in values or []:
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if number >= 0 and number not in result:
            result.append(number)
    return result


def scale_of(rule):
    if isinstance(rule.get('scale'), (int, float)):
        return round(min(SCALE_MAX, max(SCALE_MIN, float(rule['scale']))), 2)
    return OLD_SIZES.get(rule.get('size'), 1.0)


def validate(value):
    if not isinstance(value, dict):
        raise ValueError('Configuração do Titan inválida')
    result = copy.deepcopy(DEFAULTS)
    result['enabled'] = value.get('enabled', True) is True
    rules = []
    for rule in value.get('rules') or []:
        if not isinstance(rule, dict) or rule.get('kind') not in RULE_KINDS:
            continue
        target = str(rule.get('value', '')).strip()
        if not target or (rule['kind'] != 'name' and not target.isdigit()):
            continue
        color = rule.get('color') if rule.get('color') in COLORS else 'none'
        scale = scale_of(rule)
        if scale == 1.0 and color == 'none':
            continue  # nothing left to change
        rules.append(dict(kind=rule['kind'], value=target, scale=scale, color=color,
                          key=rule.get('key') if rule.get('key') in KEYS else NO_KEY,
                          enabled=rule.get('enabled', True) is not False, label=str(rule.get('label', ''))[:60]))
    result['rules'] = rules
    if isinstance(value.get('hide_groups'), list):
        groups = []
        for group in value['hide_groups']:
            if not isinstance(group, dict):
                continue
            what = group.get('what') or group.get('preset')
            if what not in HIDE_WHAT:
                continue  # free groups of the first version
            row = dict(HIDE_DEFAULT, what=what, key=group.get('key') if group.get('key') in KEYS else NO_KEY,
                       active=group.get('active') is True, except_ids=_int_list(group.get('except_ids')),
                       except_species=_int_list(group.get('except_species')),
                       except_names=[str(n).strip() for n in group.get('except_names') or [] if str(n).strip()][:200],
                       mode='only' if group.get('mode') == 'only' else 'except')
            row.update(HIDE_WHAT[what][1])
            groups.append(row)
        result['hide_groups'] = groups
    result['summon_species'] = _int_list(value.get('summon_species'))
    overlay = value.get('overlay') if isinstance(value.get('overlay'), dict) else {}
    position = overlay.get('position')
    result['overlay'] = dict(visible=overlay.get('visible') is True,
                             position=[int(position[0]), int(position[1])] if isinstance(position, list) and len(position) == 2
                             and all(isinstance(v, (int, float)) for v in position) else None)
    return result


def load(path=None):
    path = Path(path or FILE)
    try:
        return validate(json.loads(path.read_text(encoding='utf-8')))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)


def save(config, path=None):
    path = Path(path or FILE)
    data = validate(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, suffix='.tmp', delete=False) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        temporary = handle.name
    os.replace(temporary, path)
    return data
