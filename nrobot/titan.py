"""Titan: what the own game client draws, changed locally by the relay.

The relay is between the server and the game. Titan is the last filter of the server -> client
stream: it adds packets the client already understands (state 0229/028A for colour, vanish 0080
and a re-sent appearance) or withholds the packets of hidden units. Size is not done here: the
panel sets the client's own zoom of each unit (titan_zoom). Nothing is sent
to the server and the bot's own reading of the stream (mirror_map) sees the original bytes.
"""
import json
import os
import struct
import tempfile
import time
from collections import OrderedDict
from pathlib import Path

from .network_targets import is_player_id
from .npc_labels import plain
from .packet_reader import message_length
from . import titan_settings

SPAWNS = {0x78: 47, 0x7c: 37, 0x22a: 50, 0x22b: 50, 0x22c: 55}  # opcode -> position offset
WITHHELD = {0x86, 0x88, 0x9c, 0x119, 0x229, 0x28a, 0x1f3, 0xc3, 0x1d7, 0x196}  # dropped while hidden
SUMMON_TYPES = {7, 8, 9, 10}  # pet, homunculus, mercenary, elemental
NPC_TYPES = {1, 6}
NAME_CACHE_LIMIT = 4096


def encode_position(x, y, direction=0):
    return bytes([(x >> 2) & 0xff, ((x & 3) << 6) | ((y >> 4) & 0x3f), ((y & 15) << 4) | (direction & 15)])


def encode_movement(sx, sy, dx, dy, tail=0x88):
    return bytes([(sx >> 2) & 0xff, ((sx & 3) << 6) | ((sy >> 4) & 0x3f), ((sy & 15) << 4) | ((dx >> 6) & 15),
                  ((dx & 63) << 2) | ((dy >> 8) & 3), dy & 0xff, tail & 0xff])


def decode_position(raw):
    return raw[0] << 2 | raw[1] >> 6, (raw[1] & 63) << 4 | raw[2] >> 4, raw[2] & 15


def decode_destination(raw):
    return ((raw[2] & 15) << 6) | raw[3] >> 2, ((raw[3] & 3) << 8) | raw[4]


# 0080 type in the pinned NRO.exe (handler 0x5986A0, switch on the type byte): 0 sends the unit
# message 0x63 first (a fade-out), 1 plays the death, 2/3 launch the logout/teleport effect. Any
# type above 3 takes the default branch: the unit is removed and deleted at once, with nothing drawn.
INSTANT_VANISH = 4


def vanish_packet(entity_id):
    return struct.pack('<HIB', 0x80, entity_id, INSTANT_VANISH)


class TitanConfig:
    """The panel's file, read again when it changes. A stat every 15 ms keeps a key press instant."""

    def __init__(self, path=None):
        self.path = Path(path or titan_settings.FILE)
        self.next_poll = 0
        self.stamp = None
        self.version = 0  # raised on every reload: what the filter compares, not the object identity
        self.value = titan_settings.validate({'enabled': False})

    def __call__(self):
        now = time.monotonic()
        if now >= self.next_poll:
            self.next_poll = now+.015
            try:
                info = self.path.stat()
                stamp = (info.st_mtime_ns, info.st_size)
            except OSError:
                stamp = None
            if stamp != self.stamp:
                self.stamp = stamp
                self.value = titan_settings.load(self.path) if stamp is not None else titan_settings.validate({'enabled': False})
                self.version += 1
        return self.value


class Titan:
    def __init__(self, account, config, summon_ids=None, screen_file=None):
        self.account = account
        self.player_id = int.from_bytes(account, 'little') if account else None
        self.config = config
        self.summon_ids = summon_ids or (lambda: set())
        self.name_queue = []  # unit ids whose name the relay asks the server for (0094)
        self.name_asked = {}  # unit id -> time asked
        self.departed_names = OrderedDict()  # confirmed names of units that left view, this map only
        self.next_name_scan = 0
        self.screen_file = Path(screen_file) if screen_file else None
        self.pending = bytearray()
        self.started = self.passthrough = self.ready = False
        self.entities = {}
        self.applied = {}  # entity id -> colour (field, value) or None the client is drawing now
        self.hidden = set()
        self.summon_species = set()  # species of creatures the bot recognized as summons this session
        self.signature = None
        self.screen_written = 0
        self.screen_last = None
        self.error = None
        self.injected = 0

    # ---- stream -----------------------------------------------------------------------------
    def feed(self, data):
        if self.passthrough:
            return data
        self.pending.extend(data)
        output = bytearray()
        offset = 0
        if not self.started:
            if len(self.pending) < 4:
                return b''
            self.started = True
            if self.account and self.pending[:4] == self.account:
                output.extend(self.pending[:4])
                offset = 4
        while offset < len(self.pending):
            try:
                size = message_length(self.pending, offset)
            except (ValueError, OSError) as exc:
                self.error = str(exc)
                self.passthrough = True
                output.extend(self.pending[offset:])
                offset = len(self.pending)
                break
            if size is None or offset+size > len(self.pending):
                break
            packet = bytearray(self.pending[offset:offset+size])
            offset += size
            try:
                output.extend(self.packet(packet))
            except (struct.error, IndexError):
                output.extend(packet)  # an unexpected layout is forwarded untouched
        del self.pending[:offset]
        if not self.passthrough:
            output.extend(self.refresh())
        return bytes(output)

    def flush(self):
        data = bytes(self.pending)
        self.pending.clear()
        return data

    def tick(self):
        """Called by the relay a few times per second: a key press must not wait for traffic."""
        if self.passthrough or self.pending:
            return b''
        return self.refresh()

    # ---- packets ----------------------------------------------------------------------------
    def packet(self, packet):
        op = struct.unpack_from('<H', packet)[0]
        if op in (0x73, 0x2eb, 0x91, 0x92):
            self.entities.clear()
            self.applied.clear()
            self.hidden.clear()
            self.name_queue.clear()
            self.name_asked.clear()
            self.departed_names.clear()
            self.next_name_scan = 0
            self.ready = op != 0x92
            return packet
        if op in SPAWNS:
            return self.spawn(op, packet)
        if op == 0x80:
            identity = struct.unpack_from('<I', packet, 2)[0]
            entity = self.entities.pop(identity, None)
            self.departed_names.pop(identity, None)
            if packet[6] == 0 and entity and entity.get('name'):
                self.departed_names[identity] = {key: entity.get(key) for key in
                                                 ('species', 'type', 'name', 'name_packet')}
                while len(self.departed_names) > NAME_CACHE_LIMIT:
                    self.departed_names.popitem(last=False)
            self.name_asked.pop(identity, None)
            self.name_queue = [i for i in self.name_queue if i != identity]
            self.applied.pop(identity, None)
            if identity in self.hidden:
                self.hidden.discard(identity)
                return b''
            return packet
        if op in (0x95, 0x195):
            identity = struct.unpack_from('<I', packet, 2)[0]
            entity = self.entities.get(identity)
            if entity is not None:
                name = packet[6:30].split(b'\0')[0].decode('cp1252', 'replace')
                entity['name_packet'] = bytes(packet)
                if name != entity.get('name'):
                    entity['name'] = name
                    return bytes(packet)+self.evaluate(entity)
            return packet
        if len(packet) < 6:
            return packet
        identity = struct.unpack_from('<I', packet, 2)[0]
        entity = self.entities.get(identity)
        if entity is None:
            return packet
        if op == 0x86:
            entity['position'] = decode_destination(packet[6:12])
        elif op == 0x88:
            entity['position'] = struct.unpack_from('<HH', packet, 6)
        elif op == 0x119:
            entity['opt1'], entity['opt2'], entity['option'] = struct.unpack_from('<hhH', packet, 6)
            self.tint_state(entity, packet, 0x119)
        elif op == 0x229:
            entity['opt1'], entity['opt2'], entity['option'] = struct.unpack_from('<hhI', packet, 6)
            self.tint_state(entity, packet, 0x229)
        elif op == 0x28a:
            entity['option'], entity['level'], entity['opt3'] = struct.unpack_from('<III', packet, 6)
            colour = self.applied.get(identity)
            if colour and colour[0] == 'opt3':
                struct.pack_into('<I', packet, 14, entity['opt3'] | colour[1])
        elif op in (0xc3, 0x1d7):
            entity['looks'][packet[6]] = bytes(packet)
        if identity in self.hidden and op in WITHHELD:
            return b''
        return packet

    def spawn(self, op, packet):
        identity = struct.unpack_from('<I', packet, 3 if op in (0x78, 0x7c, 0x22c) else 2)[0]
        old = self.entities.get(identity) or {}
        if op in (0x78, 0x7c, 0x22c):
            object_type, species = packet[2], struct.unpack_from('<H', packet, 21 if op == 0x7c else 17 if op == 0x22c else 15)[0]
            opt1, opt2 = struct.unpack_from('<hh', packet, 9)
            option = struct.unpack_from('<I' if op == 0x22c else '<H', packet, 13)[0]
        else:
            object_type, species = None, struct.unpack_from('<H', packet, 16)[0]
            opt1, opt2 = struct.unpack_from('<hh', packet, 8)
            option = struct.unpack_from('<I', packet, 12)[0]
        cached = self.departed_names.pop(identity, None)
        if not old and cached:
            old = cached
        if old.get('species') != species or old.get('type') != object_type:
            old = {}
        at = SPAWNS[op]
        if op == 0x22c:
            position = decode_destination(packet[at:at+6])
            direction = 0
        else:
            x, y, direction = decode_position(packet[at:at+3])
            position = (x, y)
        level = 0
        if op in (0x22a, 0x22b, 0x22c):
            level_at = {0x22a: 56, 0x22b: 55, 0x22c: 63}[op]
            level = struct.unpack_from('<H', packet, level_at)[0] if len(packet) >= level_at+2 else 0
        entity = dict(id=identity, op=op, packet=bytes(packet), type=object_type, species=species,
                      position=position, direction=direction, opt1=opt1, opt2=opt2, option=option,
                      opt3=old.get('opt3', 0), level=level, name=old.get('name'),
                      name_packet=old.get('name_packet'), looks=old.get('looks', {}))
        self.entities[identity] = entity
        self.applied.pop(identity, None)  # a new appearance: the client draws it as sent
        self.want_name(entity)
        if self.hide_wanted(entity):
            self.hidden.add(identity)
            return b''
        self.hidden.discard(identity)
        return bytes(packet)+(entity.get('name_packet') or b'')+self.apply(entity)

    def tint_state(self, entity, packet, op):
        colour = self.applied.get(entity['id'])
        if not colour:
            return
        field, value = colour
        if field == 'opt1' and not entity['opt1']:
            struct.pack_into('<h', packet, 6, value)
        elif field == 'opt2':
            struct.pack_into('<h', packet, 8, (entity['opt2'] | value) & 0x7fff)

    # ---- decisions --------------------------------------------------------------------------
    def names_needed(self):
        cfg = self.config()
        return cfg['enabled'] and (
            any(g['active'] and g['except_names'] for g in cfg['hide_groups'])
            or any(r['enabled'] and r['kind'] == 'name' for r in cfg['rules']))

    def want_name(self, entity):
        """Monsters, summons and NPCs get their name only when the game asks (mouse over it): the
        relay asks right away when a name decides what Titan does."""
        identity = entity['id']
        if entity.get('name') or self.kind(entity) in ('self', 'player') or not self.names_needed():
            return
        now = time.monotonic()
        if now-self.name_asked.get(identity, -10) >= 3 and identity not in self.name_queue:
            self.name_queue.append(identity)

    def take_name_requests(self, limit=8):
        """Ids to ask now (at most `limit`), still on screen and still without a name."""
        taken = []
        if not self.names_needed():
            self.name_queue.clear()
            return taken
        now = time.monotonic()
        while self.name_queue and len(taken) < limit:
            identity = self.name_queue.pop(0)
            entity = self.entities.get(identity)
            if entity is None or entity.get('name'):
                continue
            self.name_asked[identity] = now
            taken.append(identity)
        return taken

    def kind(self, entity):
        identity = entity['id']
        if identity == self.player_id:
            return 'self'
        if is_player_id(identity) or is_player_id((-identity) & 0xffffffff):
            return 'player'
        cfg = self.config()
        if identity in self.summon_ids():
            self.summon_species.add(entity['species'])  # the same creature summoned again later
            return 'summon'
        if entity['species'] in self.summon_species or entity['species'] in cfg['summon_species'] or entity['type'] in SUMMON_TYPES:
            return 'summon'
        if entity['type'] in NPC_TYPES:
            return 'npc'
        if entity['type'] == 5:
            return 'monster'
        return 'monster' if entity['species'] >= 1000 else 'npc'

    def hide_wanted(self, entity):
        cfg = self.config()
        if not cfg['enabled']:
            return False
        kind = self.kind(entity)
        if kind == 'self':
            return False
        # The server's name only (asked by request_name as soon as the unit appears). A unit whose
        # name is not known yet is not "marked by name": in "todos menos os marcados" it stays hidden
        # until the name arrives, so a wrongly named Bikouchuu never shows up.
        name = plain(entity.get('name') or '')
        for group in cfg['hide_groups']:
            if not group['active']:
                continue
            if not ((kind == 'player' and group['players']) or (kind == 'npc' and group['npcs'])
                    or (kind == 'monster' and group['monsters']) or (kind == 'summon' and group['summons'])):
                continue
            marked = (entity['id'] in group['except_ids']
                      or bool(name) and name in {plain(n) for n in group['except_names']}
                      or (kind != 'player' and entity['species'] in group['except_species']))
            if marked == (group['mode'] == 'only'):
                return True
        return False

    def wanted(self, entity):
        """Colour (field, value) or None, asked by the most specific enabled rule."""
        cfg = self.config()
        if not cfg['enabled']:
            return None
        name = plain(entity.get('name') or '')
        best = None
        for rule in cfg['rules']:
            if not rule['enabled'] or rule['color'] == 'none':
                continue
            if rule['kind'] == 'entity' and int(rule['value']) == entity['id']:
                rank = 3
            elif rule['kind'] == 'name' and name and plain(rule['value']) == name:
                rank = 2
            elif rule['kind'] == 'species' and int(rule['value']) == entity['species']:
                rank = 1
            else:
                continue
            if best is None or rank > best[0]:
                best = (rank, rule)
        if best is None:
            return None
        spec = titan_settings.COLORS[best[1]['color']]
        return (spec['field'], spec['value']) if spec['field'] else None

    def apply(self, entity):
        """Packets that draw the wanted colour on a unit the client just (re)created."""
        colour = self.wanted(entity)
        self.applied[entity['id']] = colour
        if not colour:
            return b''
        self.injected += 1
        return self.state_packets(entity, colour)

    def state_packets(self, entity, colour, previous=None):
        field, value = colour or (None, 0)
        opt1 = value if field == 'opt1' and not entity['opt1'] else entity['opt1']
        opt2 = (entity['opt2'] | value) & 0x7fff if field == 'opt2' else entity['opt2']
        out = struct.pack('<HIhhIB', 0x229, entity['id'], opt1, opt2, entity['option'], 0)
        # 028A also when an opt3 tint is being taken off: 0229 alone leaves it drawn.
        if field == 'opt3' or entity['opt3'] or (previous and previous[0] == 'opt3'):
            out += struct.pack('<HIIII', 0x28a, entity['id'], entity['option'], entity['level'],
                               entity['opt3'] | (value if field == 'opt3' else 0))
        return out

    def respawn(self, entity):
        """The cached appearance at the latest known cell (a hidden unit shown again)."""
        packet = bytearray(entity['packet'])
        at = SPAWNS[entity['op']]
        x, y = entity['position']
        if entity['op'] == 0x22c:
            packet[at:at+6] = encode_movement(x, y, x, y, packet[at+5])
        else:
            packet[at:at+3] = encode_position(x, y, entity['direction'])
        if entity['op'] == 0x22b and len(packet) == 57:
            # 022B is "just arrived" (the client gives the unit an entrance); shown again it is
            # simply standing there: 022A, the same fields plus the stand state byte (0).
            packet = bytearray(struct.pack('<H', 0x22a))+packet[2:55]+b'\0'+packet[55:57]
        out = bytearray(packet)
        for look in entity['looks'].values():
            out.extend(look)
        if entity.get('name_packet'):
            out.extend(entity['name_packet'])  # the client needs the name after the unit exists
        if entity['opt1'] or entity['opt2'] or entity['opt3']:
            out.extend(self.state_packets(entity, None))
        return bytes(out)

    def evaluate(self, entity):
        identity = entity['id']
        hide = self.hide_wanted(entity)
        if hide and identity not in self.hidden:
            self.hidden.add(identity)
            self.applied.pop(identity, None)
            return vanish_packet(identity)
        if not hide and identity in self.hidden:
            self.hidden.discard(identity)
            return self.respawn(entity)+self.apply(entity)
        if hide:
            return b''
        colour = self.wanted(entity)
        previous = self.applied.get(identity)
        if colour == previous:
            return b''
        self.applied[identity] = colour
        return self.state_packets(entity, colour, previous)

    def refresh(self):
        if not self.ready:
            return b''
        cfg = self.config()
        out = bytearray()
        try:
            summons = sorted(self.summon_ids())
        except Exception:
            summons = []
        # An object id can be reused by Python after the old config is freed: compare a version.
        version = getattr(self.config, 'version', None)
        signature = (version if version is not None else json.dumps(cfg, sort_keys=True), tuple(summons))
        if signature != self.signature:
            self.signature = signature
            for entity in list(self.entities.values()):
                self.want_name(entity)
                out.extend(self.evaluate(entity))
        now = time.monotonic()
        if now >= self.next_name_scan:
            self.next_name_scan = now+.25
            for entity in list(self.entities.values()):
                self.want_name(entity)  # retry unanswered requests without toggling the shortcut
        self.write_screen()
        return bytes(out)

    # ---- panel feed -------------------------------------------------------------------------
    def screen(self):
        rows = []
        for entity in self.entities.values():
            rows.append(dict(id=entity['id'], species=entity['species'], name=entity.get('name') or '',
                             kind=self.kind(entity), x=entity['position'][0], y=entity['position'][1],
                             hidden=entity['id'] in self.hidden))
        rows.sort(key=lambda r: (r['kind'], r['species'], r['id']))
        return rows

    def write_screen(self, force=False):
        if self.screen_file is None or not self.config()['enabled']:
            return
        now = time.monotonic()
        if not force and now-self.screen_written < .3:
            return
        self.screen_written = now
        rows = self.screen()
        if rows == self.screen_last and not force:
            return
        self.screen_last = rows
        try:
            self.screen_file.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.screen_file.parent, suffix='.tmp',
                                             delete=False) as handle:
                json.dump(dict(updated=time.time(), own_id=self.player_id, entities=rows), handle, ensure_ascii=False)
                temporary = handle.name
            os.replace(temporary, self.screen_file)
        except OSError:
            pass

    def diagnostic(self):
        return dict(ready=self.ready, entities=len(self.entities), hidden=len(self.hidden),
                    injected=self.injected, framing_error=self.error)
