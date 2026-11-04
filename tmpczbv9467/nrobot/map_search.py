"""REDE-52: search memory from received sightings; never authorizes attacks."""
import math


class MapSearch:
    def __init__(self):
        self.epoch = None
        self.searched = {}
        self.goal = None
        self.summary = {}
        self.next_update = 0

    def plan(self, inventory, player, species, now, collision):
        if self.epoch != inventory.epoch:
            self.epoch = inventory.epoch
            self.searched.clear()
            self.summary = {}
            self.goal = None
            self.next_update = 0
        if player is None or collision is None:
            self.goal = None
            return None
        if self.goal is not None:
            current = inventory.entities.get(self.goal['entity_id'])
            if current is None or current.get('removal_reason') == 1 or current.get('hp') == 0:
                self.goal = None
                self.next_update = 0
        if now < self.next_update:
            return self.goal
        self.next_update = now+1
        self.searched = {key: until for key, until in self.searched.items() if until > now}
        candidates = []
        observed = visible = 0
        for entity in inventory.entities.values():
            if entity['species_id'] not in species:
                continue
            observed += 1
            present = entity['present_last_observation']
            visible += int(present)
            if entity.get('removal_reason') == 1 or entity.get('hp') == 0:
                continue
            age = max(0, now-entity['last_seen'])
            if not present and age > 60:
                continue
            position = entity.get('destination') or entity['position']
            sector = (position[0]//4, position[1]//4)
            if math.dist(player, position) <= 6:
                self.searched[sector] = now+30
                continue
            if sector in self.searched or not collision.walkable(position):
                continue
            candidates.append({'entity_id': entity['entity_id'], 'position': list(position),
                               'visible': present, 'age_seconds': round(age, 2),
                               'distance': round(math.dist(player, position), 2)})
        candidates.sort(key=lambda e: (not e['visible'], e['distance'], e['age_seconds']))
        self.goal = None
        for candidate in candidates[:12]:
            route = collision.route(player, candidate['position'])
            if route:
                self.goal = candidate
                break
            position = candidate['position']
            self.searched[(position[0]//4, position[1]//4)] = now+30
        self.summary = {'received_species_entities': observed, 'present_entities': visible,
                        'search_locations': candidates[:30], 'goal': self.goal,
                        'scope': 'Somente entidades recebidas; locais antigos sao pistas, nao alvos confirmados.'}
        return self.goal
