"""@voltar after the hunt and a mount for the trips, both learned from the player once.

- @voltar: the chat frame the client sent when the player typed it is replayed as is.
  It only works out of combat and its casting is broken by physical damage: monsters
  around are killed first, the character waits calm, casts, and starts over when hit.
- Revive: on death during the hunt or a trip, "return to the save point", the recorded talk with
  the healer (Curandeira) and back to the hunting map by the routes.
- Mount: the item the player equipped and the equipment the server took off for it.
  Mounting also needs to be out of combat. The taken equipment is put back when the
  hunt starts; the mount goes back on for the next trip.
"""
import copy
import json
import time
import uuid
from pathlib import Path

FILE = Path(__file__).resolve().parents[1]/'data/rede/quest_extras.json'
DEFAULTS = dict(voltar_enabled=False, voltar_frame='', voltar_name='', calm_seconds=10, clear_radius=8,
                cast_timeout=15, attempts=6, mount_enabled=False, mount=None,
                characters={},  # name -> {'mount_item': id, 'combat_items': [ids]} chosen in the panel
                revive_enabled=False, revive_attempts=4, heal_steps=[], heal_map='')
AMMO = 0x8000


def for_character(config, name):
    """The mount and combat items chosen for the character playing (each one uses different items)."""
    config = copy.deepcopy(config)
    chosen = (config.get('characters') or {}).get(name or '') or {}
    if chosen.get('mount_item'):
        learned = config.get('mount') or {}
        same = learned.get('item_id') == chosen['mount_item']
        config['mount'] = dict(item_id=chosen['mount_item'], location=learned.get('location') if same else None,
                               displaced=learned.get('displaced', []) if same else [])
    config['combat_items'] = list(chosen.get('combat_items') or [])
    return config


def load(path=None):
    """The panel and the relay are two processes reading and writing this file: a read that meets
    the file while it is being replaced (or locked by an antivirus) is tried again, so a passing
    failure never looks like an empty configuration that the next save would write back."""
    path = Path(path or FILE)
    data = {}
    for attempt in range(20):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            break
        except FileNotFoundError:
            break
        except (OSError, ValueError):
            if attempt == 19:
                raise OSError('Nao foi possivel ler '+path.name+' (arquivo em uso por outro programa?)')
            time.sleep(.05)
    result = copy.deepcopy(DEFAULTS)
    result.update({k: v for k, v in (data if isinstance(data, dict) else {}).items() if k in DEFAULTS})
    if type(result['revive_attempts']) is not int:
        result['revive_attempts'] = DEFAULTS['revive_attempts']
    result['revive_attempts'] = max(1, min(20, result['revive_attempts']))
    return result


def load_defaults():
    return copy.deepcopy(DEFAULTS)


def save(config, path=None):
    """Written to a temporary file and swapped in; Windows refuses the swap while the other process
    reads the file, so it is retried for up to 3 s and then reported (never silently lost)."""
    data = {k: config.get(k, v) for k, v in DEFAULTS.items()}
    if type(data['revive_attempts']) is not int:
        data['revive_attempts'] = DEFAULTS['revive_attempts']
    data['revive_attempts'] = max(1, min(20, data['revive_attempts']))
    path = Path(path or FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    try:
        for attempt in range(60):
            try:
                temporary.replace(path)
                return data
            except PermissionError:
                if attempt == 59:
                    raise OSError('Nao foi possivel salvar '+path.name+': o arquivo esta em uso (antivirus ou '
                                  'outro programa?). Tente de novo.')
                time.sleep(.05)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass
    return data


def chat_frame(learned_hex, name=None):
    """The learned 00F3 frame, with the speaker swapped when another character is playing."""
    frame = bytes.fromhex(learned_hex)
    content = frame[4:].split(b'\0')[0]
    if not name or b' : ' not in content:
        return frame
    body = name.encode('cp1252', 'replace')+b' : '+content.split(b' : ', 1)[1]+b'\0'
    return frame[:2]+(4+len(body)).to_bytes(2, 'little')+body


def map_key(name):
    return str(name or '').lower().removesuffix('.gat')


class Body:
    """What the server said about the character: combat and worn equipment."""

    def __init__(self):
        self.gear = {}  # inventory index -> {'item_id', 'equip_location', 'worn'}
        self.last_combat = -1e9
        self.last_physical_hit = -1e9
        self.unequipped = []  # (time, index, position) taken off by the server
        self.acks = []  # (time, index, position, success, equipped)
        self.map_changed_at = -1e9
        self.map = None; self.same_map_teleport_at = -1e9  # map the character is on, from the server
        self.in_combat = None  # from the game's own messages, when it sends them
        self.notice_at = -1e9; self.notice = ''; self.left_combat_at = -1e9; self.combat_until = -1e9
        self.attackers = {}  # monster id -> last time it attacked the character
        self.skill_failed_at = -1e9; self.cast_at = -1e9; self.cast_ms = 0  # @voltar casts skill 960

    def observe(self, events, own, now):
        for e in events:
            kind = e['kind']
            if kind in ('map_change', 'map_transfer'):
                # A teleport inside the same map also comes as a map change: only another map counts.
                if e.get('map') and self.map and map_key(e['map']) == map_key(self.map):
                    self.same_map_teleport_at = now
                else:
                    self.map_changed_at = now
                if e.get('map'):
                    self.map = e['map']
            elif kind == 'inventory_list':
                stackable = bool(e.get('stackable'))
                self.gear = {i: v for i, v in self.gear.items() if v.get('stackable') != stackable}
                for item in e['items']:
                    self.gear[item['index']] = dict(item_id=item['item_id'], equip_location=item.get('equip_location', 0),
                                                    worn=item.get('equipped', 0), type=item.get('type'),
                                                    amount=item.get('amount', 1), stackable=stackable)
            elif kind == 'inventory_added' and e.get('success'):
                old = self.gear.get(e['index'])
                if old and old['item_id'] == e['item_id']:
                    old['amount'] = old.get('amount', 0)+e['amount']
                else:
                    self.gear[e['index']] = dict(item_id=e['item_id'], equip_location=e.get('equip_location', 0), worn=0, type=e.get('type'),
                                                 amount=e['amount'], stackable=e.get('type') not in (4, 5, 8, 12))
            elif kind == 'inventory_removed':
                item = self.gear.get(e['inventory_index'])
                if item:
                    item['amount'] = item.get('amount', 1)-e['amount']
                    if item['amount'] <= 0:
                        del self.gear[e['inventory_index']]
            elif kind == 'ammo_equipped':
                for index, item in self.gear.items():
                    if item.get('worn', 0) & AMMO:
                        item['worn'] = 0
                if e['index'] in self.gear:
                    self.gear[e['index']]['worn'] = AMMO
                self.acks.append((now, e['index'], AMMO, bool(e['index']), True))
            elif kind == 'equipment_ack':
                item = self.gear.setdefault(e['index'], dict(item_id=0, equip_location=e['position'], worn=0))
                if e['success']:
                    item['worn'] = e['position'] if e['equipped'] else 0
                    if not e['equipped']:
                        self.unequipped.append((now, e['index'], e['position']))
                self.acks.append((now, e['index'], e['position'], e['success'], e['equipped']))
                del self.acks[:-40]; del self.unequipped[:-40]
            elif kind == 'skill_failed':
                self.skill_failed_at = now
            elif kind == 'skill_cast' and e.get('source_id') == own:
                self.cast_at, self.cast_ms = now, e.get('duration_ms') or 0
            elif kind == 'combat_notice':
                self.notice_at, self.notice = now, e['text']
                self.in_combat = e['state'] == 'in'
                if self.in_combat:
                    self.last_combat = now
                    if e.get('seconds'):  # "aguarde N segundos": the game's own countdown decides
                        self.combat_until = now+e['seconds']; self.in_combat = None
                else:
                    self.left_combat_at = now; self.combat_until = -1e9
            elif kind in ('normal_attack', 'skill_damage') and own is not None and own in (e.get('source_id'), e.get('target_id')):
                self.last_combat = now
                if e.get('target_id') == own and e.get('source_id') not in (None, own):
                    self.attackers[e['source_id']] = now
                if e.get('target_id') == own and e.get('source_id') != own and e.get('damage_raw', 0) > 0 and kind == 'normal_attack':
                    self.last_physical_hit = now

    def items(self):
        """Inventory for the panel: what the server listed for this character."""
        return [dict(index=i, item_id=v['item_id'], type=v.get('type'), amount=v.get('amount', 1),
                     worn=v.get('worn', 0), equip_location=v.get('equip_location', 0))
                for i, v in sorted(self.gear.items())]

    def position_of(self, index):
        item = self.gear.get(index, {})
        return AMMO if item.get('type') == 10 else item.get('equip_location') or 0

    def index_of(self, item_id, worn=None):
        for index, item in self.gear.items():
            if item['item_id'] == item_id and (worn is None or bool(item['worn']) == worn):
                return index
        return None

    def wearing(self, item_id):
        return self.index_of(item_id, worn=True) is not None


class Errand:
    """One job between quest steps: 'voltar', 'mount' or 'gear'. step() says what to do now:
    ('clear', species) hunt the monsters around · ('wait', None) stand still · ('chat', frame) ·
    ('equip', (index, position)) · ('done', None) · ('fail', reason)."""

    def __init__(self, kind, config, now):
        self.kind, self.config, self.state, self.started, self.attempts = kind, config, 'clear', now, 0
        self.sent_at = None; self.reason = ''; self.displaced = []; self.pending = None; self.cast_from = None

    def calm(self, body, near, now):
        if near:
            self.reason = f'matando {len(near)} monstro(s) ao redor antes de '+('usar @voltar' if self.kind == 'voltar' else 'equipar a montaria')
            return ('clear', sorted({species for _, species in near}))
        if now < body.combat_until:
            self.reason = f'o jogo diz em combate ({body.combat_until-now:.0f} s)'
            return ('wait', None)
        if body.combat_until > -1e9 and body.last_combat <= body.notice_at:
            return None  # the game's countdown ended with no fighting since
        if body.in_combat is False and body.left_combat_at >= body.last_combat:
            return None  # the game said the character left combat
        if body.in_combat and now-body.notice_at < 30:
            self.reason = 'o jogo diz em combate: '+body.notice
            return ('wait', None)
        wait = self.config['calm_seconds']-(now-body.last_combat)
        if wait > 0:
            self.reason = f'aguardando sair de combate ({wait:.0f} s)'
            return ('wait', None)
        return None

    def step(self, body, near, now, *, name=None):
        if self.kind == 'gear':
            return self.gear(body, now)
        if self.kind == 'mount':
            return self.mount(body, near, now)
        return self.voltar(body, near, now, name)

    def voltar(self, body, near, now, name):
        if self.state == 'cast':
            if body.map_changed_at >= self.cast_from:
                self.reason = '@voltar concluido: chegou em '+(body.map or 'outro mapa')
                return ('done', None)
            if body.last_physical_hit >= self.cast_from:
                self.state = 'clear'; self.reason = 'conjuracao do @voltar cancelada por dano; matando os monstros'
                return ('wait', None)
            if body.notice_at >= self.cast_from and (body.in_combat or body.combat_until > now):
                self.state = 'clear'; self.reason = '@voltar recusado pelo jogo: '+body.notice
                return ('wait', None)
            if body.skill_failed_at >= self.cast_from and body.cast_at < self.cast_from:
                # The server refuses the @voltar casting (skill 960) while in combat: wait it out again.
                self.state = 'clear'; self.reason = '@voltar recusado pelo servidor (ainda em combate); esperando de novo'
                body.last_combat = max(body.last_combat, now)
                return ('wait', None)
            limit = self.config['cast_timeout']
            if body.cast_at >= self.cast_from:
                limit = max(limit, body.cast_at-self.cast_from+body.cast_ms/1000+5)
                self.reason = f'conjurando @voltar ({body.cast_ms/1000:.1f} s de conjuracao)'
            if now-self.cast_from > limit:
                self.state = 'clear'; self.reason = '@voltar sem teletransporte; tentando de novo'
            return ('wait', None)
        busy = self.calm(body, near, now)
        if busy:
            return busy
        if self.attempts >= self.config['attempts']:
            return ('fail', '@voltar nao teletransportou apos '+str(self.attempts)+' tentativas')
        if not self.config.get('voltar_frame'):
            return ('fail', 'Aprenda o @voltar: digite-o uma vez no jogo com "Aprender @voltar" ativo')
        self.attempts += 1; self.state = 'cast'; self.cast_from = now; self.cast_map = body.map
        self.reason = f'conjurando @voltar (tentativa {self.attempts})'
        return ('chat', chat_frame(self.config['voltar_frame'], name))

    def mount(self, body, near, now):
        mount = self.config.get('mount') or {}
        if self.pending:
            ack = next((a for a in body.acks if a[0] >= self.pending[0] and a[1] == self.pending[1] and a[4]), None)
            if ack and ack[3]:
                # What the server took off for the mount comes back on before the hunt.
                self.displaced = [dict(item_id=body.gear.get(i, {}).get('item_id', 0), position=p)
                                  for t, i, p in body.unequipped if t >= self.pending[0] and i != self.pending[1]]
                self.pending = None
                self.reason = 'montaria equipada'
                return ('done', None)
            refused = body.notice_at >= self.pending[0] and (body.in_combat or body.combat_until > now)
            if not ack and not refused and now-self.pending[0] <= 4:
                return ('wait', None)
            self.pending = None; self.retry_at = now+1
            self.reason = 'servidor recusou a montaria (em combate?); tentando de novo'
            return ('wait', None)
        if body.wearing(mount.get('item_id')):
            self.reason = 'montaria equipada'
            return ('done', None)
        if now < getattr(self, 'retry_at', 0):
            return ('wait', None)
        busy = self.calm(body, near, now)
        if busy:
            return busy
        index = body.index_of(mount.get('item_id'))
        if index is None:
            return ('fail', 'Montaria (item '+str(mount.get('item_id'))+') nao esta no inventario')
        self.attempts += 1
        if self.attempts > self.config['attempts']:
            return ('fail', 'O servidor nao equipou a montaria apos '+str(self.config['attempts'])+' tentativas')
        self.pending = (now, index); self.reason = 'equipando a montaria'
        from .item_names import MOUNT_SLOTS  # slots unknown (received this session): a mount takes these three
        return ('equip', (index, mount.get('location') or body.position_of(index) or MOUNT_SLOTS))

    def gear(self, body, now):
        """Put back what the mount took off, one item at a time.

        While the mount is on, the server can refuse the hand items and accept only the one that
        takes the mount off (the scroll, below): a refused item is tried again after the others,
        up to 4 times each, instead of being given up at the first refusal."""
        failed = self.__dict__.setdefault('failures', {})
        if self.pending:
            ack = next((a for a in body.acks if a[0] >= self.pending[0] and a[1] == self.pending[1] and a[4]), None)
            if not ack and now-self.pending[0] <= 3:
                return ('wait', None)
            if ack and ack[3]:
                failed.clear()  # something changed (the mount came off): the refused ones may work now
            else:
                failed[self.pending[2]] = failed.get(self.pending[2], 0)+1
                self.retry_at = now+.6
            self.pending = None
        if now < getattr(self, 'retry_at', 0):
            return ('wait', None)
        chosen = [dict(item_id=i, position=None) for i in self.config.get('combat_items') or []]
        missing = []
        for item in chosen or self.config.get('displaced') or []:
            if body.wearing(item['item_id']):
                continue
            index = body.index_of(item['item_id'], worn=False)
            if index is None:
                continue
            missing.append((failed.get(item['item_id'], 0), item, index))
        for tries, item, index in sorted(missing, key=lambda m: m[0]):  # the least refused first
            if tries >= 4:
                continue
            self.pending = (now, index, item['item_id']); self.reason = 'equipando os itens de combate'
            return ('equip', (index, item['position'] or body.position_of(index)))
        if missing:
            self.reason = 'o servidor recusou '+str(len(missing))+' item(ns) de combate: '+', '.join(str(m[1]['item_id']) for m in missing)
            print('[ROTA] '+self.reason)
        else:
            self.reason = 'itens de combate equipados'
        return ('done', None)
