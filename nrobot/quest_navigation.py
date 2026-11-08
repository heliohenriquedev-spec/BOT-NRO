"""Choose known map connections by walking effort, retaining distinct portal arrival cells."""
import heapq
import math

from .portals import PortalGuard


class TravelCost:
    def __init__(self, collision=None, destinations=None):
        self.collision=collision;self.destinations=destinations or {};self.maps={};self.walks={}

    def walk(self,name,start,end,exact=True):
        if end is None:return 0,start
        end=tuple(end)
        if start is None:return 32,end  # landing not recorded: conservative estimated approach
        start=tuple(start);key=(PortalGuard.key(name),start,end,exact)
        if key in self.walks:return self.walks[key]
        distance=max(abs(end[i]-start[i]) for i in (0,1))
        if not exact and distance<=2:return 0,start
        name=PortalGuard.key(name)
        if name not in self.maps:
            try:self.maps[name]=self.collision(name+'.gat') if self.collision else None
            except (OSError,ValueError,KeyError):self.maps[name]=None
        collision=self.maps[name]
        if collision is not None:
            route=collision.route(start,end,exact=exact,max_nodes=8000,greed=1.3,wall_cost=0)
            if route:
                result=(sum(math.dist(a,b) for a,b in zip(route,route[1:])),tuple(route[-1]))
            else:result=(distance+200,end)  # bounded search could not validate the approach
        else:result=(distance,end)
        self.walks[key]=result
        return result

    def leg(self,origin,position,steps):
        cost=0;here=PortalGuard.key(origin);last=None
        for step in steps:
            kind=step['kind']
            if kind=='wait_map':
                there=PortalGuard.key(step['map']);arrival=step.get('arrival')
                if last and not arrival:
                    label=','.join(str(v) for v in last)
                    links=self.destinations.get(here,self.destinations.get(here+'.gat',{}))
                    record=links.get(label,{})
                    if PortalGuard.key(record.get('map',''))==there:arrival=record.get('arrival')
                cost+=8;here=there;position=tuple(arrival) if arrival else None;last=None
            elif step.get('position') is not None:
                effort,position=self.walk(here,position,step['position'],exact=kind!='npc')
                cost+=effort;last=tuple(step['position'])
                if kind=='npc':cost+=2
            elif kind in ('next','select','select_free_slot','select_mission_slot'):cost+=1
        return cost,position,here


def closest_connection(edges, origin, target, position=None, target_position=None, collision=None, destinations=None):
    """Dijkstra over (map, arrival), so fewer map changes need not mean less walking."""
    origin,target=PortalGuard.key(origin),PortalGuard.key(target)
    if origin==target:return []
    costs=TravelCost(collision,destinations)
    start=(origin,tuple(position) if position is not None else None)
    queue=[(0,0,start,[])];best={start:0};serial=0;winner=None;winner_cost=math.inf
    while queue:
        cost,_,state,path=heapq.heappop(queue)
        if cost!=best[state]:continue
        if cost>=winner_cost:break
        here,point=state
        if here==target:
            final,_=costs.walk(target,point,target_position,exact=False)
            if cost+final<winner_cost:winner,winner_cost=path,cost+final
            continue
        for there,leg in edges.get(here,[]):
            extra,landing,_=costs.leg(here,point,leg)
            state_next=(PortalGuard.key(there),landing)
            candidate=cost+extra
            if candidate<best.get(state_next,math.inf):
                best[state_next]=candidate;serial+=1
                heapq.heappush(queue,(candidate,serial,state_next,path+leg))
    if winner is None:raise ValueError('Sem caminho conhecido de '+origin+' para '+target)
    return winner
