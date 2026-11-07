"""REDE-40: novelty-biased exploration with a persistent travel heading.

With collision data the map is covered through an ordered circuit of open-ground
waypoints (patrol_tour.py), shortened using walkable distances. Coverage is remembered
per map and the connecting paths do not add novelty detours. Branches and bottlenecks
may require returning through previously visited ground."""
from collections import Counter, deque
import math
import random
import time

from .patrol_tour import SPACING, PatrolTour


class PacketPatrol:
    DIRECTIONS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
    GOAL_TIMEOUT = 25  # seconds without getting closer before a waypoint is put aside
    FOCUS_RETRY_DELAY = 45
    FOCUS_ROUTE_NODES = 12000  # same search size as the @showmobs scan that chose the spot
    FOCUS_CLUSTER_RADIUS = 12  # suppress tiny @showmobs marker shifts around the same group
    ROUTE_NODES = 4000  # cell search budget per plan (~0.1 s); longer trips go by stepping stones
    ROUTE_GREED = 1.5
    MAP_FIELDS = ('tour', 'remaining', 'done', 'walked', 'cycle_number', 'sweep_order', 'corridor_plan', 'last_passage')
    # Mazes where the planned walk measured worse than the nearest pending waypoint
    # (tools/validar_patrulha.py, 6 starts each, 2026-11-05: gl_sew02 +16% steps).
    NEAREST_FIRST_MAPS = frozenset({'gl_sew02.gat', 'gl_sew02'})

    def __init__(self, max_step=8, rng=None, *, spacing=SPACING, coverage=1.0, wall_margin=2, avoid_walls=False):
        if not 1 <= max_step <= 8:
            raise ValueError('Trecho de patrulha deve ter entre uma e oito células')
        self.max_step = max_step
        self.layout = dict(spacing=spacing, wall_margin=wall_margin, avoid_walls=avoid_walls)
        self.coverage_target = coverage  # share of the map's waypoints passed before a new cycle starts
        self.rng = rng if rng is not None else random.Random()
        self.reset()

    def route(self, collision, start, goal, **options):
        route=self.direct_route(collision,start,goal,**options)
        if not route or len(route)<2 or options.get('partial') or not self.last_passage:
            return route
        start_sector=(start[0]//4,start[1]//4)
        sectors={(p[0]//4,p[1]//4) for p in route}-{start_sector}
        if not sectors or not sectors.issubset(self.last_passage):
            return route  # fresh ground remains the first choice
        oldest,newest=min(self.last_passage.values()),max(self.last_passage.values())
        costs={s:.25+2.75*(at-oldest)/max(1,newest-oldest) for s,at in self.last_passage.items()}
        alternative=collision.route(start,goal,**{**options,'sector_costs':costs})
        if alternative and len(alternative)-1 <= (len(route)-1)*1.25+8:
            def recency(path):
                return sum(costs.get((p[0]//4,p[1]//4),0) for p in path
                           if (p[0]//4,p[1]//4)!=start_sector)
            if recency(alternative)<recency(route):return alternative
        return route

    def direct_route(self, collision, start, goal, **options):
        """Route that keeps off walls, unless that costs a long detour: in mazes of one-cell
        corridors keeping off walls chose ways 3-4 times longer (gl_sew02: 436 steps for a
        119-step trip), back and forth over the same ground."""
        route = collision.route(start, goal, **options)
        if not route or options.get('partial') or not options.get('wall_cost'):
            return route
        steps = len(route)-1
        straight = max(abs(goal[0]-start[0]), abs(goal[1]-start[1]))
        if steps <= straight*1.25+10:
            return route  # nearly straight: no shorter way to look for
        shortest = collision.route(start, goal, **{**options, 'wall_cost': 0})
        if shortest and steps > (len(shortest)-1)*1.25+10:
            return shortest
        return route

    def wall_cost(self):
        """Walking next to a wall costs more, much more when walls are to be avoided."""
        return 18 if self.layout.get('avoid_walls') else 3

    def configure(self, *, spacing, coverage, wall_margin, avoid_walls):
        """New spacing/margins redo each map's waypoints; what was walked (visits) is kept."""
        layout = dict(spacing=spacing, wall_margin=wall_margin, avoid_walls=avoid_walls)
        self.coverage_target = coverage
        if layout != self.layout:
            self.layout = layout
            self.map_memory = {}
            self.tour = None
            self.goal = self.goal_block = None

    def reset(self):
        self.map_memory = {}
        self.visits = Counter()
        self.last_passage = {}
        self.observed_position = None
        self.last_sector = None
        self.heading = self.rng.choice(self.DIRECTIONS)
        self.goal = None
        self.goal_block = None
        self.search_destination = None
        self.focus = None  # a spot to go to first (@showmobs); reached through the normal waypoints
        self.focus_reached = None  # the last such spot reached: not gone to again
        self.focus_history = []  # scan areas already reached during this coverage cycle
        self.focus_suppressed = None
        self.focus_suppressed_until = 0
        self.focus_key = None
        self.focus_block = None
        self.linear = True  # all maps: one planned walk through every pending point
        self.goal_at = 0
        self.goal_distance = None
        self.last_plan_position = None
        self.last_plan_at = 0
        self.tour = None
        self.remaining = set()
        self.sweep_order = []
        self.corridor_plan = []
        self.done = set()
        self.walked = set()  # 4x4 sectors walked this cycle: routes prefer fresh ground
        self.partial_ends = {}  # waypoint -> ends of partial routes already walked toward it
        self.cycle_number = 1
        self.deferred = {}
        self.retried = False
        self.route_cache_key = None
        self.route_cache = None
        self.failed_edges = {}
        self.retry_at = 0
        self.fail_streak = (None, 0)
        self.unreachable = set()  # waypoints the server would not let us reach this cycle
        self.steps = 0
        self.recent_sectors = deque(maxlen=24)
        self.recent_positions = deque(maxlen=10)
        self.last_direction = None
        self.straight_steps = 0
        self.loop_escapes = 0
        self.escape_next = False

    @staticmethod
    def sectors_on_segment(origin, destination):
        length = max(abs(destination[i]-origin[i]) for i in (0, 1))
        points = [origin] if length == 0 else [
            [round(origin[j]+(destination[j]-origin[j])*i/length) for j in (0, 1)]
            for i in range(length+1)]
        sectors = []
        for point in points:
            sector = (point[0]//4, point[1]//4)
            if not sectors or sector != sectors[-1]:
                sectors.append(sector)
        return sectors

    def reached(self, position, origin=None, now=None):
        now=time.monotonic() if now is None else now
        if origin is not None and max(abs(position[i]-origin[i]) for i in (0, 1)) > 2*self.max_step+2:
            origin = None  # a jump (inner portal, teleport): nothing was walked in between
        for sector in self.sectors_on_segment(origin or position, position):
            self.last_passage[sector]=now
            self.walked.add(sector)
            if sector != self.last_sector:
                self.visits[sector] += 1
                self.recent_sectors.append(sector)
                self.last_sector = sector
        if self.tour is not None:
            start = origin or position
            length = max(abs(position[i]-start[i]) for i in (0, 1))
            for step in sorted({*range(0, length+1, 2), length}):
                point = [round(start[i]+(position[i]-start[i])*step/max(length, 1)) for i in (0, 1)]
                self.mark_seen(point)
        if origin is not None and list(position) != list(origin):
            direction = tuple((position[i] > origin[i])-(position[i] < origin[i]) for i in (0, 1))
            self.straight_steps = self.straight_steps+1 if direction == self.last_direction else 1
            self.last_direction = direction
            self.steps += 1
            self.recent_positions.append(tuple(position))
            if len(self.recent_positions) == 10 and len(set(self.recent_positions)) <= 4:
                self.escape_next = True
                self.loop_escapes += 1
                self.recent_positions.clear()

    def observe_position(self, position, now, map_name=None):
        """Account for real progress during combat, quest travel or a different patrol goal."""
        if self.tour is None or position is None:return
        collision=self.tour.collision
        name=getattr(collision,'name',None)
        if name and map_name and name.lower().removesuffix('.gat')!=map_name.lower().removesuffix('.gat'):
            self.observed_position=None;return
        point=tuple(round(v) for v in position)
        if point==self.observed_position:return
        if not collision.walkable(point):return
        origin=self.observed_position
        if origin is not None and not collision.line_clear(origin,point):origin=None
        self.reached(point,origin,now=now)
        self.observed_position=point

    def mark_seen(self, point):
        for block in self.tour.seen_from(point):
            if block in self.remaining:
                self.remaining.discard(block)
                self.done.add(block)

    def recover_stall(self, position, now):
        """Resume the existing coverage cycle from a reachable sector after repeated no-action ticks."""
        if self.tour is None or position is None:
            return False
        distances = self.tour.distances(position)
        pending = self.remaining-set(self.deferred)
        reachable = [block for block in self.sweep_order if block in pending and block in distances]
        unreachable = [block for block in self.sweep_order if block in pending and block not in distances]
        if self.linear or self.tour.corridor_mode:
            self.corridor_plan = self.tour.plan_order(position, reachable) if reachable else []
        else:
            # Preserve the cycle order, but move sectors inaccessible from the current component
            # behind reachable ones. Rebuilding the whole tour here used to send the player back.
            self.sweep_order = reachable+unreachable+[b for b in self.sweep_order if b not in pending]
        self.deferred.clear()
        self.failed_edges.clear()
        self.goal = self.goal_block = None
        self.route_cache_key = self.route_cache = None
        self.retry_at = 0
        if self.focus is not None:
            self.goal = tuple(self.focus)
            self.goal_at = now
            self.goal_distance = math.dist(position, self.focus)
        return bool(reachable)

    def update_focus(self, point, now):
        """Keep a live scan target stable while the marker jitters inside one monster group."""
        if not point:
            return
        candidate = tuple(point)
        if self.focus is not None:
            return  # finish the current scan trip before accepting a competing destination
        if any(math.dist(candidate, old) <= self.FOCUS_CLUSTER_RADIUS for old in self.focus_history):
            return
        if self.focus_reached is not None and math.dist(candidate, self.focus_reached) <= self.FOCUS_CLUSTER_RADIUS:
            return
        if (self.focus_suppressed is not None and now < self.focus_suppressed_until
                and math.dist(candidate, self.focus_suppressed) <= self.FOCUS_CLUSTER_RADIUS):
            return
        if candidate != self.focus:
            self.focus = list(candidate)
            self.goal = self.goal_block = None
            self.route_cache_key = self.route_cache = None
            self.goal_at = now
            self.goal_distance = None

    CYCLE_KEEP = 1800  # s on one map before its coverage starts over (and on every new visit)

    def switch_map(self, collision, position):
        """A new collision object for the same map (e.g. portal cells learned) keeps the coverage;
        another map starts from scratch: what was walked on a map is dropped on leaving it."""
        same_map = (self.tour is not None and getattr(self.tour.collision, 'name', None) is not None
                    and getattr(self.tour.collision, 'name', None) == getattr(collision, 'name', None))
        self.map_memory = {}
        if same_map:
            self.map_memory[id(collision)] = {f: getattr(self, f) for f in self.MAP_FIELDS}
        elif self.tour is not None:
            self.focus = self.focus_reached = self.focus_suppressed = None
            self.focus_history = []
            self.last_passage = {}
        self.goal = self.goal_block = self.search_destination = None
        self.observed_position = None
        self.focus_key = self.focus_block = None
        self.route_cache_key = self.route_cache = None
        self.deferred = {}
        self.failed_edges = {}
        self.partial_ends = {}
        saved = self.map_memory.get(id(collision))
        if saved is not None and tuple(position) in saved['tour'].cells:
            saved = dict(saved, tour=PatrolTour(collision, position, **self.layout)) if saved['tour'].collision is not collision else saved
            self.cycle_started_at = getattr(self, 'cycle_started_at', None)
            for field, value in saved.items():
                setattr(self, field, value)
            return
        self.tour = PatrolTour(collision, position, **self.layout)
        self.sweep_order = self.tour.sweep_order(position)
        self.corridor_plan = []
        self.cycle_started_at = None
        self.cycle_number = 1
        self.done, self.walked = set(), set()
        self.remaining = set(self.tour.points)
        self.mark_seen(position)

    def new_cycle(self, position):
        self.cycle_number += 1
        self.sweep_order = self.tour.sweep_order(position)
        self.corridor_plan = []
        self.unreachable.clear()
        self.remaining = set(self.tour.points)
        self.done.clear()
        self.walked.clear()
        self.focus_history.clear()
        self.deferred.clear()
        self.partial_ends = {}
        self.goal = self.goal_block = None
        self.focus_key = self.focus_block = None
        self.mark_seen(position)
        if not self.remaining:  # tiny map: everything is in view from here
            self.remaining = set(self.tour.points)-set(self.tour.seen_from(position)) or set(self.tour.points)

    def resume_forward(self, position):
        """Rotate the existing circuit to a nearby pending point after a combat/scan detour.

        No new tour or all-pairs search, and skipped pending points stay in the same cycle.
        Corridor branch traversal retains its ordered return through bottlenecks.
        """
        if self.tour is None or self.tour.corridor_mode:
            return
        pending = self.remaining-set(self.deferred)
        distances = self.tour.distances(position)
        order = self.corridor_plan if self.linear and self.corridor_plan else self.sweep_order
        candidates = [b for b in order if b in pending and b in distances]
        if not candidates:
            return
        nearest = min(distances[b] for b in candidates)
        nearby = [b for b in candidates if distances[b] <= nearest+.5*self.tour.spacing]
        def score(block):
            point = self.tour.points[block]
            offset = (point[0]-position[0], point[1]-position[1])
            alignment = sum(offset[i]*self.heading[i] for i in (0,1))/max(1,math.hypot(*offset)*math.hypot(*self.heading))
            return distances[block]-.5*self.tour.spacing*alignment,block
        chosen = min(nearby,key=score)
        index = self.sweep_order.index(chosen)
        self.sweep_order = self.sweep_order[index:]+self.sweep_order[:index]
        if self.linear and self.corridor_plan and chosen in self.corridor_plan:
            index=self.corridor_plan.index(chosen)
            self.corridor_plan=self.corridor_plan[index:]+self.corridor_plan[:index]

    def next_block(self, position):
        """Next pending point of the stable circuit; blocked points wait without resetting it."""
        candidates = self.remaining-set(self.deferred)
        if not candidates:
            return None
        if not self.linear and self.tour.corridor_mode and getattr(self.tour.collision, 'name', None) in self.NEAREST_FIRST_MAPS:
            distances = self.tour.distances(position)
            reachable = [block for block in candidates if block in distances]
            return min(reachable, key=lambda block: (distances[block], block)) if reachable else None
        if self.tour.corridor_mode or self.linear:
            # Mazes (sewers, ant hills): one planned walk through every pending waypoint, kept after
            # fights. Taking the nearest one each time left points behind and went back and forth
            # for them; the old fixed circuit ignored walking distances.
            distances = self.tour.distances(position)
            reachable = [block for block in candidates if block in distances]
            if not reachable:
                return None
            nearest = min(distances[block] for block in reachable)
            plan = [block for block in getattr(self, 'corridor_plan', []) if block in candidates and block in distances]
            if not plan:
                plan = self.tour.plan_order(position, reachable)
            self.corridor_plan = plan
            return plan[0] if plan else None
        ordered = next((block for block in self.sweep_order if block in candidates), None)
        if ordered is not None:
            return ordered
        distances = self.tour.distances(position)
        reachable = [block for block in candidates if block in distances]
        if not reachable:
            return None
        nearest = min(distances[block] for block in reachable)
        reachable = [block for block in reachable if distances[block] <= nearest+.35*self.tour.spacing]
        heading = math.hypot(*self.heading) or 1
        beside = self.tour.graph[self.tour.block_near(position)]

        def cost(block):
            point = self.tour.points[block]
            offset = [point[i]-position[i] for i in (0, 1)]
            alignment = sum(offset[i]*self.heading[i] for i in (0, 1))/((math.hypot(*offset) or 1)*heading)
            spacing = self.tour.spacing
            done = self.tour.done_around(block, self.remaining)
            # Sweep forwards through adjacent fresh ground. Large "leftover" rewards used to
            # pull the character backwards after almost every waypoint, fragmenting the circuit.
            value = distances[block]-.65*spacing*alignment
            if block in beside and done:
                value -= .15*spacing
            if distances[block] > 2.5*spacing:
                # Choosing among far waypoints: open ground first, the ones by walls at the end.
                # Waypoints right beside are taken on the way, so nothing is left behind for a loop.
                value += .15*spacing*self.tour.edge_penalty(block)
            return (value, block)
        return min(reachable, key=cost)

    FAILED_EDGE_SECONDS = 2

    STUCK_FAILURES = 3  # refused steps in a row from one cell: what lies that way is unreachable

    def failed(self, origin, destination, now):
        if origin is None:
            return
        self.failed_edges[(tuple(origin), tuple(destination))] = now+self.FAILED_EDGE_SECONDS
        streak = self.fail_streak
        self.fail_streak = (tuple(origin), streak[1]+1 if streak[0] == tuple(origin) else 1)
        if self.fail_streak[1] >= self.STUCK_FAILURES and self.tour is not None:
            self.give_up_around(destination)
            self.fail_streak = (None, 0)

    def give_up_around(self, cell):
        """The server keeps refusing the way (its map differs from ours there): the waypoint aimed
        at and the ones next to the refused cell are left out until the next cycle."""
        dropped = {block for block, point in self.tour.points.items()
                   if block in self.remaining and math.dist(point, cell) <= self.tour.spacing}
        if self.goal_block is not None:
            dropped.add(self.goal_block)
        for block in dropped:
            self.remaining.discard(block)
            self.unreachable.add(block)
        self.goal = self.goal_block = None
        self.route_cache_key = self.route_cache = None

    def plan(self, position, now, speed, collision=None):
        if now < self.retry_at:
            return None
        if collision is not None and (self.tour is None or collision is not self.tour.collision):
            self.switch_map(collision, position)
            self.focus_suppressed = None
            self.focus_suppressed_until = 0
        if self.tour is not None:
            if getattr(self, 'cycle_started_at', None) is None:
                self.cycle_started_at = now
            elif now-self.cycle_started_at >= self.CYCLE_KEEP:
                self.new_cycle(position)  # 30 minutes on this map: its coverage starts over
                self.cycle_started_at = now
        self.reached(position,now=now)
        if self.focus is not None and max(abs(position[i]-self.focus[i]) for i in (0, 1)) <= 5:
            self.focus_reached = tuple(self.focus)
            self.focus_history.append(tuple(self.focus))
            self.focus_suppressed = None
            self.focus_suppressed_until = 0
            self.focus = None
            self.focus_key = self.focus_block = None
            self.goal = self.goal_block = None
            self.route_cache_key = self.route_cache = None
            self.resume_forward(position)
            self.retry_at=now+.05
            return None
        self.failed_edges = {edge: until for edge, until in self.failed_edges.items() if until > now}
        route = None
        if (self.last_plan_position is not None and now-self.last_plan_at > 2
            and math.dist(position, self.last_plan_position) > 12):
            # Combat or a portal displaced us: rejoin nearby without claiming the old goal
            # was explored. It stays pending for the later part of this same circuit.
            if self.tour is not None:
                self.mark_seen(position)
                self.resume_forward(position)
            self.goal = self.goal_block = None
        self.last_plan_position, self.last_plan_at = tuple(position), now
        if self.goal is not None:
            distance = math.dist(position, self.goal)
            if self.goal_distance is None or distance < self.goal_distance-1:
                self.goal_at, self.goal_distance = now, distance
            elif self.focus is not None and now-self.goal_at > self.GOAL_TIMEOUT:
                self.focus_suppressed, self.focus_suppressed_until = tuple(self.focus), now+self.FOCUS_RETRY_DELAY
                self.focus = None
                self.focus_key = self.focus_block = None
                self.goal = self.goal_block = None
                self.route_cache_key = self.route_cache = None
        if collision is not None:
            self.deferred = {block: until for block, until in self.deferred.items() if until > now}
            if self.tour.points and self.remaining and not (self.remaining-set(self.deferred)) and not self.retried:
                self.deferred.clear()  # points put aside get one more try before the cycle closes
                self.retried = True
            if self.tour.points and (not (self.remaining-set(self.deferred))
                                     or self.coverage_target < 1 and self.tour.coverage(self.done) >= self.coverage_target):
                self.new_cycle(position)
                self.retried = False
            if self.focus is not None:
                destination=tuple(self.focus)
                if self.goal != destination or self.goal_block is not None:
                    self.goal=destination
                    self.goal_block=None
                    self.goal_at=now
                    self.goal_distance=math.dist(position,destination)
                    self.route_cache_key=self.route_cache=None
            elif self.search_destination is not None:
                self.goal, self.goal_at = tuple(self.search_destination), now
            elif self.tour.points:
                stale = self.goal is not None and now-self.goal_at > self.GOAL_TIMEOUT
                if stale and self.goal_block is not None:
                    self.deferred[self.goal_block] = now+60
                    if self.focus is not None:
                        self.focus_reached, self.focus = tuple(self.focus), None
                        self.focus_key = self.focus_block = None
                focused = self.focus is not None and self.goal_block is not None and self.goal_block == getattr(self, 'focus_block', None)
                if (self.goal is None or (self.goal_block not in self.remaining and not focused) or stale
                        or self.focus is not None and not focused):
                    block = self.next_block(position)
                    self.goal = self.goal_block = None
                    if block is not None:
                        self.goal_block, self.goal = block, self.tour.points[block]
                        self.goal_at, self.goal_distance = now, math.dist(position, self.goal)
            if self.goal is not None:
                self.heading = tuple(self.goal[i]-position[i] for i in (0, 1))
                if self.heading == (0, 0):
                    self.heading = self.rng.choice(self.DIRECTIONS)
                cache_key = (self.cycle_number, self.goal, self.search_destination is None)
                cached = (cache_key == self.route_cache_key and self.route_cache and tuple(position) in self.route_cache
                          and (tuple(position) != tuple(self.route_cache[-1]) or tuple(self.route_cache[-1]) == tuple(self.goal)))
                portal = None
                if not cached and self.goal_block is not None and self.search_destination is None:
                    portal = self.tour.portal_on_way(position, self.goal_block)
                if cached:
                    route = self.route_cache[self.route_cache.index(tuple(position)):]
                elif portal is not None and tuple(portal) != tuple(position):
                    # The waypoint is on the other side of an inner portal: walk onto the portal.
                    route = self.route(collision, position, portal, exact=True, max_nodes=self.ROUTE_NODES*4,
                                            greed=self.ROUTE_GREED, wall_cost=self.wall_cost())
                else:
                    route = self.route(collision, position, self.goal, exact=self.search_destination is None,
                                            max_nodes=self.ROUTE_NODES, greed=self.ROUTE_GREED, wall_cost=self.wall_cost())
                    if route is None and self.focus is not None and self.goal == tuple(self.focus):
                        # The @showmobs spot can be far across the map: search as wide as the scan did
                        # (12000 nodes) before giving it up.
                        route = self.route(collision, position, self.goal, exact=True, max_nodes=self.FOCUS_ROUTE_NODES,
                                                greed=self.ROUTE_GREED, wall_cost=self.wall_cost())
                    if route is None and self.search_destination is None:
                        # Narrow corridors cost more next to walls and spread the search: one bigger
                        # search (~0.1 s, kept in the route cache) finds the real way around. The
                        # partial fallback below heads for the cell closest in a straight line, which
                        # may be a dead end facing the waypoint: in and out of it, over and over.
                        route = self.route(collision, position, self.goal, exact=True, max_nodes=self.ROUTE_NODES*5,
                                                greed=self.ROUTE_GREED, wall_cost=self.wall_cost())
                    if route is None and self.search_destination is None:
                        # Every search stays bounded so the relay never stalls on a big map: a far
                        # goal behind a detour is approached through a cell a few blocks along the
                        # block path, then by the closest point the search reached.
                        stone = self.tour.stepping_stone(position, self.goal_block) if self.goal_block else None
                        if stone is not None and tuple(stone) != tuple(position):
                            route = self.route(collision, position, stone, exact=True, max_nodes=self.ROUTE_NODES,
                                                    greed=self.ROUTE_GREED, partial=True, wall_cost=self.wall_cost())
                        if not route or len(route) < 2:
                            route = self.route(collision, position, self.goal, exact=True, max_nodes=self.ROUTE_NODES,
                                                    greed=self.ROUTE_GREED, partial=True, wall_cost=self.wall_cost())
                        if route and len(route) > 1 and tuple(route[-1]) != tuple(self.goal):
                            # The same partial end twice for one waypoint: a dead end, the waypoint waits.
                            ends = self.partial_ends.setdefault(self.goal, set())
                            if tuple(route[-1]) in ends:
                                route = None
                            else:
                                ends.add(tuple(route[-1]))
                if (route is not None and len(route) < 2 and self.focus is not None and self.goal == tuple(self.focus)
                        and tuple(position) != tuple(self.goal)):
                    route = None  # already at the closest reachable cell to the @showmobs spot: no way there
                self.route_cache_key, self.route_cache = cache_key, route
                if route and len(route) > 1:
                    self.heading = tuple(route[1][i]-position[i] for i in (0, 1))
                elif route is None:
                    if self.goal_block is not None:
                        self.deferred[self.goal_block] = now+60
                    elif self.focus is not None and self.goal == tuple(self.focus):
                        # No way to the @showmobs spot: put it aside and go on patrolling. Re-taking it on
                        # every plan restarted its timeout and left the character standing still
                        # (stall breaker every ~2 s, ra_fild03 2026-11-06).
                        self.focus_suppressed, self.focus_suppressed_until = tuple(self.focus), now+self.FOCUS_RETRY_DELAY
                        self.focus = None
                        self.focus_key = self.focus_block = None
                    self.goal = self.goal_block = None
                elif self.goal_block is not None:  # standing on the waypoint
                    if self.focus is not None and self.goal_block == getattr(self, 'focus_block', None):
                        self.focus_reached, self.focus = tuple(self.focus), None
                        self.focus_key = self.focus_block = None
                    self.remaining.discard(self.goal_block)
                    self.done.add(self.goal_block)
                    self.goal = self.goal_block = None
                    self.retry_at = now+.05
                    return None

        if collision is not None and self.goal is not None and route and len(route) > 1:
            # Follow the chosen route; local novelty must not cause U-turns.
            index = 1
            for candidate in range(2, min(24, len(route))):
                if collision.segment(position, route[candidate], max_steps=self.max_step, wall_margin=min(3, collision.clearance(route[1]))):
                    index = candidate
            # A step that just failed is never sent again: a shorter one on the same route is tried,
            # and if every one failed the waypoint waits a moment so another one is taken (the old
            # way re-chose the same waypoint and stood still until the failure expired).
            while index > 1 and (tuple(position), tuple(route[index])) in self.failed_edges:
                index -= 1
            destination = tuple(route[index])
            if (tuple(position), destination) in self.failed_edges and self.goal_block is not None:
                self.deferred[self.goal_block] = now+15
                self.goal = self.goal_block = None
                self.route_cache_key = self.route_cache = None
                self.retry_at = now+.05
                return None
            if (tuple(position), destination) not in self.failed_edges:
                seconds = max(50, min(speed, 2000))/1000
                dx, dy = (abs(destination[i]-position[i]) for i in (0, 1))
                duration = (max(dx, dy)+.4*min(dx, dy))*seconds
                self.heading = tuple(destination[i]-position[i] for i in (0, 1))
                sectors = self.sectors_on_segment(position, destination)
                return {'kind': 'move', 'purpose': 'patrol', 'target_id': None,
                        'origin': list(position), 'destination': list(destination),
                        'seconds_per_step': seconds*(1+.4*min(dx, dy)/max(dx, dy)), 'wait_seconds': duration,
                        'collision_route': True, 'patrol_heading': list(self.heading),
                        'new_sectors_on_path': sum(self.visits[sector] == 0 for sector in sectors)}
            self.goal = None
        if collision is not None and self.tour.points:
            self.retry_at = now+.25
            return None  # keep the cycle; never switch to random movement
        options = []
        for order, direction in enumerate(self.DIRECTIONS):
            preferred_length = self.rng.randint(max(1, self.max_step//2), self.max_step)
            for length in range(preferred_length, 0, -1):
                dest = tuple(position[i]+length*direction[i] for i in (0, 1))
                if not all(1 <= n <= 1022 for n in dest):
                    continue
                # Avoid shorter commands into the same recently unsuccessful ray.
                blocked = any(a == tuple(position) and
                              all((b[i]-a[i])*direction[i] >= 0 for i in (0, 1)) and
                              (b[0]-a[0])*direction[1] == (b[1]-a[1])*direction[0]
                              for a, b in self.failed_edges)
                if blocked or (collision is not None and not collision.segment(position, dest, max_steps=self.max_step)):
                    continue
                sectors = self.sectors_on_segment(position, dest)
                traversed = sectors[1:] or sectors
                new = sum(self.visits[sector] == 0 for sector in traversed)
                revisits = sum(math.log1p(self.visits[sector]) for sector in traversed)/len(traversed)
                recent = sum(sector in self.recent_sectors for sector in traversed)/len(traversed)
                dot = sum(direction[i]*self.heading[i] for i in (0, 1))
                alignment = dot/(math.hypot(*direction)*math.hypot(*self.heading))
                repeated_line = direction == self.last_direction and self.straight_steps >= 2
                score = (6*new/len(traversed)+.75*min(new, 2)-2*revisits-2*recent
                         +2*alignment-1.5*repeated_line+self.rng.uniform(-1.2, 1.2))
                if collision is not None:
                    margin = min(dest[0], dest[1], collision.width-2-dest[0], collision.height-2-dest[1])
                    score -= max(0, 6-margin)*.7
                options.append({'score': score, 'destination': dest, 'direction': direction,
                                'forward': dot > 0, 'new': new})
                break
        if not options:
            self.retry_at = now+2
            return None
        forward_new = [option for option in options if option['forward'] and option['new']]
        any_new = [option for option in options if option['new']]
        forward = [option for option in options if option['forward']]
        pool = options
        chosen = max(pool, key=lambda option: option['score'])
        destination = chosen['destination']
        if not chosen['forward'] or self.escape_next:
            self.heading = chosen['direction']
        self.escape_next = False
        seconds = max(50, min(speed, 2000))/1000
        if destination[0] != position[0] and destination[1] != position[1]:
            seconds *= 1.4
        length = max(abs(destination[i]-position[i]) for i in (0, 1))
        return {'kind': 'move', 'purpose': 'patrol', 'target_id': None,
                'origin': list(position), 'destination': list(destination),
                'seconds_per_step': seconds, 'wait_seconds': length*seconds,
                'collision_route': collision is not None,
                'patrol_heading': list(self.heading), 'new_sectors_on_path': chosen['new']}


    def snapshot(self):
        points = self.tour.points if self.tour is not None else {}
        return {'visited_sectors': len(self.visits), 'completed_steps': self.steps,
                'temporarily_failed_segments': len(self.failed_edges), 'max_step_cells': self.max_step,
                'general_heading': list(self.heading), 'loop_escapes': self.loop_escapes,
                'cycle': self.cycle_number, 'cycle_sectors_total': len(points),
                'cycle_mode': ('corredores: completar ramificacao e retornar' if self.tour is not None and self.tour.corridor_mode
                               else 'circuito linear continuo por distancia caminhavel'),
                'cycle_sectors_explored': len(self.done), 'cycle_sectors_visited': len(self.done),
                'cycle_sectors_remaining': len(self.remaining),
                'goal': list(self.goal) if self.goal is not None else None}

    def coverage(self):
        points = self.tour.points if self.tour is not None else {}
        return {'spacing': SPACING, 'cycle': self.cycle_number,
                'waypoints': {','.join(map(str, b)): list(p) for b, p in sorted(points.items())},
                'done': sorted(map(list, self.done)), 'remaining': sorted(map(list, self.remaining))}
