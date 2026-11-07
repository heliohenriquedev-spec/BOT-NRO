"""Reconcile manual board interactions from selected menus and server-confirmed slot changes."""
import copy
import re
import struct

from .npc_labels import plain
from .portals import PortalGuard
from .quest_slots import slot, same_mission


def update_progress(state, mission, operation):
    """Update only the affected mission; unrelated target counters survive a new acceptance."""
    if not state or mission['id'] not in state.get('mission_ids',[]):return False
    identity=mission['id'];done=state.setdefault('completed_missions',{})
    for stage in ('pickup','delivery'):done.setdefault(stage,[])
    if operation=='delivery':
        if identity not in done['delivery']:done['delivery'].append(identity)
    else:
        names={plain(t['name']) for t in mission.get('monster_targets',[])}
        species=set(mission.get('monster_ids',[]))
        for target in state.get('kill_targets',[]):
            if plain(target['name']) in names:species.update(target['species'])
        if names or species:
            state['name_counts']={k:v for k,v in state.get('name_counts',{}).items() if plain(k) not in names}
            state['kill_counts']={k:v for k,v in state.get('kill_counts',{}).items() if int(k) not in species}
        else:
            state['name_counts']={};state['kill_counts']={}
        state['kills']=sum(state['name_counts'].values())+sum(state['kill_counts'].values())
        done['pickup']=[i for i in done['pickup'] if i!=identity]
        done['delivery']=[i for i in done['delivery'] if i!=identity]
        state['skipped_ids']=[i for i in state.get('skipped_ids',[]) if i!=identity]
        if operation=='pickup':done['pickup'].append(identity)
        state['phase']=state['stage']='hunt' if operation=='pickup' else 'pickup'
        state['mission_index']=0;state['step']=0
    return True


class QuestBoardObserver:
    def __init__(self):
        self.context=None;self.slots={};self.pending=None

    def native(self,q,opcode,frame,map_name):
        if opcode==0x90 and len(frame)==7:
            self.context=None
            identity=struct.unpack_from('<I',frame,2)[0];actor=q.actors.get(identity)
            if not actor:return
            from .quest_library import load
            try:data=q.library or load()
            except (OSError,ValueError):return  # a bad local catalogue must not interrupt the game connection
            boards=[b for b in data['boards'] if PortalGuard.key(b['map'])==PortalGuard.key(map_name)
                    and list(b['position'])==list(actor['position'])]
            if len(boards)==1:self.context=dict(npc=identity,board=boards[0]['id'],data=data,mission=None,slot=None,operation=None,accepted_request=False)
            return
        c=self.context;dialog=q.dialog
        if not c or opcode!=0xb8 or len(frame)!=7 or struct.unpack_from('<I',frame,2)[0]!=c['npc']:return
        if not dialog or dialog.get('entity_id')!=c['npc'] or dialog.get('action')!='menu':return
        choice=frame[6];options=dialog.get('options',[])
        if not 1<=choice<=len(options):return
        label=options[choice-1];selected=slot(label);value=plain(label)
        if value in ('completar missao','entregar missao'):c['operation']='delivery'
        elif value in ('aceitar missao','aceitar uma missao'):
            c['operation']='pickup'
            if value=='aceitar missao':c['accepted_request']=True
        elif 'desistir' in value:
            c['operation']=None;self.pending=None;return
        if selected:
            c['slot']=selected['number']
            if not selected['empty']:label=selected['mission']
        matches=[m for m in c['data']['missions'] if m['board_id']==c['board']
                 and same_mission(label,m.get('rank') or m['name'])]
        if selected and not selected['empty']:
            owner=q.slot_owner.get(selected['number'])
            if owner:matches=[m for m in c['data']['missions'] if m['id']==owner]
            elif sum(same_mission(label,m.get('rank') or m['name']) for m in c['data']['missions'])>1:
                matches=[]  # equal ranks on both boards need a known slot owner
        if len(matches)==1:c['mission']=matches[0]
        if c['mission'] and c['slot'] is not None and c['operation']:
            self.pending=dict(c)

    def confirm(self,q,mission,operation,number=None):
        if operation=='delivery':q.daily_marks.append((mission['board_id'],mission.get('rank') or mission['name']))
        if number is not None:
            if operation=='pickup':q.slot_owner[number]=mission['id'];q.slots_dirty=True
            else:q.release_slot(number)
        state=q.progress_state()
        if update_progress(state,mission,operation):
            q.kill_counts={int(k):v for k,v in state['kill_counts'].items()};q.name_counts=state['name_counts'];q.kills=state['kills']
            q.completed_missions=state['completed_missions'];q.skipped_ids=set(state.get('skipped_ids',[]))
            if operation!='delivery':q.last_stage=(state['phase'],0)
            if q.active:q.stop('Estado da missao alterado manualmente; use Retomar fila')
        q.external_updates.append((copy.deepcopy(mission),operation))
        if self.context:self.context['mission']=None;self.context['operation']=None;self.context['accepted_request']=False

    def observe(self,q,events):
        c=self.context
        for event in events:
            if event['kind'] in ('map_change','map_transfer'):
                self.context=self.pending=None;self.slots={};return
            if not c or event['kind']!='npc_dialog' or event.get('entity_id')!=c['npc']:continue
            entries=[s for option in event.get('options',[]) if (s:=slot(option))]
            if entries:
                current={s['number']:s for s in entries};p=self.pending
                if p and p['board']==c['board'] and p['slot'] in current:
                    actual=current[p['slot']];old=self.slots.get(p['slot'])
                    label=p['mission'].get('rank') or p['mission']['name']
                    if p['operation']=='delivery' and actual['empty'] and old and not old['empty'] and same_mission(old['mission'],label):
                        self.confirm(q,p['mission'],'delivery',p['slot']);self.pending=None
                    elif p['operation']=='pickup' and old and old['empty'] and not actual['empty'] and same_mission(actual['mission'],label):
                        self.confirm(q,p['mission'],'pickup',p['slot']);self.pending=None
                self.slots.update(current)
            value=plain(event.get('text',''))
            success=c['operation']=='delivery' and ('recompensa recebida' in value or re.search(r'missao.{0,20}(concluida|entregue|completada).{0,20}sucesso',value))
            accepted=c['operation']=='pickup' and c.get('accepted_request') and any(t in value for t in ('tempo restante','missao aceita','missao iniciada','voce aceitou a missao'))
            if c['mission'] and accepted and not any(t in value for t in ('nao ','ja possui','precisa matar','expirou','esgotado')):
                self.confirm(q,c['mission'],'pickup',c['slot']);self.pending=None
            elif c['mission'] and not any(t in value for t in ('nao ','precisa matar','faltam monstros')) and (success or re.search(r'status\s*:\s*complet',value) or 'ja completou esta missao' in value):
                self.confirm(q,c['mission'],'delivery',c['slot']);self.pending=None
            elif c['mission'] and any(t in value for t in ('tempo esgotado','tempo expirou','missao expirou','missao expirada','prazo expirou','tempo da missao acabou')):
                self.confirm(q,c['mission'],'expired',c['slot']);self.pending=None
