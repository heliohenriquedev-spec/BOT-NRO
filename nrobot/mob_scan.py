"""@showmobs during the quest hunt: where the monsters still missing are, and the densest spot.

The server answers @showmobs <id> with one minimap mark (0144) per monster of that kind on the map.
From time to time, while the character patrols without a target, the bot asks for every monster the
quest still needs on that map, gathers the marks and walks to where most of them are together.

Timing: right on arrival on the hunting map, then every 60 s, fighting or not; the spot found is
walked to when the patrol has no target. Monsters respawn and wander: a snapshot older than a
minute no longer says where they are, and one query per monster kind every 4 s keeps the chat calm.

Choice: marks of every kind asked are summed; each group (marks within RADIUS) is worth
monsters / (1 + walking cells / DISTANCE_SCALE), with the walking distance along the map, so a far
group wins only when it is much larger (the densest spot of the whole map made the character cross
the map back and forth). A new scan replaces the current spot only when clearly better
(KEEP_MARGIN).

Failure: a round with no answer, or no group that can be walked to, marks the map as failed: no
more @showmobs there (the patrol sweeps the whole map instead, linear walk) until the hunt or the
queue is started again (reset_failures)."""
import math
from collections import Counter, defaultdict

from .portals import chebyshev


class MobScan:
    INTERVAL = 60.0  # s between two searches of the same hunt
    GAP = 4.0  # s between two @showmobs
    LISTEN = 3.0  # s in which marks are taken as the answer to the last @showmobs
    RADIUS = 10  # cells: marks this close together form one group
    MIN_GROUP = 3  # two monsters apart from the rest are not worth crossing the map for
    ARRIVED = 5  # cells from the spot: there
    GOAL_TIME = 60.0  # s to get there before the spot is dropped
    SILENT_ROUNDS = 3  # rounds with no mark at all: the command is not available here
    DISTANCE_SCALE = 40.0  # walking cells that halve a group's worth
    CANDIDATES = 6  # groups measured along the map (path search) per scan
    KEEP_MARGIN = 1.25  # a new spot must be worth this much more than the current one

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
        self.goal = None
        self.goal_until = 0.0
        self.round_open = False

    EARLY_GUARD = 15  # s: an early scan only when the scheduled one is at least this far off

    def seconds_to_next(self, now):
        """How long until the regular INTERVAL scan would run."""
        return self.INTERVAL-(now-self.round_at)

    def start(self, map_name, species, now, idle, early=False):
        """A new round when due: on arrival, then every INTERVAL while patrolling. With early, also
        at once (e.g. 10 s with no quest target) as long as the scheduled scan is >15 s away."""
        if self.suspended or not species or self.map_failed(map_name):
            return False
        if map_name != self.map:
            self.reset()
            self.map = map_name
        if self.queue or self.round_open:
            return False
        due = idle and now-self.round_at >= self.INTERVAL
        if not due and not (early and self.seconds_to_next(now) > self.EARLY_GUARD):
            return False
        self.queue, self.marks, self.round_at, self.round_open = list(dict.fromkeys(species)), [], now, True
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
        if self.silent >= self.SILENT_ROUNDS:
            self.suspended = True
        if own is None:
            return None
        if not marks:
            self.fail()  # no answer or nothing reachable: sweep the map instead
            return None
        bins=defaultdict(list)
        for mark in marks:bins[(mark[0]//self.RADIUS,mark[1]//self.RADIUS)].append(mark)
        def group(mark):
            x,y=mark[0]//self.RADIUS,mark[1]//self.RADIUS
            return [m for dx in (-1,0,1) for dy in (-1,0,1) for m in bins.get((x+dx,y+dy),()) if math.dist(m,mark)<=self.RADIUS]
        groups={}
        for mark in marks:
            members=group(mark)
            if len(members)<self.MIN_GROUP:continue
            centre=(sum(m[0] for m in members)/len(members),sum(m[1] for m in members)/len(members))
            spot=tuple(min(members,key=lambda m:math.dist(m,centre)))  # a real monster cell: walkable
            groups.setdefault(spot,members)
        if not groups:
            self.fail()  # only scattered monsters: not worth walking to, sweep the map instead
            return None
        def worth(count,cells):
            return count/(1+cells/self.DISTANCE_SCALE)
        # Straight-line estimate first, then the walking distance for the best few.
        ranked=sorted(groups.items(),key=lambda item:-worth(len(item[1]),math.dist(item[0],own)))[:self.CANDIDATES]
        paths={}
        scored=[]
        for spot,members in ranked:
            path=collision.route(own,list(spot),exact=True,max_nodes=12000) if collision is not None else None
            cells=len(path)-1 if path else math.dist(spot,own)*(1.4 if collision is not None else 1)
            paths[spot]=path
            scored.append((worth(len(members),cells),spot,members,cells))
        value,spot,members,cells=max(scored,key=lambda s:(s[0],-s[3]))
        if self.goal is not None and now<=self.goal_until and tuple(self.goal)!=spot:
            # Keep heading where we were going unless the new spot is clearly better.
            kept=[m for m in marks if math.dist(m,self.goal)<=self.RADIUS]
            if kept:
                old_path=collision.route(own,self.goal,exact=True,max_nodes=12000) if collision is not None else None
                old_cells=len(old_path)-1 if old_path else math.dist(self.goal,own)
                if value<worth(len(kept),old_cells)*self.KEEP_MARGIN:
                    spot,members,cells,paths[tuple(self.goal)]=tuple(self.goal),kept,old_cells,old_path
        self.goal = list(spot)
        self.goal_until = now+self.GOAL_TIME
        member_set=set(members)
        counts=Counter(species for position,species in records if position in member_set)
        path=paths.get(spot)
        return {'position': self.goal, 'monsters': len(members), 'total': len(marks),
                'species_counts':dict(counts),'queried_species':list(self.queried_species),
                'route_cells':len(path)-1 if path else None,'walk_cells':round(cells)}

    def current_goal(self, own, now):
        if self.goal is None:
            return None
        if now > self.goal_until or (own is not None and chebyshev(own, self.goal) <= self.ARRIVED):
            self.goal = None
        return self.goal
