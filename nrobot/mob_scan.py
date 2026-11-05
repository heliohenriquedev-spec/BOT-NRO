"""@showmobs during the quest hunt: where the monsters still missing are, and the densest spot.

The server answers @showmobs <id> with one minimap mark (0144) per monster of that kind on the map.
From time to time, while the character patrols without a target, the bot asks for every monster the
quest still needs on that map, gathers the marks and walks to where most of them are together.

Timing: right on arrival on the hunting map, then every 60 s, fighting or not; the spot found is
walked to when the patrol has no target. Monsters respawn and wander: a snapshot older than a
minute no longer says where they are, and one query per monster kind every 4 s keeps the chat calm."""
import math

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

    def __init__(self):
        self.reset()
        self.silent = 0
        self.suspended = False

    def reset(self):
        self.map = None
        self.queue = []
        self.marks = []
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
        if self.suspended or not species:
            return False
        if map_name != self.map:
            self.reset()
            self.map = map_name
        if self.queue or self.round_open:
            return False
        due = idle and now-self.round_at >= self.INTERVAL
        if not due and not (early and self.seconds_to_next(now) > self.EARLY_GUARD):
            return False
        self.queue, self.marks, self.round_at, self.round_open = list(species), [], now, True
        return True

    def next_command(self, now):
        if self.queue and now-self.sent_at >= self.GAP:
            return self.queue[0]
        return None

    def sent(self, species, now):
        if self.queue and self.queue[0] == species:
            self.queue.pop(0)
        self.sent_at = now

    def observe(self, events, now):
        if now-self.sent_at > self.LISTEN:
            return
        for event in events:
            if event['kind'] == 'viewpoint' and event.get('mark_type') == 1 and event.get('position'):
                self.marks.append(tuple(event['position']))

    def finish(self, own, now, walkable=None):
        """After the last answer: the densest group becomes the goal. Returns it (or None)."""
        if not self.round_open or self.queue or now-self.sent_at <= self.LISTEN:
            return None
        self.round_open = False
        marks = [m for m in self.marks if walkable is None or walkable(m)]
        self.silent = 0 if self.marks else self.silent+1
        if self.silent >= self.SILENT_ROUNDS:
            self.suspended = True
        if not marks or own is None:
            return None
        def group(mark):
            return [m for m in marks if math.dist(m, mark) <= self.RADIUS]
        best = max(marks, key=lambda m: (len(group(m)), -math.dist(m, own)))
        members = group(best)
        if len(members) < self.MIN_GROUP:
            return None
        centre = (sum(m[0] for m in members)/len(members), sum(m[1] for m in members)/len(members))
        self.goal = list(min(members, key=lambda m: math.dist(m, centre)))  # a real monster cell: walkable
        self.goal_until = now+self.GOAL_TIME
        return {'position': self.goal, 'monsters': len(members), 'total': len(marks)}

    def current_goal(self, own, now):
        if self.goal is None:
            return None
        if now > self.goal_until or (own is not None and chebyshev(own, self.goal) <= self.ARRIVED):
            self.goal = None
        return self.goal
