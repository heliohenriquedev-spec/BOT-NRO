"""REDE-57: ammo-only equipment state, confirmed by server responses."""
import re
from .grf import GrfError

AMMO_SLOT = 0x8000


def names_from_grfs(grfs):
    try:
        text = grfs.read('data\\idnum2itemdisplaynametable.txt').decode('cp1252', 'replace')
        return {int(identity): name.replace('_', ' ') for identity, name in re.findall(r'(\d+)#([^#]*)#', text)
                if re.search(r'kunai|shuriken', name, re.I)}
    except (OSError, KeyError, ValueError, GrfError):
        # Optional naming data must never terminate the authenticated transport.
        return {}


class AmmoInventory:
    def __init__(self, names=None):
        self.names = names or {}
        self.reset()

    def reset(self):
        self.items = {}
        self.equipped = None
        self.pending = None
        self.blocked = {}
        self.loaded = False
        self.reason = 'aguardando inventario recebido do servidor'

    def kind(self, item):
        if item.get('type') != 10:
            return None
        name = self.names.get(item['item_id'], '').lower()
        return 524 if 'kunai' in name else 523 if 'shuriken' in name else None

    def observe(self, events, now):
        for event in events:
            kind = event['kind']
            if kind in ('map_change', 'map_transfer'):
                self.reset()
            elif kind == 'inventory_list':
                if event['stackable']:
                    self.items = {i: v for i, v in self.items.items() if not v.get('stackable')}
                    self.loaded = True
                    self.equipped = None
                for item in event['items']:
                    item = {**item, 'stackable': event['stackable']}
                    self.items[item['index']] = item
                    if item.get('equipped', 0) & AMMO_SLOT:
                        self.equipped = item['index']
            elif kind == 'inventory_layout_unknown':
                self.reason = 'formato do inventario nao validado; equipamento automatico bloqueado'
            elif kind == 'inventory_added' and event['success']:
                old = self.items.get(event['index'], {})
                self.items[event['index']] = {**old, **event, 'amount': old.get('amount', 0)+event['amount']}
            elif kind == 'inventory_removed':
                item = self.items.get(event['inventory_index'])
                if item:
                    item['amount'] = max(0, item['amount']-event['amount'])
                    if not item['amount'] and self.equipped == event['inventory_index']:
                        self.equipped = None
            elif kind == 'ammo_equipped':
                self.equipped = event['index'] or None
                self.blocked.pop(event['index'], None)
                if self.pending and self.pending['index'] == self.equipped:
                    self.pending = None
                    self.reason = 'municao equipada confirmada pelo servidor'
            elif kind == 'equipment_ack':
                if event['success'] and event['position'] & AMMO_SLOT:
                    if event['equipped']:
                        self.equipped = event['index']
                        self.blocked.pop(event['index'], None)
                    elif self.equipped == event['index']:
                        self.equipped = None
                if self.pending and self.pending['index'] == event['index'] and event['equipped']:
                    if not event['success'] or not event['position'] & AMMO_SLOT:
                        self.blocked[event['index']] = now+8
                        self.reason = 'servidor recusou equipamento da municao'
                    self.pending = None

    def snapshot(self, now):
        if self.pending and now >= self.pending['deadline']:
            self.blocked[self.pending['index']] = now+8
            self.pending = None
            self.reason = 'equipamento sem confirmacao; tentativa adiada'
        candidates = {}
        for item in self.items.values():
            identity = self.kind(item)
            if identity and item.get('amount', 0) > 0 and self.blocked.get(item['index'], 0) <= now:
                option = {**item, 'name': self.names[item['item_id']], 'ready': item['index'] == self.equipped}
                previous = candidates.get(identity)
                if previous is None or (option['ready'], option['amount']) > (previous['ready'], previous['amount']):
                    candidates[identity] = option
        if not self.pending and candidates:
            self.reason = 'municao identificada; troca somente quando a habilidade estiver pronta'
        elif self.loaded and not self.pending and not candidates:
            self.reason = 'nenhuma municao compativel disponivel' if self.names else 'catalogo de municao nao disponivel'
        return {'loaded': self.loaded, 'options': candidates, 'pending': self.pending,
                'equipped_index': self.equipped, 'reason': self.reason}

    def sent(self, index, now):
        self.pending = {'index': index, 'deadline': now+1.2}
        self.reason = 'aguardando confirmacao de equipamento'
