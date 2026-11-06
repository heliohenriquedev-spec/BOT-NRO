"""@showmobs during the quest hunt: where the monsters still missing are, and the densest spot.

The server answers @showmobs <id> with one minimap mark (0144) per monster of that kind on the map.
From time to time, while the character patrols without a target, the bot asks for every monster the
quest still needs on that map, gathers the marks and walks to where most of them are together.

Timing: right on arrival on the hunting map, then every 60 s, fighting or not; the spot found is
walked to when the patrol has no target. Monsters respawn and wander: a snapshot older than a
minute no longer says where they are, and one query per monster kind every 4 s keeps the chat calm.

Choice: marks of all requested kinds are summed into sliding 50x50-cell fields. The most populated
reachable field wins; walking distance only breaks ties. The selected field is sticky between
scans, avoiding oscillation when counts are close. The character heads to a reachable monster mark
near that field's center.

No answer or no useful group does not disable scanning: the patrol continues normally and the next
scheduled (or no-target) round retries. Three fully silent rounds raise a diagnostic warning only;
they do not permanently disable the command because a later response may still arrive."""
import math
from collections import Counter, defaultdict

from .portals import chebyshev


class MobScan:
    INTERVAL = 60.0  # s between two searches of the same hunt
    GAP = 4.0  # s between two @showmobs
    LISTEN = 3.0  # s in which marks are taken as the answer to the last @showmobs
    FIELD_SIZE = 50
    ARRIVED = 0  # patrol confirms arrival itself; retain the exact destination until then
    GOAL_TIME = 180.0  # s: far fields can require more than one 60 s scan interval to reach
    SILENT_ROUNDS = 3  # rounds with no mark at all: show a warning, then keep retrying
    KEEP_MARGIN = 1.25  # switch fields only if the new field is clearly denser
    FAR_SINGLE = 60  # walking cells: a lone monster farther than this is not a destination

    def __init__(self):
        self.reset()
        self.silent = 0
        self.suspended = False
        self.failed_maps = set()

    def reset_failures(self):
        """Hunt or queue started again: @showmobs is tried again on every map."""
        self.failed_maps.clear()
        self.silent = 0
        self.suspended = False

    def map_failed(self, map_name):
        from .portals import PortalGuard
        return PortalGuard.key(map_name) in self.failed_maps

    def fail(self):
        from .portals import PortalGuard
        if self.map:
            self.failed_maps.add(PortalGuard.key(self.map))
        self.goal = None

    def reset(self):
        self.map = None
        self.queue = []
        self.marks = []
        self.mark_records = {}
        self.current_species = None
        self.queried_species = []
        self.sent_at = -1e9
        self.round_at = -1e9
        self.last_early_at = -1e9
        self.goal = None
        self.goal_until = 0.0
        self.round_open = False

    EARLY_GUARD = 15  # s: an early scan only when the scheduled one is at least this far off
    EARLY_INTERVAL = 10.0  # s: minimum time between scans started by the no-target trigger

    def seconds_to_next(self, now):
        """How long until the regular INTERVAL scan would run."""
        return self.INTERVAL-(now-self.round_at)

    def start(self, map_name, species, now, idle, early=False):
        """A new round when due: on arrival, then every INTERVAL while patrolling. With early, also
        after a 10 s no-target window as long as the scheduled scan is >15 s away. Early rounds are
        throttled so a long no-target period does not immediately restart after each reply."""
        if not species:
            return False
        if map_name != self.map:
            self.reset()
            self.map = map_name
            self.silent = 0
            self.suspended = False
        if self.queue or self.round_open:
            return False
        due = idle and now-self.round_at >= self.INTERVAL
        early_due = (early and self.seconds_to_next(now) > self.EARLY_GUARD
                     and now-self.last_early_at >= self.EARLY_INTERVAL)
        if not due and not early_due:
            return False
        self.queue, self.marks, self.round_at, self.round_open = list(dict.fromkeys(species)), [], now, True
        if early_due:
            self.last_early_at = now
        self.mark_records={};self.queried_species=[]
        return True

    def next_command(self, now):
        if self.queue and now-self.sent_at >= self.GAP:
            return self.queue[0]
        return None

    def sent(self, species, now):
        if self.queue and self.queue[0] == species:
            self.queue.pop(0)
        self.sent_at = now
        self.current_species=species;self.queried_species.append(species)

    def observe(self, events, now):
        if not self.round_open or now-self.sent_at > self.LISTEN:
            return
        for event in events:
            if event['kind'] == 'viewpoint' and event.get('mark_type') == 1 and event.get('position'):
                position=tuple(event['position'])
                if len(position)!=2 or any(type(v) is not int or not 0<=v<1024 for v in position):continue
                identity=event.get('npc_id')
                key=('actor',identity) if identity else ('anonymous',len(self.mark_records))
                self.mark_records[key]=(position,self.current_species)
        self.marks=[record[0] for record in self.mark_records.values()]

    def include_cached(self, marks, now, ttl, species_filter=()):
        """Include still-live minimap marks retained across scan rounds by the relay."""
        if not self.round_open:
            return
        allowed=set(species_filter)
        for identity,record in marks.items():
            if now-record.get('at',0)>ttl:
                continue
            species=record.get('species')
            if species is not None and allowed and species not in allowed:
                continue
            npc_id,mark_id=identity
            key=('actor',npc_id) if npc_id else ('mark',mark_id)
            position=tuple(record.get('position') or ())
            if len(position)==2 and all(type(v) is int and 0<=v<1024 for v in position):
                self.mark_records[key]=(position,species)
        self.marks=[record[0] for record in self.mark_records.values()]

    def finish(self, own, now, walkable=None, collision=None):
        """After the last answer: the group worth the most (size against walking distance) becomes
        the goal. Returns it (or None)."""
        if not self.round_open or self.queue or now-self.sent_at <= self.LISTEN:
            return None
        self.round_open = False
        reachable=collision.reachable(own) if collision is not None and own is not None else None
        records=[r for r in self.mark_records.values() if (walkable is None or walkable(r[0])) and (reachable is None or r[0] in reachable)]
        marks=[r[0] for r in records]
        self.silent = 0 if self.marks else self.silent+1
        if self.marks:
            self.suspended = False
        elif self.silent >= self.SILENT_ROUNDS:
            self.suspended = True
        if own is None:
            return None
        if not marks:
            self.fail()  # use the linear patrol, but retry on the next scheduled/early round
            return None
        # Find the densest sliding window, rather than fixed map-aligned tiles which split one
        # crowd across an arbitrary x/y boundary. Marks are already restricted to reachable cells.
        candidates=[]
        for x0 in sorted({p[0] for p in marks}):
            in_x=sorted((p for p in marks if x0<=p[0]<x0+self.FIELD_SIZE),key=lambda p:(p[1],p[0]))
            left=0
            best_count=0
            best_window=None
            for right in range(len(in_x)):
                while in_x[right][1]-in_x[left][1]>=self.FIELD_SIZE:
                    left+=1
                count=right-left+1
                if count<best_count:
                    continue
                y0=in_x[left][1]
                members=in_x[left:right+1]
                field=(x0,y0)
                center=(x0+(self.FIELD_SIZE-1)/2,y0+(self.FIELD_SIZE-1)/2)
                selected=min(members,key=lambda p:(math.dist(p,center),math.dist(p,own),p))
                candidate=(field,members,tuple(selected),center)
                if count>best_count or best_window is None or math.dist(selected,own)<math.dist(best_window[2],own):
                    best_count=count
                    best_window=candidate
            if best_window is not None:
                candidates.append(best_window)
        if not candidates:
            self.fail()
            return None
        # Collapse different window origins that describe the same group.
        unique={}
        for item in candidates:
            key=frozenset(item[1])
            old=unique.get(key)
            if old is None or math.dist(item[2],own)<math.dist(old[2],own):
                unique[key]=item
        candidates=list(unique.values())
        candidates.sort(key=lambda c:(-len(c[1]),math.dist(c[2],own),c[0]))
        best=candidates[0]
        kept=next((c for c in candidates if self.goal is not None
                   and c[3][0]-self.FIELD_SIZE/2 <= self.goal[0] < c[3][0]+self.FIELD_SIZE/2
                   and c[3][1]-self.FIELD_SIZE/2 <= self.goal[1] < c[3][1]+self.FIELD_SIZE/2),None)
        if kept and len(best[1]) <= len(kept[1])*self.KEEP_MARGIN:
            best=kept
        field,members,spot,center=best
        if kept is best and self.goal is not None:
            spot=tuple(min(members,key=lambda p:(math.dist(p,self.goal),math.dist(p,own),p)))
        path=collision.route(own,list(spot),exact=True,max_nodes=12000) if collision is not None else None
        if collision is not None and not path:
            self.fail()
            return None
        cells=len(path)-1 if path else math.dist(spot,own)
        if len(members)<2 and cells>self.FAR_SINGLE:
            # One monster on the other side of the map is not worth the walk: keep patrolling.
            self.goal=None
            return None
        from .portals import PortalGuard
        self.failed_maps.discard(PortalGuard.key(self.map))
        self.goal = list(spot)
        self.goal_until = now+self.GOAL_TIME
        member_set=set(members)
        counts=Counter(species for position,species in records if position in member_set and species is not None)
        return {'position': self.goal, 'monsters': len(members), 'total': len(marks),
                'species_counts':dict(counts),'queried_species':list(self.queried_species),
                'field':list(field),'field_size':self.FIELD_SIZE,
                'route_cells':len(path)-1 if path else None,'walk_cells':round(cells)}

    def current_goal(self, own, now):
        if self.goal is None:
            return None
        if now > self.goal_until or (own is not None and chebyshev(own, self.goal) <= self.ARRIVED):
            self.goal = None
        return self.goal
