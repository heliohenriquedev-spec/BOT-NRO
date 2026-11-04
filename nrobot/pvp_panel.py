"""Aba PvP: the players on screen, each with "Alvo" (the automatic battle attacks it) and
"Prioridade" (attacked before everything else; one player at a time).

The priority only exists for someone on screen: the relay drops it by itself when that player
leaves the view or hides for a few seconds, or the map changes."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

TARGET, PRIORITY, NAME, IDENTITY, DISTANCE = range(5)


class PvpTargets(QWidget):
    targets_changed = Signal()       # the "Alvo" checks: saved with the settings
    priority_requested = Signal(int)  # a player checked as priority
    priority_cleared = Signal()
    capture_requested = Signal()

    def __init__(self):
        super().__init__()
        self.targets = set()
        self.rows = None
        self.priority = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel('Jogadores visíveis no mapa atual. "Alvo": a batalha automática ataca (movimento, ataques '
                                'e habilidades da rotação, como nos monstros). "Prioridade": atacado antes de todos, '
                                'um jogador por vez; sai sozinha quando ele deixa a tela por 3 s, entra em @hide ou o mapa muda.'))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Alvo', 'Prioridade', 'Jogador', 'ID', 'Distância'])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(NAME, QHeaderView.Stretch)
        self.table.itemChanged.connect(self.item_changed)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        capture = QPushButton('Prioridade pelo mouse do jogo')
        capture.setToolTip('Traz o jogo para a frente; passe o mouse do jogo sobre o jogador (ou clique nele) nos próximos 20 s.')
        capture.clicked.connect(self.capture_requested.emit)
        buttons.addWidget(capture)
        clear = QPushButton('Remover prioridade')
        clear.clicked.connect(self.priority_cleared.emit)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.status = QLabel('Sem prioridade.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def set_targets(self, targets):
        self.targets = set(targets)
        self.rows = None

    @staticmethod
    def check(checked):
        item = QTableWidgetItem()
        item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        return item

    def update_state(self, state):
        state = state or {}
        players = state.get('players_nearby') or []
        captured = state.get('captured_player')
        self.priority = captured['entity_id'] if captured else None
        if state.get('capture_armed'):
            text = 'Prioridade pelo mouse armada: passe o mouse do jogo sobre o jogador ou clique nele (20 s).'
        elif captured:
            text = (f"Prioridade: {captured.get('name') or 'nome não recebido'} (ID {captured['entity_id']}). "
                    'Sai sozinha quando ele deixa a tela.')
        else:
            text = 'Sem prioridade.'
        if self.status.text() != text:
            self.status.setText(text)
        rows = [(p['entity_id'], p.get('name'), p.get('distance'), p['entity_id'] in self.targets,
                 p['entity_id'] == self.priority) for p in players]
        if rows == self.rows:
            return
        self.rows = rows
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(rows))
            for row, (identity, name, distance, target, priority) in enumerate(rows):
                self.table.setItem(row, TARGET, self.check(target))
                self.table.setItem(row, PRIORITY, self.check(priority))
                self.table.setItem(row, NAME, QTableWidgetItem(name or 'nome não recebido'))
                self.table.setItem(row, IDENTITY, QTableWidgetItem(str(identity)))
                self.table.setItem(row, DISTANCE, QTableWidgetItem('—' if distance is None else f'{distance} células'))
        finally:
            self.table.blockSignals(False)

    def identity(self, row):
        item = self.table.item(row, IDENTITY)
        return int(item.text()) if item is not None else None

    def item_changed(self, item):
        identity = self.identity(item.row())
        if identity is None:
            return
        checked = item.checkState() == Qt.Checked
        if item.column() == TARGET:
            (self.targets.add if checked else self.targets.discard)(identity)
            self.rows = None
            self.targets_changed.emit()
        elif item.column() == PRIORITY:
            self.rows = None  # the next state shows what the relay accepted
            if checked:
                self.priority_requested.emit(identity)
            elif identity == self.priority:
                self.priority_cleared.emit()
