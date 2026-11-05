"""Persistent RCX appearance. Confirmed units and estimated previews remain separate."""
import copy
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT/'data/rede/rcx_config.json'
SYMBOLS = {'solid': '■ Preenchido', 'outline': '□ Contorno', 'cross': '＋ Cruz', 'diagonal': '× Diagonal', 'diamond': '◇ Losango', 'dot': '• Centro'}
SHAPES = {'point': 'Somente centro', 'square': 'Quadrado', 'diamond': 'Losango', 'cross': 'Cruz', 'sanctuary': 'Santuário (modelo Ragnarok)'}
DEFAULT_STYLE = dict(enabled=True, fill='#808080', outline='#303030', opacity=70, symbol='solid', radius=0, shape='point', skill_id=0)
DEFAULTS = dict(selection_preview=True, cast_preview=True, preview_opacity=35, effects={})


def catalog():
    return json.loads((ROOT/'data/recursos/rcx/skills.json').read_text(encoding='utf-8'))['units']


def validate(value):
    if not isinstance(value, dict):raise ValueError('Configuração RCX inválida')
    result = copy.deepcopy(DEFAULTS)
    for name in ('selection_preview', 'cast_preview'):
        result[name] = bool(value.get(name, result[name]))
    result['preview_opacity'] = max(10, min(100, int(value.get('preview_opacity', 35))))
    for key, style in value.get('effects', {}).items():
        if not str(key).isdigit() or not 126 <= int(key) <= 255:continue
        s = {**DEFAULT_STYLE, **style}
        if any(not re.fullmatch(r'#[0-9a-fA-F]{6}', str(s[c])) for c in ('fill', 'outline')):raise ValueError('Cor deve usar #RRGGBB')
        if s['symbol'] not in SYMBOLS or s['shape'] not in SHAPES:raise ValueError('Símbolo ou formato inválido')
        s.update(enabled=bool(s['enabled']), opacity=max(0,min(100,int(s['opacity']))), radius=max(0,min(15,int(s['radius']))), skill_id=max(0,min(65535,int(s['skill_id']))))
        result['effects'][str(int(key))] = s
    return result


def load():
    try:return validate(json.loads(FILE.read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError):return copy.deepcopy(DEFAULTS)


def save(value):
    value = validate(value)
    FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = FILE.with_suffix('.tmp');temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8');temp.replace(FILE)
    return value


def style_for(config, unit_type):
    return {**DEFAULT_STYLE, **config.get('effects', {}).get(str(unit_type), {})}


def argb(color, opacity=100):
    return (round(opacity*255/100)<<24) | int(color[1:], 16)


def preview_definitions(config, learned):
    learned = {s['skill_id']:s for s in learned if s.get('level', 0)>0 and s.get('target_flags') in (2,32)}
    result={}
    for row in catalog():
        style=style_for(config,row['unit_type'])
        if not style['enabled']:continue
        skills=list(row['skills'])
        if style['skill_id']:skills=[dict(skill_id=style['skill_id'],radius=style['radius'],shape=style['shape'])]
        for skill in skills:
            identity=skill['skill_id']
            if identity not in learned:continue
            custom=str(row['unit_type']) in config['effects']
            result[identity]=dict(skill_id=identity, unit_type=row['unit_type'],
                radius=style['radius'] if custom else min(15,skill['radius']),
                shape=style['shape'] if custom else skill['shape'], **{k:style[k] for k in ('fill','outline','symbol')})
    return list(result.values())[:256]


def footprint(x,y,radius,shape):
    for dx in range(-radius,radius+1):
        for dy in range(-radius,radius+1):
            if shape=='point' and (dx or dy):continue
            if shape=='diamond' and abs(dx)+abs(dy)>radius:continue
            if shape=='cross' and dx and dy:continue
            if shape=='sanctuary' and abs(dx)==radius and abs(dy)==radius:continue
            if 0<=x+dx<1024 and 0<=y+dy<1024:yield [x+dx,y+dy]
