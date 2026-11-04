"""Read-only observations plus explicit human review of possible monster/item links."""
import json
import sqlite3

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QTabWidget, QWidget)

from . import drop_db


class DropDatabaseDialog(QDialog):
    def __init__(self, parent=None, species=None):
        super().__init__(parent)
        self.species, self.entries = species, []
        self.setWindowTitle('Database de itens e drops')
        self.resize(1050, 600)
        layout = QVBoxLayout(self)
        note = QLabel('Coleta passiva: itens no chao, mortes observadas e possiveis associacoes. Proximidade nao prova '
                      'origem: jogadores tambem podem jogar itens no chao. Confirme um vinculo somente apos conferir no jogo. '
                      'Contagens observadas nao sao taxas oficiais de drop.')
        note.setWordWrap(True); layout.addWidget(note)
        self.search = QLineEdit(); self.search.setPlaceholderText('Buscar item, ID, monstro ou mapa')
        self.search.textChanged.connect(self.reload); layout.addWidget(self.search)
        self.summary = QLabel(); layout.addWidget(self.summary)
        tabs = QTabWidget(); layout.addWidget(tabs, 1)
        server = QWidget(); server_layout = QVBoxLayout(server)
        server_note = QLabel('Lista completa enviada pelo servidor com o comando @mi ID (taxas do servidor, inclusive itens raros). '
                             'O bot consulta sozinho cada monstro novo que aparece, uma vez, com intervalo entre os comandos. '
                             '"Vistos" conta os drops associados a esse monstro nas observacoes.')
        server_note.setWordWrap(True); server_layout.addWidget(server_note)
        ask = QHBoxLayout(); server_layout.addLayout(ask)
        ask.addWidget(QLabel('ID do monstro:'))
        self.species_box = QSpinBox(); self.species_box.setRange(1, 99999); self.species_box.setValue(species or 1002)
        ask.addWidget(self.species_box)
        query = QPushButton('Consultar @mi agora'); query.clicked.connect(self.ask_server); ask.addWidget(query)
        ask.addStretch(1)
        self.server_table = QTableWidget(0, 7)
        self.server_table.setHorizontalHeaderLabels(['ID monstro', 'Monstro', 'ID item', 'Item', 'Chance', 'Tipo', 'Vistos'])
        self.server_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.server_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.server_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.server_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        server_layout.addWidget(self.server_table, 1)
        tabs.addTab(server, 'Drops do servidor (@mi)')
        observed = QWidget(); observed_layout = QVBoxLayout(observed); observed_layout.setContentsMargins(0, 0, 0, 0)
        tabs.addTab(observed, 'Observacoes no jogo')
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(['ID item', 'Item', 'ID monstro', 'Monstro observado', 'Mapa',
                                             'Observacoes', 'Quantidade', 'Evidencia', 'Estado'])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        observed_layout.addWidget(self.table, 1)
        buttons = QHBoxLayout(); observed_layout.addLayout(buttons)
        review = QPushButton('Confirmar vinculo conferido no jogo'); review.clicked.connect(self.review); buttons.addWidget(review)
        export = QPushButton('Exportar consulta JSON'); export.clicked.connect(self.export); buttons.addWidget(export)
        refresh = QPushButton('Atualizar'); refresh.clicked.connect(self.reload); buttons.addWidget(refresh)
        self.timer = QTimer(self); self.timer.setInterval(2000); self.timer.timeout.connect(self.reload)
        self.reload()

    def showEvent(self, event):
        super().showEvent(event); self.timer.start()

    def hideEvent(self, event):
        self.timer.stop(); super().hideEvent(event)

    def reload(self):
        selected = self.table.currentRow()
        key = self.key(self.entries[selected]) if 0 <= selected < len(self.entries) else None
        try:
            self.entries = drop_db.rows(self.search.text(), self.species)
        except (sqlite3.Error, OSError) as exc:
            self.summary.setText('Database temporariamente indisponivel: '+str(exc)); return
        self.table.setRowCount(len(self.entries))
        for row, entry in enumerate(self.entries):
            status = {'candidate': 'Candidato; revisar', 'reviewed': 'Revisado pelo usuario', 'unlinked': 'Sem vinculo'}[entry['status']]
            evidence = 'Morte proxima no tempo e espaco' if entry['species_id'] else (
                'Inventario; origem nao informada' if entry['source'] == 'inventory' else
                'Item novo no chao' if entry['fresh'] else 'Ja estava no chao')
            values = [entry['item_id'], entry['item_name'], entry['species_id'] or '—', entry['monster_name'] or 'Nao identificado',
                      entry['map'], entry['observations'], entry['quantity'], evidence, status]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
            if self.key(entry) == key:
                self.table.selectRow(row)
        try:
            official = drop_db.server_drops(self.search.text(), self.species)
        except (sqlite3.Error, OSError):
            official = []
        self.server_table.setRowCount(len(official))
        for row, entry in enumerate(official):
            values = [entry['species_id'], entry['monster_name'], entry['item_id'] or '?', entry['item_name'],
                      f"{entry['rate']:.2f}%", 'MVP' if entry['mvp'] else 'Drop', entry['seen']]
            for column, value in enumerate(values):
                self.server_table.setItem(row, column, QTableWidgetItem(str(value)))
        monsters = len({entry['species_id'] for entry in official})
        self.summary.setText(f'{len(official)} drops do servidor ({monsters} monstros) e {len(self.entries)} registros observados '
                             '(limite 500). Coleta enquanto conectado, mesmo com a caca pausada.')

    def ask_server(self):
        owner = self.parent().window() if self.parent() is not None else None
        command = getattr(owner, 'command', None)
        if command is None:
            self.summary.setText('Abra a conexao pelo painel principal para consultar o servidor.'); return
        command('mob_info', species_id=self.species_box.value())
        self.summary.setText(f'Consulta @mi {self.species_box.value()} enviada ao bot; o resultado aparece aqui em alguns segundos.')

    @staticmethod
    def key(entry):
        return entry['item_id'], entry['species_id'], entry['monster_name'], entry['map'], entry['status'], entry['source']

    def review(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.entries):
            self.summary.setText('Selecione um vinculo candidato primeiro.'); return
        try:
            drop_db.review(self.entries[row]); self.reload()
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.summary.setText(str(exc))

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Exportar database consultada', 'itens_drops.json', 'JSON (*.json)')
        if not path:
            return
        try:
            from pathlib import Path
            Path(path).write_text(json.dumps({'note': 'Associacoes candidatas nao provam origem nem taxa de drop.',
                                             'records': self.entries}, ensure_ascii=False, indent=2), encoding='utf-8')
            self.summary.setText('Consulta exportada.')
        except OSError as exc:
            self.summary.setText(str(exc))
