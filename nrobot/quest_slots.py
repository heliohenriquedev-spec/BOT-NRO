"""Bind recorded board conversations to a mission and live slots, not old slot numbers."""
import copy
import re
from .npc_labels import clean,plain,rank


def slot(value):
    match=re.match(r'^\s*#\s*(\d+)\s+(.+?)\s*$',clean(value))
    if not match:return None
    label=match[2]
    return dict(number=int(match[1]),label=label,empty=plain(label) in ('vazio','vazia','livre'),mission=rank(label) or clean(label))


def same_mission(label,wanted):
    return plain(rank(label) or label)==plain(rank(wanted) or wanted)


def template(steps,stage):
    if not steps or steps[-1]['kind'] not in ('close','cancel'):return None
    if sum(s['kind']=='npc' for s in steps)!=1:return None
    slots=[i for i,s in enumerate(steps) if s['kind']=='select' and slot(s.get('option',''))]
    if len(slots)!=1:return None
    si=slots[0];operations={plain(s.get('option','')) for s in steps if s['kind']=='select'}
    if stage=='pickup':
        ranks=[i for i,s in enumerate(steps) if s['kind']=='select' and rank(s.get('option','')) and not slot(s.get('option',''))]
        if len(ranks)!=1 or ranks[0]<=si or not {'aceitar uma missao','aceitar missao'}<=operations:return None
        return dict(steps=copy.deepcopy(steps),slot_index=si,rank_index=ranks[0])
    if not operations.intersection({'completar missao','entregar missao'}):return None
    if 'desistir de uma missao' in operations:return None
    return dict(steps=copy.deepcopy(steps),slot_index=si)


def board_model(data,board_id,stage):
    """The recorded model of this board; else the other board's, moved onto this one.

    Both boards run the same script (same menus, only the rank list differs), so one recording
    of "pegar" teaches every mission of both."""
    models=data.get('board_templates',{})
    own=models.get(board_id,{}).get(stage)
    if own and template(own.get('steps',[]),stage):return own
    target=next((b for b in data.get('boards',[]) if b['id']==board_id),None)
    if target is None:return {}
    for other,entries in models.items():
        model=entries.get(stage)
        if other==board_id or not model or not template(model.get('steps',[]),stage):continue
        steps=copy.deepcopy(model['steps'])
        for s in steps:
            s['map']=target['map']
            if s['kind']=='npc':s['position']=list(target['position']);s['name']=target['npc_name']
        return dict(model,steps=steps,shared_from=other)
    return {}


def effective_steps(data,m,stage):
    raw=m[stage+'_steps'];source=template(raw,stage)
    learned=board_model(data,m['board_id'],stage)
    if source is None:source=template(learned.get('steps',[]),stage)
    if source is None:return copy.deepcopy(raw)
    wanted=m.get('rank') or rank(m.get('menu_option') or m['name'])
    if not wanted:return copy.deepcopy(raw)
    steps=source['steps'];si=source['slot_index'];prefix=copy.deepcopy(steps[:si]);map_name=steps[si]['map']
    steps[si]=dict(kind='select_free_slot' if stage=='pickup' else 'select_mission_slot',map=map_name,option=wanted)
    if stage=='pickup':steps[source['rank_index']]['option']=wanted
    prefix[0]['verify_start']=True  # may be skipped: the next mission's slot menu proves it too
    steps.extend(prefix)
    steps.extend([dict(kind='verify_slot' if stage=='pickup' else 'verify_slot_absent',map=map_name,option=wanted),dict(kind='cancel',map=map_name)])
    return steps


def confirmation(data,m,stage):
    return m[stage+'_confirmation'] or board_model(data,m['board_id'],stage).get('confirmation','')
