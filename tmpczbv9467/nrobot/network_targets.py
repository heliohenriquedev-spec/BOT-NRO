"""Registro para eventos já decodificados (REDE-03); não decodifica tráfego NRO."""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Entity:
    entity_id: int
    species_id: int
    x: int
    y: int
    seen_at: float
    kind: str
    alive: bool = True
    destination: tuple[int, int] | None = None
    walk_speed_ms: int | None = None
    # REDE-69: the server's own walk path and its start on the local clock.
    path: tuple | None = None
    walk_started: float | None = None
    motion_uncertain: bool = False

    def path_cells(self, moment):
        from .server_path import step_durations, cells_at
        durations = step_durations(self.path, self.walk_speed_ms)
        elapsed = moment-self.walk_started
        return [list(cell) for cell in cells_at(self.path, durations, elapsed)], elapsed >= sum(durations)

    def position_bounds(self, now):
        if self.path and self.walk_speed_ms is not None and self.walk_started is not None:
            cells, arrived = self.path_cells(now)
            return ([list(self.path[-1])], True) if arrived else (cells, False)
        start = [self.x, self.y]
        if self.destination is None:
            return [start], False
        if self.walk_speed_ms is not None and not self.motion_uncertain:
            dx, dy = abs(self.destination[0]-self.x), abs(self.destination[1]-self.y)
            duration = (max(dx, dy)+.4*min(dx, dy))*self.walk_speed_ms/1000+.15
            if now-self.seen_at >= duration:
                return [list(self.destination)], True
        return [start, list(self.destination)], False

    def combat_bounds(self, now):
        """REDE-52: estimated current/near-future cells, not the final destination."""
        if self.path and self.walk_speed_ms is not None and self.walk_started is not None:
            points, arrived = self.path_cells(now)
            for cell in self.path_cells(now+.1)[0]:
                if cell not in points:
                    points.append(cell)
            return points, True
        if self.destination is None or self.walk_speed_ms is None or self.motion_uncertain:
            return self.position_bounds(now)
        dx, dy = abs(self.destination[0]-self.x), abs(self.destination[1]-self.y)
        duration = (max(dx, dy)+.4*min(dx, dy))*self.walk_speed_ms/1000
        if duration <= 0:
            return [list(self.destination)], True
        points = []
        for moment in (now, now+.1):
            fraction = min(1, max(0, (moment-self.seen_at)/duration))
            point = [round(start+(end-start)*fraction) for start, end in zip((self.x, self.y), self.destination)]
            if point not in points:
                points.append(point)
        return points, True


# REDE-59: the server reuses the account id as the game id of a character, even while it is
# disguised/transformed into a monster sprite. Monsters and NPCs use ids from 110000000 up.
ACCOUNT_IDS = range(2_000_000, 100_000_000)


def is_player_id(entity_id: int) -> bool:
    return entity_id in ACCOUNT_IDS


class TargetRegistry:
    def __init__(self, ttl: float = 5.0):
        if ttl is not None and (not math.isfinite(ttl) or ttl <= 0):
            raise ValueError('TTL deve ser positivo e finito')
        self.ttl = ttl
        self.entities: dict[int, Entity] = {}
        self.target_id: int | None = None
        self.rejected_players: set[int] = set()

    def current(self, entity, now):
        return now >= entity.seen_at and (self.ttl is None or now-entity.seen_at <= self.ttl)

    def clear(self) -> None:
        """Chamar em troca de mapa, desconexão ou falha do decodificador."""
        self.entities.clear()
        self.target_id = None

    def update(self, entity: Entity) -> None:
        if entity.entity_id <= 0 or entity.species_id < 0 or not math.isfinite(entity.seen_at):
            raise ValueError('Identidade ou horário inválido')
        if not all(isinstance(v, int) and v >= 0 for v in (entity.x, entity.y)):
            raise ValueError('Coordenadas devem ser inteiros não negativos')
        if entity.kind == 'monster' and is_player_id(entity.entity_id):
            # A character with a monster sprite is never a monster target.
            self.rejected_players.add(entity.entity_id)
            self.remove(entity.entity_id)
            return
        old = self.entities.get(entity.entity_id)
        if old is None or entity.seen_at >= old.seen_at:
            self.entities[entity.entity_id] = entity

    def remove(self, entity_id: int) -> None:
        """Remoção não implica morte: a entidade pode ter saído da visão."""
        self.entities.pop(entity_id, None)
        if self.target_id == entity_id:
            self.target_id = None

    def choose(self, species: set[int], player: tuple[int, int], now: float,
               max_distance: float = 30) -> Entity | None:
        if not math.isfinite(now) or not math.isfinite(max_distance) or max_distance < 0:
            raise ValueError('Horário e distância inválidos')
        self.entities = {i: e for i, e in self.entities.items() if self.current(e, now)}
        candidates = {i: e for i, e in self.entities.items()
                      if e.alive and e.kind == 'monster' and e.species_id in species
                      and math.dist(e.position_bounds(now)[0][-1], player) <= max_distance}
        best = candidates.get(self.target_id)
        if best is None and candidates:
            best = min(candidates.values(), key=lambda e: (math.dist(e.position_bounds(now)[0][-1], player), e.entity_id))
        self.target_id = best.entity_id if best else None
        return best
