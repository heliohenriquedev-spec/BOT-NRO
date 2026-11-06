"""Window "Cacar" opened from the monster tab, a monster's drops or an item's droppers.

Pick the map (maps with a recorded path first), check the monsters of that map to kill, set
their priority (1 = first) and the goals. "Ir cacar" sends the bot there and hunts with the
combat settings. A monster's sprite opens its loot list, where @alootid can be turned on item by
item and @autoloot for everything.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .database_hunt import monsters_by_map, routes_by_map


def send_command(widget, command, **values):
    """The main panel's relay command, reached from any window inside it."""
    owner = widget.parent() if widget is not None else None
    while owner is not None:
        target = getattr(owner, 'command', None)
        if callable(target):
            target(command, **values)
            return True
        owner = owner.parent()
    return False


def monster_icon(species_id):
    try:
        from .monster_panel import icon_for
        return icon_for(species_id)
    except (OSError, ValueError):
        from PySide6.QtGui import QIcon
        return QIcon()


def monster_drops(species_ids):
    """Server @mi sheets of these monsters; an unreadable database only hides the choices."""
    try:
        from . import drop_db
        return [d for s in species_ids for d in drop_db.server_drops(species=s)]
    except Exception:  # noqa: BLE001 - sqlite/OS errors must not break the window
        return []


class HuntDialog(QDialog):
    def __init__(self, parent, species_ids, monsters=None, entries=None, drops=monster_drops,
                 current_map=None, destinations=None):
        super().__init__(parent)
        from . import map_routes, monster_db
        self.drops = drops
        self.species_ids = [int(s) for s in species_ids if s]
        self.by_map = monsters_by_map(monster_db.all_monsters() if monsters is None else monsters)
        try:
            entries = map_routes.load() if entries is None else entries
        except (OSError, ValueError):
            entries = []
        self.routes = routes_by_map(entries)
        # Maps reached by the portals crossed before (learned automatically) from where the character is.
        from .auto_routes import load_destinations, reachable
        current_map = current_map or self.current_map()
        self.current = current_map
        from .npc_transports import NpcTransports, as_entries
        transports = as_entries(NpcTransports().known) if destinations is None else []
        self.learned = (reachable(current_map, load_destinations() if destinations is None else destinations, entries+transports)
                        if current_map else set())
        self.setWindowTitle('Cacar')
        self.resize(620, 640)
        layout = QVBoxLayout(self)
        intro = QLabel('O bot vai ate o mapa pelo percurso gravado em "Mapas de caca" e caca os monstros marcados, '
                       'na ordem de prioridade (1 primeiro), com as configuracoes de combate. Clique no sprite de um '
                       'monstro para ver os loots e ligar @alootid / @autoloot.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        row = QHBoxLayout()
        row.addWidget(QLabel('Mapa:'))
        self.map_box = QComboBox()
        maps = sorted({m for m, rows in self.by_map.items() if any(r['species_id'] in self.species_ids for r in rows)},
                      key=lambda m: (not self.known(m), m))
        for name in maps:
            label = ('' if name in self.routes else '  (caminho aprendido pelos portais)' if name in self.learned
                     else '  (sem caminho conhecido)')
            self.map_box.addItem(name+label, name)
        row.addWidget(self.map_box, 1)
        layout.addLayout(row)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Loot', 'Cacar / Monstro', 'ID', 'Prioridade'])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setColumnWidth(0, 54)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)
        goals = QGroupBox('Metas: a caca termina na primeira atingida (todas "sem limite" = ate eu parar)')
        grid = QGridLayout(goals)
        self.kills = QSpinBox(); self.kills.setRange(0, 100000); self.kills.setSpecialValueText('sem limite')
        self.minutes = QSpinBox(); self.minutes.setRange(0, 24*60); self.minutes.setSpecialValueText('sem limite')
        self.item = QComboBox(); self.item.addItem('nenhum item', 0)
        self.amount = QSpinBox(); self.amount.setRange(0, 30000); self.amount.setSpecialValueText('-')
        grid.addWidget(QLabel('Mortes:'), 0, 0); grid.addWidget(self.kills, 0, 1)
        grid.addWidget(QLabel('Minutos caçando no mapa:'), 0, 2); grid.addWidget(self.minutes, 0, 3)
        grid.addWidget(QLabel('Juntar item:'), 1, 0); grid.addWidget(self.item, 1, 1, 1, 2)
        grid.addWidget(QLabel('Quantidade:'), 1, 3); grid.addWidget(self.amount, 1, 4)
        note = QLabel('Mortes = monstros mortos, não "voltas ao mapa". Se o personagem morrer, a caça pausa.')
        note.setWordWrap(True)
        grid.addWidget(note, 2, 0, 1, 5)
        layout.addWidget(goals)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.go = QPushButton('Ir cacar')
        self.go.clicked.connect(self.start)
        close = QPushButton('Fechar')
        close.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(self.go)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.map_box.currentIndexChanged.connect(self.show_map)
        if not maps:
            self.status.setText('Nenhum mapa registrado para este monstro ainda.')
            self.go.setEnabled(False)
        self.show_map()

    def show_map(self, *args):
        name = self.map_box.currentData()
        rows = self.by_map.get(name, []) if name else []
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            loot = QPushButton()
            loot.setIcon(monster_icon(row['species_id']))
            loot.setIconSize(QSize(40, 40))
            loot.setToolTip('Ver os loots e ligar @alootid / @autoloot')
            loot.clicked.connect(lambda checked=False, r=row: self.open_loot(r))
            self.table.setCellWidget(index, 0, loot)
            item = QTableWidgetItem(str(row.get('name') or f"Monstro {row['species_id']}"))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            chosen = row['species_id'] in self.species_ids
            item.setCheckState(Qt.Checked if chosen else Qt.Unchecked)
            item.setData(Qt.UserRole, row['species_id'])
            self.table.setItem(index, 1, item)
            self.table.setItem(index, 2, QTableWidgetItem(str(row['species_id'])))
            priority = QSpinBox()
            priority.setRange(1, 99)
            priority.setValue(1 if chosen else 5)
            self.table.setCellWidget(index, 3, priority)
        self.fill_items(rows)
        if name and not self.known(name):
            self.status.setText(f'Ainda nao ha caminho conhecido ate {name}. Entre uma vez nos portais ate la (o bot '
                                'aprende sozinho cada portal) ou grave o percurso em Rotas > Mapas de caca.')
        elif name in self.routes:
            self.status.setText(f"Percurso gravado: {self.routes[name].get('name') or name}")
        elif name:
            self.status.setText(f'Caminho aprendido pelos portais, saindo de {self.current}.')
        self.go.setEnabled(bool(name) and self.known(name))

    def known(self, name):
        return name in self.routes or name in self.learned

    def current_map(self):
        """The character's map, from the main panel's last state."""
        owner = self.parent()
        while owner is not None:
            state = getattr(owner, 'last_state', None)
            if isinstance(state, dict) and state.get('map_name'):
                return state['map_name']
            owner = owner.parent()
        return None

    def fill_items(self, rows):
        """Item goal choices: what the map's monsters drop."""
        current = self.item.currentData()
        self.item.clear()
        self.item.addItem('nenhum item', 0)
        seen = set()
        for drop in self.drops([r['species_id'] for r in rows]):
            if drop.get('item_id') and drop['item_id'] not in seen:
                seen.add(drop['item_id'])
                self.item.addItem(f"{drop['item_name']} ({drop['item_id']})", drop['item_id'])
        self.item.setCurrentIndex(max(0, self.item.findData(current)))

    def open_loot(self, row):
        LootDialog(self, row, self.drops([row['species_id']])).exec()

    def request(self):
        """The relay command's values for the current choice."""
        species, priority = [], {}
        for index in range(self.table.rowCount()):
            item = self.table.item(index, 1)
            if item.checkState() == Qt.Checked:
                identity = int(item.data(Qt.UserRole))
                species.append(identity)
                priority[str(identity)] = self.table.cellWidget(index, 3).value()
        name = self.map_box.currentData()
        route = self.routes.get(name) or {}
        item_id = self.item.currentData() or 0
        return dict(target_map=name or '', map_route_id=route.get('id', ''), species=species, priority=priority,
                    kills=self.kills.value(), goal_minutes=self.minutes.value(),
                    goal_item_id=item_id, goal_item_amount=self.amount.value() if item_id else 0,
                    goal_item_name=self.item.currentText().rsplit(' (', 1)[0] if item_id else '')

    def start(self):
        values = self.request()
        if not values['species']:
            self.status.setText('Marque ao menos um monstro.')
            return
        if values['goal_item_id'] and not values['goal_item_amount']:
            self.status.setText('Informe a quantidade do item da meta.')
            return
        if not send_command(self, 'quest_hunt_database', **values):
            self.status.setText('Abra a conexao pelo painel principal para cacar.')
            return
        self.status.setText('Pedido enviado: acompanhe na aba Rotas.')
        self.accept()


class LootDialog(QDialog):
    """A monster's loot: @alootid item by item, or @autoloot for everything."""

    def __init__(self, parent, row, drops):
        super().__init__(parent)
        self.drops_list = [d for d in drops if d.get('item_id')]
        name = row.get('name') or f"Monstro {row['species_id']}"
        self.setWindowTitle(f'Loots de {name}')
        self.resize(560, 460)
        layout = QVBoxLayout(self)
        general = QHBoxLayout()
        for label, text in (('Ligar @autoloot (tudo)', '@autoloot 100'), ('Desligar @autoloot', '@autoloot 0'),
                            ('Limpar lista do @alootid', '@alootid reset')):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, t=text: self.send(t))
            general.addWidget(button)
        layout.addLayout(general)
        self.table = QTableWidget(len(drops), 4)
        self.table.setHorizontalHeaderLabels(['Item', 'ID', 'Chance', '@alootid'])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for index, drop in enumerate(drops):
            self.table.setItem(index, 0, QTableWidgetItem(str(drop['item_name'])))
            self.table.setItem(index, 1, QTableWidgetItem(str(drop.get('item_id') or '?')))
            self.table.setItem(index, 2, QTableWidgetItem(f"{drop['rate']:.2f}%" if drop.get('rate') is not None else '-'))
            if drop.get('item_id'):
                button = QPushButton('Pegar este')
                button.clicked.connect(lambda checked=False, i=drop['item_id']: self.send(f'@alootid +{i}'))
                self.table.setCellWidget(index, 3, button)
        layout.addWidget(self.table, 1)
        everything = QPushButton('Pegar todos desta lista (@alootid em cada um)')
        everything.clicked.connect(self.send_all)
        everything.setEnabled(bool(self.drops_list))
        layout.addWidget(everything)
        self.status = QLabel('Os comandos vão ao chat do jogo, um por vez.' if drops else
                             'Sem loots registrados: consulte o @mi deste monstro na Database (aba "Por monstro").')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        close = QPushButton('Fechar')
        close.clicked.connect(self.accept)
        layout.addWidget(close)

    def send_all(self):
        for drop in self.drops_list:
            self.send(f"@alootid +{drop['item_id']}")

    def send(self, text):
        if send_command(self, 'loot_command', text=text):
            self.status.setText('Enviado ao bot: '+text)
        else:
            self.status.setText('Abra a conexao pelo painel principal para enviar comandos.')
