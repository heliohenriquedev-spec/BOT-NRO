"""Signs that a character on screen is a GM/staff, beyond @hide (handled by the presence guard).

- a staff tag in the name, guild, party or guild title ("[GM]", "ADM", "Staff"...);
- walking faster than any normal character (@speed): a few milliseconds per cell;
- a visual (weapon, shield, headgear) or a name mark listed in data/jogadores/gm_sinais.json,
  for the server's GM-only items, which the bot cannot know by itself.
"""
import json
import re
from pathlib import Path

FILE = Path(__file__).resolve().parents[1]/'data/jogadores/gm_sinais.json'
STAFF_NAME = re.compile(r'(?:^|[\[\(\{<\s\-_.|])(?:GM|ADM|ADMIN|STAFF|MOD|MODERADOR|SUPORTE)(?:$|[\]\)\}>\s\-_.|])', re.I)
FAST_WALK_MS = 40  # normal walking is 150 ms per cell; buffs and mounts stay far above this
TELEPORTS = 2  # teleports next to us within TELEPORT_WINDOW seconds
TELEPORT_WINDOW = 30
TELEPORT_RADIUS = 8


def staff_name(name, marks=()):
    if not name:
        return False
    return bool(STAFF_NAME.search(name)) or any(mark and mark.casefold() in name.casefold() for mark in marks)


def load_config(path=None):
    """{'visuais': [ids], 'marcas': [texts]} chosen by the player."""
    try:
        data = json.loads(Path(path or FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    return {'visuais': {int(i) for i in data.get('visuais', []) if str(i).isdigit()},
            'marcas': [str(m) for m in data.get('marcas', []) if str(m).strip()]}


class GmSigns:
    def __init__(self):
        self.teleports = {}  # player id -> times it teleported in next to us
        self.departed = {}  # player id -> time it left the view by teleport (remove reason 3)
        self.config = load_config()
        self.speeds = {}  # player id -> walk speed as sent (ms per cell)

    def observe(self, events, own_position, now):
        for e in events:
            identity = e.get('entity_id')
            if e['kind'] == 'remove' and e.get('reason') == 3:
                self.departed[identity] = now
            if e['kind'] == 'appearance' and e.get('speed_raw'):
                self.speeds[identity] = e['speed_raw']
            if e['kind'] == 'appearance' and e.get('position') and own_position:
                came = now-self.departed.get(identity, -1e9) <= TELEPORT_WINDOW
                close = max(abs(e['position'][i]-own_position[i]) for i in (0, 1)) <= TELEPORT_RADIUS
                if close and (came or e.get('spawned')):
                    times = [t for t in self.teleports.get(identity, []) if now-t <= TELEPORT_WINDOW]+[now]
                    self.teleports[identity] = times

    def reasons(self, row, entry, speed_ms, now):
        """Why this visible character looks like staff ([] when nothing points to it)."""
        found = []
        marks = self.config['marcas']
        if staff_name(row.get('name'), marks):
            found.append('nome de GM/staff')
        for field, label in (('guild', 'guilda'), ('party', 'grupo'), ('guild_title', 'cargo')):
            if staff_name((entry or {}).get(field), marks):
                found.append(label+' de GM/staff')
        if speed_ms is not None and 0 < speed_ms <= FAST_WALK_MS:
            found.append(f'velocidade anormal ({speed_ms} ms/celula)')
        look = (entry or {}).get('look') or {}
        listed = sorted({look.get(k) for k in ('weapon', 'shield', 'head_top', 'head_mid', 'head_bottom')} & self.config['visuais'])
        if listed:
            found.append('visual marcado como de GM ('+', '.join(map(str, listed))+')')
        return found
