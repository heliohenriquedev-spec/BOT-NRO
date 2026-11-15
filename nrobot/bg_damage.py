"""The 50 largest incoming BG hits, saved separately for each character."""
from datetime import datetime
import json
from pathlib import Path


def skill_names():
    """Join numeric IDs from the client's SKID table to the local NRO name catalog."""
    from .catalog import load
    try:
        codes = json.loads((Path(__file__).resolve().parents[1]/'data/recursos/habilidades_ids.json').read_text(encoding='utf-8'))
        catalog = (load() or {}).get('habilidades', {})
        return {int(identity): catalog.get(code, {}).get('nome') or code for identity, code in codes.items()}
    except (OSError, ValueError):
        return {}


class BgDamage:
    LIMIT = 50

    def __init__(self, path):
        self.path = Path(path)
        try:
            self.characters = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(self.characters, dict):
                self.characters = {}
        except (OSError, ValueError):
            self.characters = {}
        self.character = None
        self.map_name = ''
        self.bg_map = False
        self.own_team = None
        self.teams = {}
        self.names = {}

    def select(self, character):
        key = str(character) if character is not None else None
        if key != self.character:
            self.character = key
            self.map_name = ''
            self.bg_map = False
            self.own_team = None
            self.teams = {}
            self.names = {}

    @property
    def active(self):
        return bool(self.map_name.lower().startswith('bat_')
                    or self.bg_map and self.own_team and self.teams)

    def observe(self, events, own_id, character, name_of):
        self.select(character)
        if own_id is None or self.character is None:
            return
        rows = self.characters.setdefault(self.character, [])
        changed = False
        for event in events:
            kind = event['kind']
            if kind in ('map_change', 'map_transfer'):
                self.map_name = str(event.get('map') or '')
                self.bg_map = False
                self.own_team = None
                self.teams.clear()
                self.names.clear()
            elif kind == 'map_type':
                # Same map signal used by the RCX BG affiliation tracker.
                self.bg_map = True
            elif kind == 'bg_team':
                identity, team = event.get('entity_id'), event.get('team')
                if identity == own_id:
                    self.own_team = team
                elif team:
                    self.teams[identity] = team
                else:
                    self.teams.pop(identity, None)
            if kind in ('name', 'bg_team') and event.get('name'):
                self.names[event.get('entity_id')] = event['name']
                for row in rows:
                    if row['source_id'] == event.get('entity_id') and row.get('source_name') != event['name']:
                        row['source_name'] = event['name']
                        changed = True
            elif (self.active and kind in ('skill_damage', 'normal_attack')
                  and event.get('target_id') == own_id and event.get('source_id') != own_id):
                damage = event.get('damage', event.get('damage_raw', 0))
                # Damage is the total reported by the packet, already including its hit count.
                damage = max(0, damage) + max(0, event.get('damage_secondary', 0))
                if damage <= 0 or (len(rows) >= self.LIMIT and damage <= rows[-1]['damage']):
                    continue
                rows.append(dict(damage=damage, skill_id=event.get('skill_id', 0),
                                 level=event.get('level'), source_id=event.get('source_id'),
                                 source_name=self.names.get(event.get('source_id')) or name_of(event.get('source_id')) or '',
                                 map=self.map_name, at=datetime.now().isoformat(timespec='seconds')))
                rows.sort(key=lambda row: row['damage'], reverse=True)
                del rows[self.LIMIT:]
                changed = True
        if changed:
            self.save()

    def save(self):
        try:
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps(self.characters, ensure_ascii=False), encoding='utf-8')
            temp.replace(self.path)
        except OSError:
            pass  # A display log must never interrupt the game connection.

    def snapshot(self, character):
        self.select(character)
        return {'active': self.active, 'rows': [dict(row) for row in self.characters.get(self.character, [])]}
