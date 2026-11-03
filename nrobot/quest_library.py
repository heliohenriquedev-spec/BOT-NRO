"""Reusable board access paths and individually confirmed mission conversations."""
import copy
import json
import uuid
from pathlib import Path
from .quest_routes import validate_routes, text
from .portals import PortalGuard, chebyshev
from .npc_labels import clean

FILE=Path(__file__).resolve().parents[1]/'data/rede/quadros_missoes.json'
BOARDS=[dict(id='vip',name='Quadro da Sala Vip',map='ra_in01',position=[219,95],npc_name='Quadro de Missões',
             via=dict(map='areia',position=[144,195],name='Sala Vip'),return_npc=dict(map='ra_in01',position=[213,80],name='Retorno')),
        dict(id='kakashi',name='Quadro de Kakashi',map='kakashi',position=[87,140],npc_name='Quadro de Missões',
             via=dict(map='hospital2',position=[16,74],name=''),return_npc=dict(map='kakashi',position=[83,150],name='Retorno'))]


def validate_steps(steps):
    return validate_routes([dict(name='Trecho',steps=steps)])[0]['steps']


def validate(data):
    if not isinstance(data,dict):raise ValueError('Cadastro de quadros invalido')
    data=copy.deepcopy(data);data['boards']=copy.deepcopy(BOARDS)
    data.setdefault('access_paths',[]);data.setdefault('missions',[])
    data.setdefault('return_enabled',True);data.setdefault('return_paths',{})
    data.setdefault('option_details',{})
    if type(data['return_enabled']) is not bool or not isinstance(data['return_paths'],dict):raise ValueError('Retornos invalidos')
    for identity,entry in data['return_paths'].items():
        b=next((b for b in BOARDS if b['id']==identity),None)
        if not b or not isinstance(entry,dict):raise ValueError('Retorno de quadro invalido')
        entry['steps']=validate_steps(entry.get('steps',[]))
        near=lambda s:chebyshev(s['position'],b['return_npc']['position'])<=2 and PortalGuard.key(s['map'])==b['map']
        if not any(s['kind']=='npc' and near(s) for s in entry['steps']):
            raise ValueError('O retorno precisa incluir o NPC Retorno cadastrado')
        if any(s['kind']=='npc' and not near(s) for s in entry['steps']):
            raise ValueError('Grave somente o caminho e a conversa com Retorno, sem acessar outro NPC')
        if not any(s['kind']=='wait_map' for s in entry['steps']):raise ValueError('Grave a chegada apos usar Retorno')
    if not isinstance(data['option_details'],dict):raise ValueError('Descricoes de opcoes invalidas')
    for identity,options in data['option_details'].items():
        if identity not in ('vip','kakashi') or not isinstance(options,dict):raise ValueError('Descricoes do quadro invalidas')
        for option,lines in options.items():
            if not isinstance(option,str) or not isinstance(lines,list) or len(lines)>30 or any(not isinstance(line,str) or len(line)>4096 for line in lines):
                raise ValueError('Descricao recebida invalida')
    data.setdefault('menus',{})
    data.setdefault('board_templates',{})
    if not isinstance(data['board_templates'],dict):raise ValueError('Modelos de quadro invalidos')
    if not isinstance(data['menus'],dict):raise ValueError('Menus do quadro invalidos')
    for identity,menus in data['menus'].items():
        if (identity not in ('vip','kakashi') or not isinstance(menus,list) or len(menus)>100
            or any(not isinstance(menu,list) or len(menu)>254 or any(not isinstance(s,str) or len(s)>4096 for s in menu) for menu in menus)):
            raise ValueError('Menus do quadro invalidos')
    boards={b['id']:b for b in BOARDS}
    target_lookup=None
    for group in ('access_paths','missions'):
        if not isinstance(data[group],list) or len(data[group])>500:raise ValueError('Limite de 500 cadastros por categoria')
        seen=set()
        for entry in data[group]:
            if not isinstance(entry,dict):raise ValueError('Cadastro invalido')
            entry.setdefault('id',uuid.uuid4().hex)
            if not isinstance(entry['id'],str) or not entry['id'] or entry['id'] in seen:raise ValueError('ID de cadastro duplicado/invalido')
            seen.add(entry['id'])
            if not isinstance(entry.get('board_id'),str) or entry.get('board_id') not in boards:raise ValueError('Quadro desconhecido')
            if not isinstance(entry.get('name'),str) or not entry['name'].strip():raise ValueError('Informe o nome do cadastro')
            entry['name']=clean(entry['name'])
            if group=='access_paths':
                steps=validate_steps(entry.get('steps',[]))
                if not steps:raise ValueError('Percurso de acesso vazio')
                entry['steps']=validate_access(steps,boards[entry['board_id']],steps[-1]['map'],steps[-1].get('position'))
            else:
                from .quest_slots import slot
                from .npc_labels import rank
                old_slot=slot(entry['name'])
                if old_slot and not old_slot['empty'] and rank(old_slot['label']):entry['name']=old_slot['mission']
                entry.setdefault('monster_ids',[]);entry.setdefault('rank','');entry.setdefault('description','');entry.setdefault('target_map','')
                entry.setdefault('monster_names',[]);entry.setdefault('monster_ids_manual',False)
                if (type(entry['monster_ids_manual']) is not bool or not isinstance(entry['monster_names'],list)
                    or any(not isinstance(s,str) for s in entry['monster_names'])):raise ValueError('Nomes de monstros invalidos')
                if not isinstance(entry['monster_ids'],list) or any(type(i) is not int or not 1<=i<=65535 for i in entry['monster_ids']):raise ValueError('Monstros da missao invalidos')
                if any(not isinstance(entry[k],str) for k in ('rank','description','target_map')):raise ValueError('Descricao da missao invalida')
                for stage in ('pickup','delivery'):
                    entry[stage+'_steps']=validate_steps(entry.get(stage+'_steps',[]))
                    entry.setdefault(stage+'_confirmation','')
                    if not isinstance(entry[stage+'_confirmation'],str) or len(entry[stage+'_confirmation'])>1000:
                        raise ValueError('Confirmacao da missao invalida')
                from .npc_labels import rank
                ranks={rank(s.get('option','')) for s in entry['pickup_steps'] if s['kind']=='select'}-{''}
                if not entry['rank']:entry['rank']=rank(entry.get('menu_option') or entry['name']) or (next(iter(ranks)) if len(ranks)==1 else '')
                lines=option_descriptions(data,entry['board_id'],entry.get('menu_option') or entry['rank'] or entry['name'])
                from .quest_targets import targets
                explicit=targets(lines or [entry['description']])
                if explicit:
                    entry['monster_targets']=explicit;entry['monster_names']=[t['name'] for t in explicit]
                    if not entry['description']:entry['description']=clean(' '.join(lines))
                    if not entry['monster_ids_manual']:
                        from .npc_labels import plain
                        if target_lookup is None:
                            from .monster_db import all_monsters
                            target_lookup={}
                            for mon in all_monsters():target_lookup.setdefault(plain(mon['name']),set()).add(mon['species_id'])
                        matches=[target_lookup.get(plain(t['name']),set()) for t in explicit];exact=set().union(*matches)
                        entry['monster_ids']=sorted(exact if all(matches) or not entry['monster_ids'] else set(entry['monster_ids'])|exact)
    from .quest_slots import template
    for identity,models in data['board_templates'].items():
        if identity not in boards or not isinstance(models,dict):raise ValueError('Modelo de quadro invalido')
        for stage,model in models.items():
            if stage not in ('pickup','delivery') or not isinstance(model,dict):raise ValueError('Modelo de missao invalido')
            model['steps']=validate_conversation(model.get('steps',[]),boards[identity])
            if not template(model['steps'],stage) or not isinstance(model.get('confirmation',''),str):raise ValueError('Modelo de slots invalido')
    for m in data['missions']:
        for stage in ('pickup','delivery'):
            if template(m[stage+'_steps'],stage) and m[stage+'_confirmation']:
                data['board_templates'].setdefault(m['board_id'],{}).setdefault(stage,dict(steps=copy.deepcopy(m[stage+'_steps']),confirmation=m[stage+'_confirmation']))
    # Missions ticked in the panel: "Executar: pegar/entregar" runs all of them.
    data.setdefault('checked_missions',[])
    if not isinstance(data['checked_missions'],list) or any(not isinstance(i,str) for i in data['checked_missions']):
        raise ValueError('Selecao de missoes invalida')
    existing={m['id'] for m in data['missions']}
    data['checked_missions']=[i for i in dict.fromkeys(data['checked_missions']) if i in existing]
    return data


def load(path=None):
    path=Path(path or FILE)
    return validate(json.loads(path.read_text(encoding='utf-8'))) if path.exists() else validate({})


def save(data,path=None):
    data=validate(data);path=Path(path or FILE);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)
    return data


def board(data,identity):
    result=next((b for b in data['boards'] if b['id']==identity),None)
    if result is None:raise ValueError('Quadro nao cadastrado')
    return result


def mission(data,identity):
    result=next((m for m in data['missions'] if m['id']==identity),None)
    if result is None:raise ValueError('Missao nao cadastrada: '+str(identity))
    return result


def validate_access(steps,b,end_map,end_position):
    steps=validate_steps(steps)
    if not steps:raise ValueError('Grave o percurso antes de salvar')
    if PortalGuard.key(end_map)!=PortalGuard.key(b['map']) or not end_position or chebyshev(end_position,b['position'])>3:
        raise ValueError('Termine a gravacao ao lado do '+b['name'])
    if any(s['kind']=='npc' and PortalGuard.key(s['map'])==PortalGuard.key(b['map']) and s['position']==b['position'] for s in steps):
        raise ValueError('No percurso de acesso, pare antes de abrir o quadro. Grave as opcoes separadamente.')
    via=b['via']
    if PortalGuard.key(steps[0]['map'])!=PortalGuard.key(b['map']):
        if not any(s['kind']=='npc' and PortalGuard.key(s['map'])==PortalGuard.key(via['map']) and s['position']==via['position'] for s in steps):
            raise ValueError('Este acesso precisa passar pelo NPC '+(via['name'] or via['map'])+' em '+str(via['position']))
    return steps


def validate_conversation(steps,b):
    steps=validate_steps(steps)
    if not steps or steps[0]['kind']!='npc':raise ValueError('Comece a gravacao ao lado do quadro e abra a conversa')
    for s in steps:
        if PortalGuard.key(s['map'])!=PortalGuard.key(b['map']) or s['kind'] not in ('npc','select','next','close','cancel','select_free_slot','select_mission_slot','verify_slot','verify_slot_absent'):
            raise ValueError('Grave somente as opcoes deste quadro, sem caminhar ou trocar de mapa')
        if s['kind']=='npc' and s['position']!=b['position']:raise ValueError('A conversa pertence a outro NPC')
    if steps[-1]['kind'] not in ('close','cancel'):raise ValueError('Conclua e feche o dialogo do quadro antes de salvar as opcoes')
    return steps


def ready_mission(data,identity):
    from .quest_slots import effective_steps,confirmation
    m=mission(data,identity);b=board(data,m['board_id'])
    for stage in ('pickup','delivery'):
        steps=effective_steps(data,m,stage)
        try:validate_conversation(steps,b)
        except ValueError as exc:raise ValueError('Missao '+m['name']+': grave '+('como pegar' if stage=='pickup' else 'como entregar')+'. '+str(exc)) from exc
        if not any(s['kind']=='verify_slot' for s in steps) and not text(confirmation(data,m,stage)):raise ValueError('Grave '+stage+' e a confirmacao da missao '+m['name'])
    return m


def return_steps(data,identity):
    if identity in data['return_paths']:return copy.deepcopy(data['return_paths'][identity]['steps'])
    b=board(data,identity);npc=b['return_npc']
    return [dict(kind='npc',map=npc['map'],position=list(npc['position']),name=npc['name']),dict(kind='wait_transfer',map=npc['map'])]


def enrich_mission(m,descriptions,*,monsters=None):
    from .npc_labels import clean,rank,plain
    from .monster_db import all_monsters
    m['name']=clean(m['name']);m['rank']=m.get('rank') or rank(m['name'])
    description=clean(' '.join(descriptions))[:12000]
    if description:m['description']=description
    hay=' '+plain(m.get('description',''))+' '
    ids=set(m.get('monster_ids',[]))
    if not hay.strip():m['monster_ids']=sorted(ids);return m
    from .quest_targets import targets
    explicit=targets(descriptions or [m.get('description','')])
    if explicit:
        m['monster_targets']=explicit;m['monster_names']=[t['name'] for t in explicit]
        known=monsters if monsters is not None else all_monsters()
        matched={plain(t['name']):{mon['species_id'] for mon in known if plain(mon['name'])==plain(t['name'])} for t in explicit}
        exact=set().union(*matched.values())
        if not m.get('monster_ids_manual'):
            ids=exact if all(matched.values()) or not ids else ids|exact
        m['monster_ids']=sorted(ids);return m
    import re
    for monster in (monsters if monsters is not None else all_monsters()):
        name=plain(monster['name'])
        if len(name)>3 and re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',hay):ids.add(monster['species_id'])
    m['monster_ids']=sorted(ids)
    return m


def option_descriptions(data,board_id,option):
    from .npc_labels import plain
    from .quest_slots import slot
    def key_of(value):
        found=slot(value)
        return plain(found['mission'] if found and not found['empty'] else value)
    return [line for key,lines in data.get('option_details',{}).get(board_id,{}).items() if key_of(key)==key_of(option) for line in lines]
