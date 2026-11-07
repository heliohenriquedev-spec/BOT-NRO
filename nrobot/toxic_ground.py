"""Avoid hostile, server-observed ground skills, independently of RCX display settings."""
import heapq
from .map_navigation import server_line
from .ground_cells import AREA_SKILLS, OWN_UNIT_SKILLS, rule

class ToxicGround:
    # Catalogued ground areas are hazards by default; known ally/support fields are excluded.
    # Point-shaped damage/status spells and traps are added explicitly and blocked on received cells.
    SAFE_FIELDS={12,25,27,70,2044,2452,2465,2466,2467,2468,285,286,287}
    POINT_THREATS={18,79,80,87,115,116,117,118,119,120,121,122,123,220,229,404,
        521,725,739,2414,2418,2419,2446,2447,2449,2450,2453,2479,2482,2484,2485,
        2490,2213,2216,2238,2239,2249,2250,2251,2252,2253,2254,3006,3008,3009,8025}
    THREAT_SKILLS=((set(OWN_UNIT_SKILLS)|set(AREA_SKILLS))-SAFE_FIELDS-{516})|POINT_THREATS
    # NRO custom Salamandra Venom Dust: center plus one cell in each cardinal direction.
    CUSTOM_CROSSES={140:1}
    # Legacy hazard units whose area is not always tied to a skill announcement.
    RADII={146:0,225:2,253:2}
    def __init__(self):
        self.reset()

    def reset(self):
        self.units={};self.forecasts={};self.source_skills={};self.revision=0
        self.cached=frozenset();self.cached_revision=-1;self.next_expiry=float('inf')

    @staticmethod
    def position(value):
        return isinstance(value,(list,tuple)) and len(value)==2 and all(type(v) is int and 0<=v<1024 for v in value)

    @staticmethod
    def square(point,radius):
        x,y=point
        return {(a,b) for a in range(max(0,x-radius),min(1023,x+radius)+1)
                      for b in range(max(0,y-radius),min(1023,y+radius)+1)}

    @classmethod
    def skill_cells(cls,skill_id,position,level=1):
        if skill_id in cls.CUSTOM_CROSSES:
            x,y=position
            points={(x,y)}
            for distance in range(1,cls.CUSTOM_CROSSES[skill_id]+1):
                points.update(((x-distance,y),(x+distance,y),(x,y-distance),(x,y+distance)))
            return frozenset((a,b) for a,b in points if 0<=a<1024 and 0<=b<1024)
        model=rule(skill_id)
        if model is None:return frozenset((tuple(position),))
        centre,radius_for_level,_window,spread,_unit_type=model
        radius=max(0,int(radius_for_level(max(1,int(level or 1)))))
        # Meteor units can be distributed around the cast cell; reserve the full model envelope.
        if centre=='unit':radius+=max(0,int(spread))
        return frozenset(cls.square(position,radius))

    def observe(self,events,inventory,now,ground_cells=None,own_id=None):
        seen={}
        for e in events:
            kind=e['kind']
            if kind in ('map_change','map_transfer'):
                self.reset();seen.clear()
            elif kind=='appearance':seen[e['entity_id']]=e.get('species_id')
            elif kind=='ground_effect_removed':
                if self.units.pop(e['effect_id'],None) is not None:self.revision+=1
            elif kind=='ground_effect':
                identity=e['effect_id'];unit=e.get('effect_type')
                if not e.get('visible'):
                    if self.units.pop(identity,None) is not None:self.revision+=1
                elif self.position(e.get('position')) and (identity in self.units or len(self.units)<8192):
                    cells=None;skill_id=None
                    observed=(ground_cells.units.get(identity) if ground_cells is not None else None)
                    if observed:
                        skill_id=observed.get('skill_id')
                        area=observed.get('area')
                        if skill_id in self.THREAT_SKILLS and area and len(area)>=3:
                            cells=frozenset(self.square(area[:2],int(area[2])))
                    source=e.get('source_id')
                    cast=self.source_skills.get(source)
                    if skill_id is None and cast and now<=cast['expires']:
                        limit=max(2,self.CUSTOM_CROSSES.get(cast['skill_id'],0))
                        if max(abs(e['position'][i]-cast['position'][i]) for i in (0,1))<=limit:
                            skill_id=cast['skill_id']
                            if skill_id in self.CUSTOM_CROSSES or rule(skill_id) is not None:
                                cells=self.skill_cells(skill_id,cast['position'],cast['level'])
                            else:
                                cells=frozenset(self.square(e['position'],self.RADII.get(unit,0)))
                    if cells is None and unit in self.RADII:
                        cells=frozenset(self.square(e['position'],self.RADII[unit]))
                    if cells is None and skill_id in self.THREAT_SKILLS:
                        cells=self.skill_cells(skill_id,e['position'])
                    if cells is None:
                        if self.units.pop(identity,None) is not None:self.revision+=1
                        continue
                    value=(cells,unit,skill_id)
                    if self.units.get(identity)!=value:self.units[identity]=value;self.revision+=1
            elif kind=='skill_cast_cancel':
                source=e.get('source_id')
                for key in list(self.forecasts):
                    if key[0]==source:self.forecasts.pop(key);self.revision+=1
                self.source_skills.pop(source,None)
            elif kind in ('skill_cast','ground_skill') and e.get('skill_id') in self.THREAT_SKILLS|set(self.CUSTOM_CROSSES):
                source=e.get('source_id')
                if source is None or source==own_id or not self.position(e.get('position')):continue
                entity=inventory.entities.get(source,{})
                species=seen.get(source,entity.get('species_id'))
                skill_id=e['skill_id']
                if skill_id==140 and species!=1831:continue
                duration=max(0,min(30,(e.get('duration_ms') or 0)/1000))
                level=e.get('level') or 1
                forecast=self.skill_cells(skill_id,e['position'],level)
                self.forecasts[(source,skill_id)]=(forecast,now+duration+2)
                self.source_skills[source]=dict(skill_id=skill_id,position=tuple(e['position']),
                                                level=level,expires=now+duration+30)
                self.revision+=1

    def cells(self,now,*,include_active=True,include_forecasts=True):
        if include_active and include_forecasts and self.cached_revision==self.revision and now<self.next_expiry:return self.cached
        for key,(_,expires) in list(self.forecasts.items()):
            if expires<=now:self.forecasts.pop(key);self.revision+=1
        for source,cast in list(self.source_skills.items()):
            if cast['expires']<=now:self.source_skills.pop(source,None)
        cells=set()
        if include_active:
            for points,_unit,_skill_id in self.units.values():cells.update(points)
        if include_forecasts:
            for points,_ in self.forecasts.values():cells.update(points)
        # Only cache the full union; the independent settings can request subsets.
        if not (include_active and include_forecasts):return frozenset(cells)
        self.cached=frozenset(cells);self.cached_revision=self.revision
        self.next_expiry=min((expires for _,expires in self.forecasts.values()),default=float('inf'))
        return self.cached

    def crosses(self,origin,destination,now,*,include_active=True,include_forecasts=True):
        cells=self.cells(now,include_active=include_active,include_forecasts=include_forecasts)
        return bool(cells and any(point in cells for point in server_line(tuple(origin),tuple(destination))))

    def escape(self,collision,origin,blocked,now,*,include_active=True,include_forecasts=True):
        from .map_navigation import CollisionMap
        hazards=self.cells(now,include_active=include_active,include_forecasts=include_forecasts);origin=tuple(origin)
        if origin not in hazards:return None
        physical=CollisionMap(collision.width,collision.height,collision.cells)
        physical.set_forbidden(set(collision.forbidden)-set(getattr(collision,'hazard_cells',hazards)))
        queue=[(0,0,origin)];parents={origin:None};costs={origin:0};goal=None
        while queue and len(costs)<=8000:
            cost,depth,point=heapq.heappop(queue)
            if cost!=costs[point]:continue
            if point not in hazards:goal=point;break
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                nxt=(point[0]+dx,point[1]+dy)
                if not physical.edge(point,nxt,blocked):continue
                weight=cost+1+(100 if nxt in hazards else 0)
                if weight<costs.get(nxt,float('inf')):
                    costs[nxt]=weight;parents[nxt]=point;heapq.heappush(queue,(weight,depth+1,nxt))
        if goal is None:return None
        path=[];point=goal
        while point is not None:path.append(point);point=parents[point]
        path.reverse()
        for index in range(min(4,len(path)-1),0,-1):
            destination=path[index]
            if physical.segment(origin,destination,blocked,max_steps=4):
                # No re-entry into poison after the first safe cell.
                left=False;valid=True
                for point in server_line(origin,destination):
                    if point not in hazards:left=True
                    elif left:valid=False;break
                if valid:return destination
        # Cornered: every way out crosses the area again (several clouds side by side). Walking over
        # it beats standing inside, which left the character still next to a Salamandra (2026-11-06).
        for index in range(min(4,len(path)-1),0,-1):
            if physical.segment(origin,path[index],blocked,max_steps=4):
                return path[index]
        return None
