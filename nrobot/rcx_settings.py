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
# RCX acts on a skill only for the sides checked; every skill starts with none (no RCX, the
# game's own effect). Where RCX acts and hide_native is checked, the game's effect is withheld.
DEFAULT_STYLE.update(show_allies=False,show_enemies=False)
SIDES_VERSION = 2  # files before it had both sides on by default for every saved entry
DEFAULTS = dict(selection_preview=True, cast_preview=True, preview_opacity=35, preview_color='#70d6ff', preview_symbol='outline', effects={}, skill_styles={})
DEFAULTS['sides_version'] = SIDES_VERSION
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
        for field in ('show_allies','show_enemies'):s[field]=bool(style.get(field,False))
        if 'hide_native' in style:s['hide_native']=bool(style['hide_native'])  # absent: follows the general effect
        s['enabled']=s['show_allies'] or s['show_enemies']
        for field in ('preview_fill','preview_outline'):
            if s[field] is not None and not re.fullmatch(r'#[0-9a-fA-F]{6}',str(s[field])):raise ValueError('Cor da previa invalida')
        if s['preview_symbol'] is not None and s['preview_symbol'] not in SYMBOLS:raise ValueError('Simbolo da previa invalido')
        if s['preview_opacity'] is not None:s['preview_opacity']=max(0,min(100,int(s['preview_opacity'])))
        s['skill_id']=int(key) if section=='skill_styles' else 0
        result[section][str(int(key))] = s
    return result


def migrate_sides(value):
    """Older files: both sides on was only the old default (all skills drawn), so it becomes none;
    a side the user turned off keeps the other one. 'Mostrar este efeito' off means none."""
    if not isinstance(value, dict) or value.get('sides_version') == SIDES_VERSION:return value, False
    value = copy.deepcopy(value)
    for section in ('effects', 'skill_styles'):
        for style in (value.get(section) or {}).values():
            if not isinstance(style, dict):continue
            allies, enemies = style.get('show_allies', True), style.get('show_enemies', True)
            if style.get('enabled', True) is False or (allies and enemies):
                allies = enemies = False
            style.update(show_allies=bool(allies), show_enemies=bool(enemies))
            style.pop('enabled', None)
    value['sides_version'] = SIDES_VERSION
    return value, True


def load():
    try:raw=json.loads(FILE.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, TypeError):return copy.deepcopy(DEFAULTS)
    try:
        raw,migrated=migrate_sides(raw)
        value=validate(raw)
    except (ValueError, TypeError):return copy.deepcopy(DEFAULTS)
    if migrated:
        try:
            backup=FILE.with_name(FILE.name+'.antes_lados')
            if not backup.exists():backup.write_text(FILE.read_text(encoding='utf-8-sig'),encoding='utf-8')
            save(value)
        except OSError:pass
    return value


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
        current = validate(migrate_sides(json.loads(FILE.read_text(encoding='utf-8-sig')))[0])
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
    general=config.get('effects', {}).get(str(unit_type), {})
    skill=config.get('skill_styles', {}).get(str(skill_id), {})
    result={**DEFAULT_STYLE, 'hide_native':False, 'selection_preview':config.get('selection_preview',True), 'cast_preview':config.get('cast_preview',True), **general, **skill}
    # A side checked on the general effect covers all of its skills; one checked on the skill
    # covers that skill. RCX acts on the skill when any side applies.
    for field in ('show_allies','show_enemies'):
        result[field]=bool(general.get(field,False) or skill.get(field,False))
    result['enabled']=result['show_allies'] or result['show_enemies']
    return result


def visible_source(style, source, ground):
    own=ground.get('own_id')
    if source is None:return style.get('show_allies',True) or style.get('show_enemies',True)
    if own is not None and source==own:return style.get('show_allies',True)
    allied=source in ground.get('allied_ids',[])
    return style.get('show_allies' if allied else 'show_enemies',True)


@lru_cache(maxsize=1)
def unit_skills():
    """unit type -> its only skill (shared types: None), skill id -> unit type."""
    single={r['unit_type']:(r['skills'][0]['skill_id'] if len(r['skills'])==1 else None) for r in catalog()}
    units={s['skill_id']:r['unit_type'] for r in catalog() for s in r['skills']}
    return single,units


def hides_native(config, unit_type=None, skill_id=None, source=None, ground=None):
    """The game's own drawing (GRF effect) of this skill is withheld from the client when the entry
    asks for it and RCX acts on it for this caster's side, so it never just vanishes."""
    single,units=unit_skills()
    if unit_type is None:
        unit_type=units.get(skill_id)
        if unit_type is None:return False
    elif skill_id is None:
        skill_id=single.get(unit_type)
    if unit_type not in single:return False
    style=style_for(config,unit_type,skill_id)
    return bool(style['hide_native'] and style['enabled'] and visible_source(style,source,ground or {}))


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
