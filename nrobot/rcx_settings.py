"""Persistent RCX appearance. Confirmed units and estimated previews remain separate."""
import copy
from functools import lru_cache
import json
import re
import os
import tempfile
import hashlib
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT/'data/rede/rcx_config.json'
SYMBOLS = {'solid': '■ Preenchido', 'outline': '□ Contorno', 'cross': '＋ Cruz', 'diagonal': '× Diagonal', 'diamond': '◇ Losango', 'dot': '• Centro'}
SHAPES = {'point': 'Somente centro', 'square': 'Quadrado', 'diamond': 'Losango', 'cross': 'Cruz', 'sanctuary': 'Santuário (modelo Ragnarok)'}
DEFAULT_STYLE = dict(enabled=True, fill='#808080', outline='#303030', opacity=70, symbol='solid', radius=0, shape='point', skill_id=0, area_override=False, preview_appearance=False, selection_preview=True, cast_preview=True, preview_fill=None, preview_outline=None, preview_symbol=None, preview_opacity=None)
DEFAULT_STYLE.update(show_allies=True,show_enemies=True)
DEFAULTS = dict(selection_preview=True, cast_preview=True, preview_opacity=35, preview_color='#70d6ff', preview_symbol='outline', effects={}, skill_styles={})
DEFAULTS['client_vision']=False


@lru_cache(maxsize=1)
def catalog():
    return json.loads((ROOT/'data/recursos/rcx/skills.json').read_text(encoding='utf-8'))['units']


def validate(value):
    if not isinstance(value, dict):raise ValueError('Configuração RCX inválida')
    result = copy.deepcopy(DEFAULTS)
    for name in ('selection_preview', 'cast_preview', 'client_vision'):
        result[name] = bool(value.get(name, result[name]))
    result['preview_opacity'] = max(10, min(100, int(value.get('preview_opacity', 35))))
    color=value.get('preview_color',result['preview_color'])
    if not re.fullmatch(r'#[0-9a-fA-F]{6}',str(color)):raise ValueError('Cor de prévia inválida')
    result['preview_color']=color
    result['preview_symbol']=value.get('preview_symbol','outline')
    if result['preview_symbol'] not in SYMBOLS:raise ValueError('Símbolo de prévia inválido')
    for section,low,high in (('effects',126,255),('skill_styles',1,65535)):
      for key, style in value.get(section, {}).items():
        if not str(key).isdigit() or not low <= int(key) <= high:continue
        s = {**DEFAULT_STYLE, **style}
        if 'preview_appearance' not in style:
            s['preview_appearance']=any(s[k]!=DEFAULT_STYLE[k] for k in ('fill','outline','opacity','symbol'))
        if any(not re.fullmatch(r'#[0-9a-fA-F]{6}', str(s[c])) for c in ('fill', 'outline')):raise ValueError('Cor deve usar #RRGGBB')
        if s['symbol'] not in SYMBOLS or s['shape'] not in SHAPES:raise ValueError('Símbolo ou formato inválido')
        s.update(preview_appearance=bool(s['preview_appearance']),area_override=bool(s['area_override']),enabled=bool(s['enabled']), opacity=max(0,min(100,int(s['opacity']))), radius=max(0,min(15,int(s['radius']))), skill_id=max(0,min(65535,int(s['skill_id']))))
        for field in ('selection_preview','cast_preview'):s[field]=bool(style.get(field,value.get(field,True)))
        for field in ('show_allies','show_enemies'):s[field]=bool(style.get(field,True))
        for field in ('preview_fill','preview_outline'):
            if s[field] is not None and not re.fullmatch(r'#[0-9a-fA-F]{6}',str(s[field])):raise ValueError('Cor da previa invalida')
        if s['preview_symbol'] is not None and s['preview_symbol'] not in SYMBOLS:raise ValueError('Simbolo da previa invalido')
        if s['preview_opacity'] is not None:s['preview_opacity']=max(0,min(100,int(s['preview_opacity'])))
        s['skill_id']=int(key) if section=='skill_styles' else 0
        result[section][str(int(key))] = s
    return result


def load():
    try:return validate(json.loads(FILE.read_text(encoding='utf-8-sig')))
    except (OSError, ValueError, TypeError):return copy.deepcopy(DEFAULTS)


def save(value):
    value = validate(value)
    FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=FILE.parent,
                                         prefix=FILE.name+'.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(FILE)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return value


@contextmanager
def _save_lock():
    if os.name != 'nt':
        yield
        return
    import ctypes as C
    from ctypes import wintypes as W
    k=C.WinDLL('kernel32',use_last_error=True)
    k.CreateMutexW.argtypes=[C.c_void_p,W.BOOL,W.LPCWSTR];k.CreateMutexW.restype=W.HANDLE
    k.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];k.WaitForSingleObject.restype=W.DWORD
    k.ReleaseMutex.argtypes=[W.HANDLE];k.CloseHandle.argtypes=[W.HANDLE]
    identity=hashlib.sha256(str(FILE.resolve()).casefold().encode('utf-8')).hexdigest()[:24]
    handle=k.CreateMutexW(None,False,'Local\\NroRcxSettings_'+identity)
    if not handle:raise OSError('Nao foi possivel reservar a gravacao RCX')
    acquired=False
    try:
        acquired=k.WaitForSingleObject(handle,1000) in (0,0x80)
        if not acquired:raise OSError('Outro painel esta salvando; tente novamente')
        yield
    finally:
        if acquired:k.ReleaseMutex(handle)
        k.CloseHandle(handle)


def save_changes(value, baseline):
    with _save_lock():return _save_changes(value, baseline)


def _save_changes(value, baseline):
    """Merge only this panel's edits; another open RCX panel may have saved newer fields."""
    value, baseline = validate(value), validate(baseline)
    if FILE.exists():
        current = validate(json.loads(FILE.read_text(encoding='utf-8-sig')))
    else:
        current = copy.deepcopy(DEFAULTS)
    for key in DEFAULTS:
        if key not in ('effects', 'skill_styles') and value[key] != baseline[key]:
            current[key] = value[key]
    for section in ('effects', 'skill_styles'):
        for key in baseline[section].keys() | value[section].keys():
            if key not in value[section]:
                current[section].pop(key, None)
                continue
            before = {**DEFAULT_STYLE, **baseline[section].get(key, {})}
            after = {**DEFAULT_STYLE, **value[section][key]}
            edits = {field: new for field, new in after.items() if before.get(field) != new}
            if edits:
                current[section][key] = {**DEFAULT_STYLE, **current[section].get(key, {}), **edits}
    return save(current)


def style_for(config, unit_type, skill_id=None):
    return {**DEFAULT_STYLE, 'selection_preview':config.get('selection_preview',True), 'cast_preview':config.get('cast_preview',True), **config.get('effects', {}).get(str(unit_type), {}), **config.get('skill_styles', {}).get(str(skill_id), {})}


def visible_source(style, source, ground):
    own=ground.get('own_id')
    if source is None:return style.get('show_allies',True) or style.get('show_enemies',True)
    if own is not None and source==own:return True  # own visibility keeps its existing controls
    allied=source in ground.get('allied_ids',[])
    return style.get('show_allies' if allied else 'show_enemies',True)


def external_preview_definitions(config, casts):
    models={s['skill_id']:s for row in catalog() for s in row['skills']}
    keys={(c['skill_id'],max(1,c.get('level') or 1)) for c in casts if c.get('external') and c['skill_id'] in models}
    result={}
    for identity,level in keys:
        known=[dict(skill_id=identity,level=level,target_flags=2 if models[identity].get('ground',True) else 4)]
        definitions=preview_definitions(config,known)
        if definitions:result[identity,level]=definitions[0]
    return result


def argb(color, opacity=100):
    return (round(opacity*255/100)<<24) | int(color[1:], 16)


def preview_definitions(config, learned):
    learned = {s['skill_id']:s for s in learned if s.get('level', 0)>0 and s.get('target_flags') in (2,4,32)}
    result={}
    for row in catalog():
        base=style_for(config,row['unit_type'])
        skills=list(row['skills'])
        for skill in skills:
            identity=skill['skill_id']
            style=style_for(config,row['unit_type'],identity)
            mapped=identity
            if mapped not in learned:continue
            self_centered=learned[mapped].get('target_flags')==4
            if self_centered and skill.get('ground',False):continue
            custom=style['area_override']
            result[mapped]=dict(skill_id=mapped, unit_type=row['unit_type'],
                radius=style['radius'] if custom else min(15,skill.get('radius_by_level',{}).get(str(learned[mapped]['level']),skill['radius'])),
                shape=style['shape'] if custom else skill['shape'], self_centered=self_centered,
                selection_preview=style['selection_preview'], cast_preview=style['cast_preview'],
                show_allies=style['show_allies'],show_enemies=style['show_enemies'],
                preview_fill=style['preview_fill'],preview_outline=style['preview_outline'],preview_symbol=style['preview_symbol'],preview_opacity=style['preview_opacity'],
                **{k:style[k] for k in ('fill','outline','symbol','opacity')})
    return list(result.values())[:256]


def preview_visual(config, definition):
    opacity=definition.get('preview_opacity')
    if opacity is None:opacity=definition['opacity']
    return (argb(definition.get('preview_fill') or definition['fill'],opacity),
            argb(definition.get('preview_outline') or definition['outline'],opacity),
            list(SYMBOLS).index(definition.get('preview_symbol') or definition['symbol']))


def footprint(x,y,radius,shape):
    for dx in range(-radius,radius+1):
        for dy in range(-radius,radius+1):
            if shape=='point' and (dx or dy):continue
            if shape=='diamond' and abs(dx)+abs(dy)>radius:continue
            if shape=='cross' and dx and dy:continue
            if shape=='sanctuary' and radius>0 and abs(dx)==radius and abs(dy)==radius:continue
            if 0<=x+dx<1024 and 0<=y+dy<1024:yield [x+dx,y+dy]
