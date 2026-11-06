"""Cells explicitly reported as skill units; never infer a square from cast range.

Exception: area spells whose server sends a single DUMMYSKILL unit (0x86) for the whole
effect. The unit type alone is shared by several spells, so the area is drawn only when
the unit's caster announced that spell on the ground (0x0117 / 0x013E) right before, at
a compatible cell, and only while the received unit exists.
"""

LAND_PROTECTOR = 0x9d  # Ragnarok UNT_LANDPROTECTOR, not the learned skill ID
DUMMYSKILL = 0x86  # rAthena UNT_DUMMYSKILL, shared by the spells below
GRAY_STYLE = {'fill': '#808080', 'outline': '#303030', 'opacity': 1.0, 'outline_width': 1}
# skill_id: (centre, radius(level), seconds after the cast, max distance unit<->cast cell)
# centre 'cast' = one area around the cast cell (unit Layout); 'unit' = area around each
# received unit (unit Range, e.g. every meteor). rAthena db/pre-re/skill_db.yml.
AREA_SKILLS = {
    516: ('cast', lambda lv: 3, 2.0, 3),                    # GS_DESPERADO: self-centred unit layout 3
    83: ('unit', lambda lv: 3, 12.0, 4),                      # WZ_METEOR, Range 3 (7x7 per meteor)
    89: ('cast', lambda lv: 4, 3.0, 4),                       # WZ_STORMGUST, Layout 4 (9x9)
    85: ('cast', lambda lv: 7 if lv >= 11 else 5, 3.0, 7),    # WZ_VERMILION, Layout 5 (11x11)
    21: ('cast', lambda lv: 3 if lv >= 11 else 2, 3.0, 3),    # MG_THUNDERSTORM, Layout 2 (5x5)
    91: ('cast', lambda lv: 2, 3.0, 2),                       # WZ_HEAVENDRIVE, Layout 2 (5x5)
}


class GroundCells:
    MAX_UNITS = 8192

    def __init__(self):
        self.map = None
        self.units = {}
        self.overflow = False
        self.casts = {}
        self.requests = {}
        self.ground_skills = {}

    def reset(self, map_name=None):
        self.map = map_name
        self.units.clear()
        self.overflow = False
        self.casts = {}
        self.requests = {}
        self.ground_skills = {}

    def note_ground_skill(self, event, now, delay=0.0):
        skill_id, position = event.get('skill_id'), event.get('position')
        if skill_id not in AREA_SKILLS or not position or len(position) != 2:
            return
        if any(type(v) is not int or not 0 <= v < 1024 for v in position):
            return
        recent = [c for c in self.ground_skills.get(event.get('source_id'), [])
                  if now - c['at'] <= AREA_SKILLS[c['skill_id']][2]]
        recent.append(dict(skill_id=skill_id, level=event.get('level') or 1, position=list(position), at=now+delay))
        self.ground_skills[event.get('source_id')] = recent[-8:]

    def area_for(self, source_id, position, now):
        """Area of a DUMMYSKILL unit, from the newest compatible ground spell of the same caster."""
        for cast in reversed(self.ground_skills.get(source_id, [])):
            centre, radius, window, spread = AREA_SKILLS[cast['skill_id']]
            if not -1.0 <= now - cast['at'] <= window:
                continue
            cx, cy = cast['position']
            if max(abs(position[0]-cx), abs(position[1]-cy)) > spread:
                continue
            x, y = (cx, cy) if centre == 'cast' else position
            return [x, y, radius(cast['level'])]
        return None

    def request_cast(self, skill_id, position, now):
        # A request can be rejected or ignored: record it, but never paint it as a cast.
        self.casts.clear()
        if len(position)==2 and all(type(v) is int and 0<=v<1024 for v in position):
            self.requests={skill_id:dict(skill_id=skill_id,position=list(position),expires=now+2)}

    def preview_cast(self, skill_id, position, now, duration=1.0):
        if len(position)==2 and all(type(v) is int and 0<=v<1024 for v in position):
            self.casts[skill_id] = dict(skill_id=skill_id, position=list(position), expires=now+min(60,max(.1,duration)))

    def observe(self, events, own_id=None, now=None):
        import time
        now = time.monotonic() if now is None else now
        for event in events:
            kind = event['kind']
            if kind in ('map_change', 'map_transfer'):
                self.reset(event.get('map'))
            elif kind == 'ground_skill':
                self.note_ground_skill(event, now)
                if own_id is not None and event.get('source_id')==own_id:
                    self.casts.pop(event.get('skill_id'),None);self.requests.pop(event.get('skill_id'),None)
            elif kind == 'skill_cast' and event.get('skill_id') in AREA_SKILLS and event.get('source_id') != own_id:
                # Backup for 0x0117: the cast bar ends (duration) before the spell lands.
                self.note_ground_skill(event, now, max(0, event.get('duration_ms') or 0)/1000)
            elif kind == 'skill_cast' and event.get('source_id') == own_id and own_id is not None:
                if event.get('skill_id') in AREA_SKILLS:
                    self.note_ground_skill(event, now, max(0, event.get('duration_ms') or 0)/1000)
                if event.get('position') is not None:
                    self.requests.pop(event['skill_id'],None)
                    duration=event.get('duration_ms',0)/1000
                    if duration>0:self.preview_cast(event['skill_id'],event['position'],now,duration)
                    else:self.casts.pop(event['skill_id'],None)
            elif kind == 'skill_failed':
                self.casts.pop(event.get('skill_id'),None);self.requests.pop(event.get('skill_id'),None)
                if own_id is not None:self.ground_skills[own_id]=[c for c in self.ground_skills.get(own_id,[]) if c['skill_id']!=event.get('skill_id')]
            elif kind == 'skill_cast_cancel':
                self.ground_skills.pop(event.get('source_id'),None)
                if own_id is not None and event.get('source_id')==own_id:self.casts.clear();self.requests.clear()
            elif kind == 'ground_effect_removed':
                self.units.pop(event['effect_id'], None)
            elif kind == 'ground_effect':
                if own_id is not None and event.get('source_id') == own_id:
                    self.casts.clear();self.requests.clear()
                identity = event['effect_id']
                unit_type = event.get('effect_type', -1)
                if type(unit_type) is not int or not 0x7e <= unit_type <= 0xff or not event.get('visible'):
                    self.units.pop(identity, None)
                    continue
                position = event.get('position')
                if not position or len(position) != 2 or any(type(v) is not int or not 0 <= v < 1024 for v in position):
                    continue
                if identity not in self.units and len(self.units) >= self.MAX_UNITS:
                    self.overflow = True
                    continue
                previous = self.units.get(identity)
                area = previous.get('area') if previous and previous['position'] == list(position) else None
                if unit_type == DUMMYSKILL and area is None:
                    area = self.area_for(event.get('source_id'), position, now)
                self.units[identity] = dict(position=list(position), source_id=event.get('source_id'),
                                            effect_type=event['effect_type'])
                if area:
                    self.units[identity]['area'] = area
                    for cast in reversed(self.ground_skills.get(event.get('source_id'), [])):
                        if cast['skill_id'] in AREA_SKILLS and abs(now-cast['at'])<=AREA_SKILLS[cast['skill_id']][2]:
                            self.units[identity]['skill_id']=cast['skill_id'];break

    def snapshot(self):
        # Overlapping units are retained individually; removing one must not clear the other's cell.
        cells = set()
        for unit in self.units.values():
            if 'area' in unit:
                x, y, r = unit['area']
                cells.update((i, j) for i in range(max(0, x-r), min(1023, x+r)+1)
                             for j in range(max(0, y-r), min(1023, y+r)+1))
            else:
                cells.add(tuple(unit['position']))
        cells = sorted(cells)
        return dict(effects=[dict(effect_id=i, **u) for i,u in self.units.items()], casts=list(self.casts.values()), requests=list(self.requests.values()), map=self.map, cells=[list(cell) for cell in cells], units=len(self.units),
                    unit_type=LAND_PROTECTOR, style=dict(GRAY_STYLE), incomplete=self.overflow,
                    evidence='unidades de terreno recebidas; area so para magias em area confirmadas pelo pacote da magia')
