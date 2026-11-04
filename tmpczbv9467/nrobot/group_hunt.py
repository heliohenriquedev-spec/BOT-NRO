"""Follow an explicitly selected leader using received map events only."""
import math
from .presence_guard import normalize_player_name


class GroupHunt:
    def __init__(self):
        self.target_id = None
        self.target_at = 0
        self.reason = ''

    def leader(self, settings, names, tracks):
        wanted=normalize_player_name(settings.get('group_leader',''))
        matches=[i for i,n in names.items() if wanted and normalize_player_name(n)==wanted and i in tracks]
        return matches[0] if len(matches)==1 else None

    def observe(self, events, leader_id, now):
        for e in events:
            if e['kind'] in ('map_change','map_transfer'):
                self.target_id=None
            elif e['kind']=='remove' and e.get('entity_id') in (self.target_id,leader_id):
                self.target_id=None
            elif leader_id is not None and e.get('source_id')==leader_id and e['kind'] in ('normal_attack','skill_damage','skill_cast'):
                target=e.get('target_id')
                if target and target!=leader_id:
                    self.target_id,self.target_at=target,now
        if self.target_id is not None and now-self.target_at>15:
            self.target_id=None

    def plan_follow(self, state, leader, settings, collision, blocked, speed):
        if leader is None or collision is None:
            self.reason='aguardando lider visivel e mapa de colisao'
            return None
        player=state['player_position'];target=leader
        if math.dist(player,target)<=settings['group_distance']:
            self.reason='seguindo: distancia do lider mantida'
            return None
        path=collision.route(player,target,blocked)
        if not path or len(path)<2:
            self.reason='aguardando rota livre ate o lider'
            return None
        index=1
        for j in range(1,min(len(path),13)):
            if collision.segment(player,path[j],blocked,max_steps=4):
                index=j
                if math.dist(path[j],target)<=settings['group_distance']:break
        destination=list(path[index]);dx,dy=[abs(destination[i]-player[i]) for i in (0,1)]
        steps=max(dx,dy);seconds=max(50,min(speed,2000))/1000
        duration=(steps+.4*min(dx,dy))*seconds
        self.reason='seguindo trajeto do lider'
        return dict(kind='move',purpose='group_follow',target_id=None,origin=list(player),
                    destination=destination,wait_seconds=duration,seconds_per_step=duration/steps,collision_route=True)
