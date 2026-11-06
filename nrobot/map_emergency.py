"""Confirmed Coelho x3 -> Fukai Kemuri -> retreat until server visibility removal."""
from collections import deque
import copy
import math


def validate(config):
    expected={'species_id','minimum_count','radius','prepare_skill','prepare_casts','area_skill'}
    if not isinstance(config,dict) or set(config)!=expected:
        raise ValueError('Emergencia invalida')
    for key,low,high in [('species_id',1,65535),('minimum_count',2,10),('radius',1,10),('prepare_casts',1,5)]:
        if type(config[key]) is not int or not low<=config[key]<=high:
            raise ValueError('Emergencia: '+key+' invalido')
    for key in ('prepare_skill','area_skill'):
        row=config[key]
        if not isinstance(row,dict) or set(row)!={'skill_id','name'} or type(row['skill_id']) is not int or not 1<=row['skill_id']<=65535 or not isinstance(row['name'],str) or not 1<=len(row['name'])<=100:
            raise ValueError('Habilidade de emergencia invalida')
    return copy.deepcopy(config)


class Emergency:
    # The seal was never confirmed when sent by the bot (ra_fild03, every session of 2026-11-06):
    # the sequence ran out and the character fled without hitting anything, and died. Now an
    # unconfirmed sequence is dropped and the fight goes on; the escape only follows the area skill.
    UNCONFIRMED_LIMIT = 2  # seals sent without an answer before the sequence is dropped
    PAUSE = 30.0  # s without a new emergency after a dropped one
    RETREAT_MAX = 8.0  # s of escape at most

    def __init__(self,config):
        self.config=validate(config)
        self.paused_until=0
        self.reset()

    def reset(self):
        self.phase=None
        self.confirmed=0
        self.waiting=None
        self.targets=set()
        self.started=0
        self.reason=''
        self.unconfirmed=0
        self.retreat_since=None

    def drop(self,now,reason):
        """Give the sequence up: normal combat until PAUSE is over."""
        self.reset()
        self.paused_until=now+self.PAUSE
        self.reason=reason

    def observe(self,events,player_id,now):
        for e in events:
            if e['kind'] in ('map_change','map_transfer'):
                self.reset()
            elif self.waiting and e.get('skill_id')==self.waiting['skill_id']:
                if e['kind']=='skill_failed':
                    self.waiting=None
                elif e['kind']=='skill_no_damage' and e.get('source_id')==player_id and e.get('target_id')==player_id:
                    if e.get('success'):
                        if self.waiting['stage']=='prepare':
                            self.confirmed+=1
                            if self.confirmed>=self.config['prepare_casts']:self.phase='area'
                        else:self.phase='retreat'
                    self.unconfirmed=0
                    self.waiting=None

    def intent(self,state,now,distance):
        visible=[e for e in state.get('recent_entities',[]) if e.get('kind','monster')=='monster' and e.get('species_id')==self.config['species_id']]
        nearby=[e for e in visible if distance(state,e)<=self.config['radius']]
        if self.phase is None and now<self.paused_until:return None
        if self.phase is None and len(nearby)>=self.config['minimum_count']:
            self.phase='prepare';self.started=now
            self.targets={e['entity_id'] for e in visible}
        if self.phase is None:return None
        remaining=[e for e in visible if e['entity_id'] in self.targets]
        if not remaining:
            self.reset()
            return None
        if self.waiting and now>self.waiting['deadline']:
            self.waiting=None
            self.unconfirmed+=1
        if self.phase!='retreat' and (now-self.started>12 or self.unconfirmed>=self.UNCONFIRMED_LIMIT):
            self.drop(now,'sequencia de emergencia nao confirmada pelo servidor; lutando normalmente')
            return None
        if self.phase=='retreat':
            self.retreat_since=self.retreat_since or now
            if now-self.retreat_since>self.RETREAT_MAX:
                self.drop(now,'fuga encerrada; lutando normalmente')
                return None
        target=min(remaining,key=lambda e:distance(state,e))
        return dict(mode='emergency',target_id=target['entity_id'],skill_id=None,phase=self.phase,
                    reason=self.reason or f'emergencia: {self.phase} ({self.confirmed}/{self.config["prepare_casts"]} Coelho confirmados)')

    def plan(self,state,rotation,now,intent):
        if self.phase=='retreat' or self.waiting:return None
        identity=self.config['prepare_skill' if self.phase=='prepare' else 'area_skill']['skill_id']
        # Kemuri may start at level 0 and become available only after three seals.
        meta=next((s for s in state.get('learned_skills',[]) if s['skill_id']==identity and s.get('level',0)>0),None)
        if meta is None or meta.get('target_flags') not in (4,16):
            self.reason='aguardando habilidade de emergencia liberada pelo servidor'
            return None
        for i,p in list(rotation.pending.items()):
            if now>=p['deadline']:
                if p.get('burst_sent') and not p.get('control_status'):rotation.pending.pop(i)
                else:rotation._fail(i,now,'sem confirma\u00e7\u00e3o')
        cooldown=state.get('skill_cooldowns',{})
        previous=max((rotation.last_sent.get(i,0)+rotation.after_skill_delay for i,p in rotation.pending.items() if p['role']=='offensive'),default=0)
        if (identity in rotation.pending or now<max(rotation.next_send,state.get('own_cast_until',0),previous,
            rotation.ready.get(identity,0),rotation.cooldown_floor.get(identity,0),cooldown.get(identity,cooldown.get(str(identity),0)))
            or state.get('state')!='tracking' or not state.get('player_position_recent') or state.get('player_id') is None
            or (state.get('player_sp') or 0)-sum(p['sp_cost'] for p in rotation.pending.values())<meta['sp_cost']):
            return None
        return dict(kind='skill',skill_id=identity,enabled=True,role='offensive',level=meta['level'],interval=.5,
                    effect_id=0,target_id=state['player_id'],combat_target_id=intent['target_id'],cast_mode='self',
                    sp_cost=meta['sp_cost'],control_status='emergency',emergency_stage=self.phase)

    def sent(self,action,now):
        if action.get('emergency_stage'):
            self.waiting=dict(skill_id=action['skill_id'],stage=action['emergency_stage'],deadline=now+2)

    def retreat(self,state,hunt,collision,now,speed):
        if self.phase!='retreat' or collision is None or hunt.pending is not None or now<hunt.ready_at:
            return None
        threats=[e.get('effective_position',e['position']) for e in state.get('recent_entities',[]) if e['entity_id'] in self.targets]
        if not threats:return None
        origin=tuple(state['player_position'])
        blocked={p for p,t in hunt.blocked_until.items() if t>now}
        queue=deque([(origin,0)])
        parents={origin:None}
        best=None
        while queue and len(parents)<1000:
            point,depth=queue.popleft()
            distances=[math.dist(point,p) for p in threats]
            if depth:
                score=(min(distances)+sum(distances)/len(distances)*.1,collision.clearance(point),-depth)
                if best is None or score>best[0]:best=(score,point)
            if depth>=20:continue
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                nxt=(point[0]+dx,point[1]+dy)
                if nxt not in parents and nxt not in blocked and collision.segment(point,nxt,blocked,max_steps=1):
                    parents[nxt]=point;queue.append((nxt,depth+1))
        if best is None:return None
        path=[];point=best[1]
        while point is not None:path.append(point);point=parents[point]
        path.reverse()
        destination=next((path[i] for i in range(min(4,len(path)-1),0,-1) if collision.segment(origin,path[i],blocked,max_steps=4)),None)
        if destination is None:return None
        self.reason='fugindo ate os Jounin sairem da visibilidade recebida do servidor'
        return dict(kind='move',purpose='map_retreat',target_id=None,origin=list(origin),destination=list(destination),
                    collision_route=True,wait_seconds=max(.1,max(abs(destination[i]-origin[i]) for i in (0,1))*speed/1000))
