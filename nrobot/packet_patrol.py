"""REDE-40: novelty-biased exploration with a persistent travel heading.

REDE-75: with collision data the map is covered through open-ground waypoints (see
patrol_tour.py): the next goal is the unvisited waypoint that is closest by walking,
preferring the current heading and waypoints whose neighbours are already done (so no
stragglers are left behind for a long walk back). Corners, wall edges and dead-end nooks
are never goals. Coverage is remembered per map; a new cycle starts once every waypoint
was passed."""
from collections import Counter, deque
import math
import random

from .patrol_tour import SPACING, PatrolTour


class PacketPatrol:
    DIRECTIONS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
    GOAL_TIMEOUT = 25  # seconds without getting closer before a waypoint is put aside
    ROUTE_NODES = 4000  # cell search budget per plan (~0.1 s); longer trips go by stepping stones
    ROUTE_GREED = 1.5
    MAP_FIELDS = ('tour', 'remaining', 'done', 'walked', 'cycle_number')

    def __init__(self, max_step=8, rng=None, *, spacing=SPACING, coverage=1.0, wall_margin=2, avoid_walls=False):
        if not 1 <= max_step <= 8:
            raise ValueError('Trecho de patrulha deve ter entre uma e oito células')
        self.max_step = max_step
        self.layout = dict(spacing=spacing, wall_margin=wall_margin, avoid_walls=avoid_walls)
        self.coverage_target = coverage  # share of the map's waypoints passed before a new cycle starts
        self.rng = rng if rng is not None else random.Random()
        self.reset()

    def wall_cost(self):
        """Walking next to a wall costs more, much more when walls are to be avoided."""
        return 6 if self.layout.get('avoid_walls') else 3

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
        self.last_sector = None
        self.heading = self.rng.choice(self.DIRECTIONS)
        self.goal = None
        self.goal_block = None
        self.search_destination = None
        self.goal_at = 0
        self.goal_distance = None
        self.last_plan_position = None
        self.last_plan_at = 0
        self.tour = None
        self.remaining = set()
        self.done = set()
        self.walked = set()  # 4x4 sectors walked this cycle: routes prefer fresh ground
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

    def reached(self, position, origin=None):
        if origin is not None and max(abs(position[i]-origin[i]) for i in (0, 1)) > 2*self.max_step+2:
            origin = None  # a jump (inner portal, teleport): nothing was walked in between
        for sector in self.sectors_on_segment(origin or position, position):
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

    def mark_seen(self, point):
        for block in self.tour.seen_from(point):
            if block in self.remaining:
                self.remaining.discard(block)
                self.done.add(block)

    def switch_map(self, collision, position):
        """Remember coverage per collision map so returning to a map resumes its cycle."""
        if self.tour is not None:
            self.map_memory[id(self.tour.collision)] = {f: getattr(self, f) for f in self.MAP_FIELDS}
        self.goal = self.goal_block = self.search_destination = None
        self.route_cache_key = self.route_cache = None
        self.deferred = {}
        self.failed_edges = {}
        saved = self.map_memory.get(id(collision))
        if saved is not None and saved['tour'].collision is collision and tuple(position) in saved['tour'].cells:
            for field, value in saved.items():
                setattr(self, field, value)
            return
        self.tour = PatrolTour(collision, position, **self.layout)
        self.cycle_number = 1
        self.done, self.walked = set(), set()
        self.remaining = set(self.tour.points)
        self.mark_seen(position)

    def new_cycle(self, position):
        self.cycle_number += 1
        self.unreachable.clear()
        self.remaining = set(self.tour.points)
        self.done.clear()
        self.walked.clear()
        self.deferred.clear()
        self.goal = self.goal_block = None
        self.mark_seen(position)
        if not self.remaining:  # tiny map: everything is in view from here
            self.remaining = set(self.tour.points)-set(self.tour.seen_from(position)) or set(self.tour.points)

    def next_block(self, position):
        """Closest unvisited waypoint by walking; ties favour the heading and leftovers."""
        candidates = self.remaining-set(self.deferred)
        if not candidates:
            return None
        distances = self.tour.distances(position)
        reachable = [block for block in candidates if block in distances]
        if not reachable:
            return None
        heading = math.hypot(*self.heading) or 1
        beside = self.tour.graph[self.tour.block_near(position)]

        def cost(block):
            point = self.tour.points[block]
            offset = [point[i]-position[i] for i in (0, 1)]
            alignment = sum(offset[i]*self.heading[i] for i in (0, 1))/((math.hypot(*offset) or 1)*heading)
            spacing = self.tour.spacing
            done = self.tour.done_around(block, self.remaining)
            value = distances[block]-.5*spacing*alignment-.3*spacing*done
            if not any(other in self.remaining for other in self.tour.graph[block]):
                # A straggler: everything around is done or wall. Left now, it would cost a walk back later.
                value -= .6*spacing
            if block in beside and done:
                # The next block of the sweep, touching ground already covered: keep going on.
                # A neighbour on fresh ground (e.g. through a gap) waits, so no side is left behind.
                value -= .4*spacing
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
        self.reached(position)
        self.failed_edges = {edge: until for edge, until in self.failed_edges.items() if until > now}
        route = None
        if (self.last_plan_position is not None and now-self.last_plan_at > 2
            and math.dist(position, self.last_plan_position) > 12):
            self.goal = None  # combat displaced us: do not retrace to the old waypoint
        self.last_plan_position, self.last_plan_at = tuple(position), now
        if self.goal is not None:
            distance = math.dist(position, self.goal)
            if self.goal_distance is None or distance < self.goal_distance-1:
                self.goal_at, self.goal_distance = now, distance
        if collision is not None:
            self.deferred = {block: until for block, until in self.deferred.items() if until > now}
            if self.tour.points and self.remaining and not (self.remaining-set(self.deferred)) and not self.retried:
                self.deferred.clear()  # points put aside get one more try before the cycle closes
                self.retried = True
            if self.tour.points and (not (self.remaining-set(self.deferred))
                                     or self.coverage_target < 1 and self.tour.coverage(self.done) >= self.coverage_target):
                self.new_cycle(position)
                self.retried = False
            if self.search_destination is not None:
                self.goal, self.goal_at = tuple(self.search_destination), now
            elif self.tour.points:
                stale = self.goal is not None and now-self.goal_at > self.GOAL_TIMEOUT
                if stale and self.goal_block is not None:
                    self.deferred[self.goal_block] = now+60
                if self.goal is None or self.goal_block not in self.remaining or stale:
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
                    route = collision.route(position, portal, exact=True, max_nodes=self.ROUTE_NODES*4,
                                            greed=self.ROUTE_GREED, wall_cost=self.wall_cost())
                else:
                    route = collision.route(position, self.goal, exact=self.search_destination is None,
                                            max_nodes=self.ROUTE_NODES, greed=self.ROUTE_GREED, wall_cost=self.wall_cost(),
                                            visited_sectors=self.walked if self.search_destination is None else frozenset())
                    if route is None and self.search_destination is None:
                        # Every search stays bounded so the relay never stalls on a big map: a far
                        # goal behind a detour is approached through a cell a few blocks along the
                        # block path, then by the closest point the search reached.
                        stone = self.tour.stepping_stone(position, self.goal_block) if self.goal_block else None
                        if stone is not None and tuple(stone) != tuple(position):
                            route = collision.route(position, stone, exact=True, max_nodes=self.ROUTE_NODES,
                                                    greed=self.ROUTE_GREED, partial=True, wall_cost=self.wall_cost())
                        if not route or len(route) < 2:
                            route = collision.route(position, self.goal, exact=True, max_nodes=self.ROUTE_NODES,
                                                    greed=self.ROUTE_GREED, partial=True, wall_cost=self.wall_cost())
                self.route_cache_key, self.route_cache = cache_key, route
                if route and len(route) > 1:
                    self.heading = tuple(route[1][i]-position[i] for i in (0, 1))
                elif route is None:
                    if self.goal_block is not None:
                        self.deferred[self.goal_block] = now+60
                    self.goal = self.goal_block = None
                elif self.goal_block is not None:  # standing on the waypoint
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
                'cycle_mode': 'pontos de passagem em chão aberto',
                'cycle_sectors_explored': len(self.done), 'cycle_sectors_visited': len(self.done),
                'cycle_sectors_remaining': len(self.remaining),
                'goal': list(self.goal) if self.goal is not None else None}

    def coverage(self):
        points = self.tour.points if self.tour is not None else {}
        return {'spacing': SPACING, 'cycle': self.cycle_number,
                'waypoints': {','.join(map(str, b)): list(p) for b, p in sorted(points.items())},
                'done': sorted(map(list, self.done)), 'remaining': sorted(map(list, self.remaining))}
