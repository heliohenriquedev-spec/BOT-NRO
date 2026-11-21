"""Armazém (@storage): deposit the Item/Etc tabs when the character is heavy, withdraw chosen items.

The NRO client shuffles its request packets, so the three storage requests (put an item in,
take one out, close the window) are learned once from the game itself: the player does each
action by hand and the bot keeps the client frame that the server confirmed, with the offsets
of the inventory/storage index and the amount. Server packets are the standard ones.
"""
from __future__ import annotations

import json
import struct
from collections import deque
from pathlib import Path

PATH = Path(__file__).resolve().parents[1]/'data/rede/armazem.json'
CONTENT_PATH = Path(__file__).resolve().parents[1]/'data/rede/armazem_conteudo.json'
# Learned requests shipped with the bot: same client for everyone, so nobody has to learn again.
BUNDLED_PATH = Path(__file__).resolve().parents[1]/'data/recursos/armazem_pacotes.json'
DEFAULTS = dict(auto_enabled=False, threshold=50, keep_ids=[], frames={}, refused_ids=[])
IGNORED_OPCODES = {0x89, 0x7d, 0xa7, 0xf3}  # chat, walk, clock: never a storage request
SEND_GAP = 0.35   # s between two storage requests
ITEM_WAIT = 2.0   # s for the server to confirm a deposit/withdrawal; then the item is skipped
OPEN_WAIT = 6.0   # s for @storage to open
RETRY_SAME = 60.0   # s before trying again with exactly the same storable items (nothing went in)
RETRY_GAP = 5.0     # s between two deposits otherwise: still heavy -> deposit again
JOB_LIMIT = 90.0    # s: a storage visit that never finishes is abandoned and the hunt resumes


def load():
    try:
        data = json.loads(PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    result = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    result['threshold'] = max(10, min(95, int(result.get('threshold') or 50)))
    result['keep_ids'] = sorted({int(i) for i in result.get('keep_ids') or [] if str(i).isdigit()})
    result['auto_enabled'] = bool(result.get('auto_enabled'))
    try:
        bundled = json.loads(BUNDLED_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        bundled = {}
    frames = {**bundled, **(result.get('frames') or {})}
    result['frames'] = {k: v for k, v in frames.items() if k in ('store', 'take', 'close') and isinstance(v, dict)}
    result['refused_ids'] = sorted({int(i) for i in data.get('refused_ids') or [] if str(i).isdigit()})
    return result


def save(config):
    data = {**load(), **config}
    temp = PATH.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(PATH)
    return load()


def load_contents():
    try:
        return json.loads(CONTENT_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_contents(name, items):
    data = load_contents()
    data[name] = [dict(item_id=i['item_id'], amount=i['amount']) for i in items]
    temp = CONTENT_PATH.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temp.replace(CONTENT_PATH)


def find_fields(frame, index, amount):
    """Offsets (index u16, amount u32 or u16) inside a client frame, after the opcode."""
    data = bytes(frame)
    index_bytes = struct.pack('<H', index)
    for i in range(2, len(data)-1):
        if data[i:i+2] != index_bytes:
            continue
        for size, fmt in ((4, '<I'), (2, '<H')):
            packed = struct.pack(fmt, amount)
            for j in range(2, len(data)-size+1):
                if data[j:j+size] == packed and (j+size <= i or j >= i+2):
                    return dict(index_offset=i, amount_offset=j, amount_size=size)
    return None


def build(template, index=None, amount=None):
    frame = bytearray(bytes.fromhex(template['hex']))
    if index is not None:
        struct.pack_into('<H', frame, template['index_offset'], index)
    if amount is not None:
        size = template['amount_size']
        struct.pack_into('<I' if size == 4 else '<H', frame, template['amount_offset'],
                         min(amount, 0xffffffff if size == 4 else 0xffff))
    return bytes(frame)


class Storage:
    def __init__(self):
        self.config = load()
        self.weight = None
        self.max_weight = None
        self.open = False
        self.items = {}         # storage index -> {'item_id', 'amount', 'stackable'}
        self.learning = None    # 'store' | 'take' | 'close'
        self.recent = deque(maxlen=40)   # (time, opcode, frame) sent by the client
        self.removed = deque(maxlen=10)  # (time, index, amount): inventory/storage removals
        self.stored_at = -1e9  # last storage_added: the server removes the inventory item right after it
        self.job = None
        self.last_auto = -1e9
        self.last_signature = None  # storable items of the last deposit that moved nothing
        self.reason = ''
        self.character = ''

    # --- server and client observation -------------------------------------------------
    def observe(self, events, now):
        for e in events:
            kind = e['kind']
            if kind == 'player_stat' and e.get('stat_type') == 24:
                self.weight = e['value']
            elif kind == 'player_stat' and e.get('stat_type') == 25:
                self.max_weight = e['value']
            elif kind == 'storage_opened':
                self.open = True
                if self.job and self.job['stage'] == 'opening' and self.job.get('asked') is not None:
                    self.job.update(stage='opened', at=now)
            elif kind == 'storage_list':
                if not self.open:
                    self.items = {}
                self.open = True
                for item in e['items']:
                    self.items[item['index']] = dict(item_id=item['item_id'], amount=item['amount'],
                                                     stackable=e['stackable'])
                if self.job and self.job['stage'] == 'opening' and self.job.get('asked') is not None:
                    self.job.update(stage='opened', at=now)
                self.remember()
            elif kind == 'storage_added':
                old = self.items.get(e['index'], {})
                self.items[e['index']] = dict(item_id=e['item_id'], amount=old.get('amount', 0)+e['amount'])
                self.stored_at = now
                self.learn_from('store', now)
                if self.job and self.job.get('waiting') == 'store':
                    self.job.update(waiting=None, item_id=None, done=self.job.get('done', 0)+1, sent_at=now)
                self.remember()
            elif kind == 'storage_removed':
                item = self.items.get(e['index'])
                if item:
                    item['amount'] = max(0, item['amount']-e['amount'])
                    if not item['amount']:
                        self.items.pop(e['index'], None)
                self.removed.append((now, e['index'], e['amount']))
                self.learn_from('take', now)
                if self.job and self.job.get('waiting') == 'take':
                    self.job.update(waiting=None, done=self.job.get('done', 0)+1, sent_at=now)
                self.remember()
            elif kind == 'inventory_removed':
                self.removed.append((now, e['inventory_index'], e['amount']))
                if now-self.stored_at < 2.5:
                    self.learn_from('store', now, quiet=True)
            elif kind == 'storage_closed':
                self.open = False
                self.learn_from('close', now)
                if self.job and self.job['stage'] == 'closing':
                    self.finish()
            elif kind in ('map_change', 'map_transfer'):
                self.open = False

    def client(self, opcode, frame, now):
        if opcode not in IGNORED_OPCODES:
            self.recent.append((now, opcode, bytes(frame)))

    def remember(self):
        if self.character:
            try:
                save_contents(self.character, list(self.items.values()))
            except OSError:
                pass

    def learn_from(self, what, now, quiet=False):
        if self.learning != what:
            return
        frames = [f for t, _, f in reversed(self.recent) if now-t < 2.5]
        template = None
        if what == 'close':
            if frames:
                template = dict(hex=frames[0].hex())
        else:
            removals = [(i, a) for t, i, a in reversed(self.removed) if now-t < 2.5]
            for frame in frames:
                for index, amount in removals:
                    fields = find_fields(frame, index, amount)
                    if fields:
                        template = dict(hex=frame.hex(), **fields)
                        break
                if template:
                    break
        if template is None:
            if what == 'store' and not quiet:
                return  # the inventory removal (00AF) comes right after the storage one
            self.reason = 'Acao vista no servidor, mas o pacote do jogo nao foi reconhecido; tente de novo'
            return
        frames_config = dict(self.config['frames'])
        frames_config[what] = template
        self.config = save(dict(frames=frames_config))
        try:
            BUNDLED_PATH.write_text(json.dumps(frames_config, indent=2), encoding='utf-8')
        except OSError:
            pass
        self.learning = None
        self.reason = {'store': 'Guardar item aprendido', 'take': 'Retirar item aprendido',
                       'close': 'Fechar armazem aprendido'}[what]

    # --- jobs ------------------------------------------------------------------------
    def missing(self):
        return [label for key, label in (('store', 'guardar'), ('take', 'retirar'), ('close', 'fechar'))
                if key not in self.config['frames']]

    def heavy(self):
        if not self.weight or not self.max_weight:
            return False
        return self.weight*100 >= self.config['threshold']*self.max_weight

    def storable(self, inventory):
        keep = set(self.config['keep_ids']) | set(self.config['refused_ids'])
        return [(i, v['amount'], v['item_id']) for i, v in sorted(inventory.items())
                if v.get('stackable') and v.get('amount', 0) > 0 and not v.get('equipped')
                and v['item_id'] not in keep]

    def wants_auto(self, now, inventory=None):
        if not (self.config['auto_enabled'] and self.job is None and self.heavy()
                and 'store' in self.config['frames'] and 'close' in self.config['frames']):
            return False
        if now-self.last_auto < RETRY_GAP:
            return False
        if inventory is not None:
            queue = self.storable(inventory)
            if not queue:
                return False  # nothing of the Item/Etc tabs that can be stored
            signature = tuple(queue)
            if signature == self.last_signature and now-self.last_auto < RETRY_SAME:
                return False  # the same items did not go in a moment ago
        return True

    def start_deposit(self, inventory, now):
        queue = self.storable(inventory)
        self.last_auto = now
        self.signature = tuple(queue)
        self.job = dict(kind='deposit', stage='opening', at=now, queue=queue, done=0, sent_at=-1e9, waiting=None,
                        started=now)
        self.reason = f'Peso acima de {self.config["threshold"]}%: guardando {len(queue)} item(ns) no armazem'

    def start_withdraw(self, wanted, now):
        """wanted: [{'item_id', 'amount'}] (amount 0 = everything stored)."""
        self.job = dict(kind='withdraw', stage='opening', at=now, wanted=list(wanted), queue=None, done=0,
                        sent_at=-1e9, waiting=None, started=now)
        self.reason = f'Retirando {len(wanted)} item(ns) do armazem'

    def withdraw_queue(self):
        queue = []
        for want in self.job['wanted']:
            left = int(want.get('amount') or 0)
            for index, item in sorted(self.items.items()):
                if item['item_id'] != int(want['item_id']) or item['amount'] <= 0:
                    continue
                take = item['amount'] if left <= 0 else min(left, item['amount'])
                queue.append((index, take, item['item_id']))
                if left > 0:
                    left -= take
                    if not left:
                        break
        return queue

    def finish(self):
        job, self.job = self.job, None
        if job and job['kind'] == 'deposit':
            self.last_signature = None if job.get('done') else getattr(self, 'signature', None)
        if job and job['kind'] == 'deposit' and job.get('done') and job.get('refused'):
            # Another item went in during the same visit: these were refused by the server
            # (not storable), never tried again. With nothing accepted it may be a full storage.
            refused = sorted(set(self.config['refused_ids']) | set(job['refused']))
            try:
                self.config = save(dict(refused_ids=refused))
            except OSError:
                self.config['refused_ids'] = refused
        if job:
            verb = 'guardado(s)' if job['kind'] == 'deposit' else 'retirado(s)'
            self.reason = f"Armazem fechado: {job.get('done', 0)} item(ns) {verb}"
        return job

    def step(self, now, chat):
        """Next payload to send for the running job, or None. chat(text) builds a chat frame."""
        job = self.job
        if job is None:
            return None
        if now-job['started'] > JOB_LIMIT:
            self.finish()
            self.reason += ' (tempo esgotado; o armazem sera usado de novo)'
            return None
        if now-job['sent_at'] < SEND_GAP:
            return None
        frames = self.config['frames']
        if job['stage'] == 'opening':
            if job.get('asked') is None:  # always: an "open" state seen earlier may be stale
                job.update(asked=now, sent_at=now)
                return chat('@storage')
            if now-job['asked'] > OPEN_WAIT:
                self.finish()
                self.reason = 'O armazem nao abriu (@storage sem resposta); tentando de novo em seguida'
            return None
        if job['stage'] == 'opened':
            if now-job['at'] < 0.6:
                return None  # the whole list first
            if job['kind'] == 'withdraw' and job['queue'] is None:
                job['queue'] = self.withdraw_queue()
            job['stage'] = 'moving'
        if job['stage'] == 'moving':
            if job.get('waiting') and now-job['sent_at'] < ITEM_WAIT:
                return None
            if job.get('waiting') == 'store' and job.get('item_id') is not None:
                job.setdefault('refused', []).append(job['item_id'])
            job['waiting'] = None  # not confirmed in time: the server refused it, next one
            if job['queue']:
                index, amount, item_id = job['queue'].pop(0)
                key = 'store' if job['kind'] == 'deposit' else 'take'
                job.update(waiting=key, sent_at=now, item_id=item_id)
                return build(frames[key], index, amount)
            job.update(stage='closing', sent_at=now, closing_at=now)
            return build(frames['close'])
        if job['stage'] == 'closing' and now-job['closing_at'] > 3.0:
            self.finish()
        return None

    def snapshot(self):
        return dict(auto_enabled=self.config['auto_enabled'], threshold=self.config['threshold'],
                    refused_ids=self.config['refused_ids'],
                    keep_ids=self.config['keep_ids'], weight=self.weight, max_weight=self.max_weight,
                    open=self.open, learning=self.learning, reason=self.reason, missing=self.missing(),
                    busy=self.job is not None, character=self.character)
