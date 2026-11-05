"""REDE-33: decoded map sightings for diagnostics, never used to authorize attacks."""
from __future__ import annotations


class EntityInventory:
    def __init__(self, species_names=None):
        self.names = species_names or {}
        self.entities = {}
        self.map_name = None
        self.epoch = 0

    def reset(self, map_name=None):
        self.entities.clear()
        self.map_name = map_name
        self.epoch += 1

    def observe(self, events, now):
        for event in events:
            kind = event['kind']
            if kind in ('map_change', 'map_transfer'):
                self.reset(event.get('map'))
                continue
            identity = event.get('entity_id')
            if kind == 'appearance':
                old = self.entities.get(identity, {})
                if old.get('species_id') != event['species_id'] or not old.get('present_last_observation', True):
                    old = {}
                self.entities[identity] = {
                    'entity_id': identity, 'species_id': event['species_id'],
                    'correlated_name': self.names.get(str(event['species_id'])),
                    'object_type_raw': event.get('object_type'),
                    'owner_id': event.get('owner_id', old.get('owner_id')),
                    'summoned': event.get('summoned', old.get('summoned', False)),
                    'walk_speed_ms': event.get('walk_speed_ms'),
                    'position': event['position'], 'destination': event.get('destination'),
                    'present_last_observation': True, 'removal_reason': None,
                    'body_state': event.get('body_state', 0), 'dead': bool(event.get('dead')),
                    'last_seen': now, 'movements': old.get('movements', 0)}
                if len(self.entities) > 5000:
                    oldest = min(self.entities, key=lambda i: self.entities[i]['last_seen'])
                    del self.entities[oldest]
            elif identity in self.entities:
                entity = self.entities[identity]
                if kind in ('move', 'position'):
                    entity.update(position=event['position'], destination=event.get('destination'),
                                  last_seen=now, movements=entity['movements']+int(kind == 'move'))
                elif kind == 'option_change' and 'body_state' in event:
                    entity['body_state'] = event['body_state']
                elif kind == 'name':
                    for key in ('name', 'hp', 'max_hp'):
                        if key in event:
                            entity[key] = event[key]
                elif kind == 'remove':
                    entity.update(present_last_observation=False, removal_reason=event.get('reason'),
                                  removed_at=now)
                    if event.get('reason') == 1:
                        entity['dead'] = True  # a player's body stays on the ground
                elif kind == 'resurrection':
                    entity.update(dead=False, present_last_observation=True)

    def snapshot(self, now):
        from .monster_origin import temporary_reason
        return {'map': self.map_name, 'map_epoch': self.epoch,
                'note': 'Aparições recebidas pelo cliente; não é uma lista completa do mapa. Dados antigos não autorizam ataques. Remoção não prova morte.',
                'entities': [{**{k: v for k, v in e.items() if k not in ('last_seen', 'removed_at')},
                              'origin_note': temporary_reason(e),
                              'position_age_seconds': round(max(0, now-e['last_seen']), 3)}
                             for e in self.entities.values()]}
