"""REDE-67/68: target capture and the user-defined skill priority list."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox, QCheckBox,
                               QListWidget, QListWidgetItem, QAbstractItemView, QTableWidget,
                               QTableWidgetItem, QHeaderView)

THROWS = 'throws'
THROW_IDS = (523, 524)


class PriorityPanel(QWidget):
    apply_requested = Signal()
    capture_requested = Signal()
    release_requested = Signal()
    target_requested = Signal(int)
    changed = Signal()  # reordering: the panel saves it by itself

    def __init__(self, priority=None):
        super().__init__()
        self.saved = list(priority or [])
        self.available = None
        layout = QVBoxLayout(self)

        target_box = QGroupBox('1º  Alvo')
        target_layout = QVBoxLayout(target_box)
        target_layout.addWidget(QLabel('Alvo próximo: o monstro mais perto é escolhido. Um jogador capturado tem prioridade enquanto estiver visível.'))
        buttons = QHBoxLayout()
        capture = QPushButton('Capturar jogador com o mouse do jogo')
        capture.setToolTip('Traz o jogo para a frente; passe o mouse do próprio jogo sobre o jogador (ou clique nele) nos próximos 20 s.')
        capture.clicked.connect(self.capture_requested.emit)
        buttons.addWidget(capture)
        choose = QPushButton('Tornar alvo o jogador selecionado na lista')
        choose.clicked.connect(self.choose_selected)
        buttons.addWidget(choose)
        release = QPushButton('Soltar jogador')
        release.clicked.connect(self.release_requested.emit)
        buttons.addWidget(release)
        target_layout.addLayout(buttons)
        self.minimap = QCheckBox('Mostrar o minimapa no canto do jogo (rota feita, pontos que faltam, jogadores e hide)')
        self.minimap.setChecked(True)
        target_layout.addWidget(self.minimap)
        self.capture_label = QLabel('Nenhum jogador capturado')
        self.capture_label.setWordWrap(True)
        target_layout.addWidget(self.capture_label)
        self.players = QTableWidget(0, 4)
        self.players.setHorizontalHeaderLabels(['Jogador', 'ID', 'Distância', 'Situação'])
        self.players.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.players.setEditTriggers(QTableWidget.NoEditTriggers)
        self.players.setSelectionBehavior(QTableWidget.SelectRows)
        self.players.setMaximumHeight(170)
        target_layout.addWidget(self.players)
        layout.addWidget(target_box)

        order_box = QGroupBox('Depois do alvo: ordem das habilidades (usadas em ciclo nesta ordem; a que não estiver pronta ou no alcance é pulada)')
        order_layout = QHBoxLayout(order_box)
        self.order = QListWidget()
        self.order.setDragDropMode(QAbstractItemView.InternalMove)
        self.order.setDefaultDropAction(Qt.MoveAction)
        self.order.model().rowsMoved.connect(lambda *args: self.changed.emit())
        order_layout.addWidget(self.order, 1)
        side = QVBoxLayout()
        for label, step in (('▲ Subir', -1), ('▼ Descer', 1)):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, s=step: self.move(s))
            side.addWidget(button)
        side.addStretch()
        apply = QPushButton('Salvar e aplicar • pausa a caça')
        apply.clicked.connect(self.apply_requested.emit)
        side.addWidget(apply)
        order_layout.addLayout(side)
        layout.addWidget(order_box, 1)
        note = QLabel('Arraste ou use Subir/Descer. Aparecem as habilidades marcadas em "Usar" na aba Habilidades. '
                      'Kunai e Shuriken formam uma única entrada e continuam alternando entre si.')
        note.setWordWrap(True)
        layout.addWidget(note)

    @staticmethod
    def tokens_for(profiles):
        tokens = []
        for profile in profiles:
            if not profile.get('enabled'):
                continue
            token = THROWS if profile['skill_id'] in THROW_IDS else profile['skill_id']
            if token not in tokens:
                tokens.append(token)
        return tokens

    def sync(self, profiles, names):
        """Rebuild only when the set of usable skills changes, keeping manual reordering."""
        tokens = self.tokens_for(profiles)
        current = self.priority() if self.available is not None else self.saved
        ordered = [t for t in current if t in tokens]+[t for t in tokens if t not in current]
        if self.available == set(tokens) and self.order.count() == len(ordered):
            for index in range(self.order.count()):
                item = self.order.item(index)
                item.setText(self.label(item.data(Qt.UserRole), names))
            return
        self.available = set(tokens)
        self.order.clear()
        for token in ordered:
            item = QListWidgetItem(self.label(token, names))
            item.setData(Qt.UserRole, token)
            self.order.addItem(item)

    @staticmethod
    def label(token, names):
        if token == THROWS:
            return 'Kunai e Shuriken (alternadas)'
        return f"{names.get(token) or 'Habilidade'} (ID {token})"

    def priority(self):
        if self.available is None:
            return list(self.saved)
        shown = [self.order.item(index).data(Qt.UserRole) for index in range(self.order.count())]
        # Skills this character does not have keep their place in the saved order.
        return shown+[token for token in self.saved if token not in shown]

    def move(self, step):
        row = self.order.currentRow()
        target = row+step
        if row < 0 or not 0 <= target < self.order.count():
            return
        item = self.order.takeItem(row)
        self.order.insertItem(target, item)
        self.order.setCurrentRow(target)
        self.changed.emit()

    def choose_selected(self):
        row = self.players.currentRow()
        item = self.players.item(row, 1) if row >= 0 else None
        if item is None:
            self.capture_label.setText('Selecione um jogador na lista primeiro.')
            return
        self.target_requested.emit(int(item.text()))

    def update_targets(self, state):
        captured = state.get('captured_player')
        if state.get('capture_armed'):
            text = 'Captura armada: passe o mouse do jogo sobre o jogador ou clique nele (20 s).'
        elif captured:
            text = f"Alvo capturado: {captured.get('name') or 'nome não recebido'} (ID {captured['entity_id']}, por {captured['origin']})"
        else:
            text = 'Nenhum jogador capturado'
        if self.capture_label.text() != text:
            self.capture_label.setText(text)
        rows = state.get('players_nearby') or []
        self.players.setRowCount(len(rows))
        for row, player in enumerate(rows):
            values = [player.get('name') or 'nome não recebido', player['entity_id'],
                      '—' if player.get('distance') is None else f"{player['distance']} células",
                      'Alvo capturado' if player.get('captured') else '']
            for column, value in enumerate(values):
                text = str(value)
                item = self.players.item(row, column)
                if item is None:
                    self.players.setItem(row, column, QTableWidgetItem(text))
                elif item.text() != text:
                    item.setText(text)
