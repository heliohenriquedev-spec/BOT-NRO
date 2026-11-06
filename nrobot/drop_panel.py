"""Items and the monsters that drop them (server @mi sheets plus what was seen falling).

Tables are only rebuilt when the database changes on disk or the search changes: rebuilding
them every 2 s with columns sized to contents took ~9 s per refresh and froze the window."""
import json
import sqlite3

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QTabWidget, QWidget)

from . import drop_db


def chance(source):
    if source['rate'] is not None:
        return f"{source['rate']:.2f}%" + (' (MVP)' if source['mvp'] else '')
    return f"visto {source['seen']}x" if source['seen'] else '—'


def fill(table, rows):
    """Writes rows of text in one pass; columns are sized once, on the first fill."""
    table.setUpdatesEnabled(False)
    try:
        table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(str(value)))
        if not table.property('sized') and rows:
            table.resizeColumnsToContents()
            table.setProperty('sized', True)
    finally:
        table.setUpdatesEnabled(True)


def make_table(headers, stretch=()):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setSelectionMode(QTableWidget.SingleSelection)
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.Interactive)
    for column in stretch:
        header.setSectionResizeMode(column, QHeaderView.Stretch)
    return table


class ItemSourcesDialog(QDialog):
    """Every monster that drops one item, with its own chance."""

    def __init__(self, parent, item):
        super().__init__(parent)
        self.setWindowTitle(f"Quem dropa {item['item_name']} ({item['item_id'] or '?'})")
        self.resize(760, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Chance informada pelo servidor (@mi); "Vistos" conta os drops associados a cada monstro '
                                'nas observacoes do jogo. Monstros sem chance ainda nao tiveram a ficha @mi consultada.'))
        from .monster_db import all_monsters
        maps = {m['species_id']: sorted(set(m.get('maps') or []) | set(m.get('seen_maps') or [])) for m in all_monsters()}
        table = make_table(['Monstro', 'ID', 'Chance', 'Vistos', 'Mapas'], stretch=(4,))
        fill(table, [[s['monster_name'] or f"Monstro {s['species_id']}", s['species_id'], chance(s), s['seen'],
                      ', '.join(maps.get(s['species_id'], [])[:8]) or '—'] for s in item['sources']])
        layout.addWidget(table, 1)
        self.sources, self.table = item['sources'], table
        buttons = QHBoxLayout(); layout.addLayout(buttons)
        hunt = QPushButton('Cacar monstro selecionado'); hunt.clicked.connect(self.hunt); buttons.addWidget(hunt)
        buttons.addStretch(1)
        close = QPushButton('Fechar'); close.clicked.connect(self.accept)
        buttons.addWidget(close)

    def hunt(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.sources):
            row = 0 if len(self.sources) == 1 else -1
        if row < 0:
            return
        from .hunt_dialog import HuntDialog
        HuntDialog(self, [self.sources[row]['species_id']]).exec()


class DropDatabaseDialog(QDialog):
    def __init__(self, parent=None, species=None):
        super().__init__(parent)
        self.species, self.entries, self.items, self.stamp, self.query = species, [], [], None, None
        self.setWindowTitle('Database de itens e drops' + (f' — monstro {species}' if species else ''))
        self.resize(1050, 600)
        layout = QVBoxLayout(self)
        self.search = QLineEdit(); self.search.setPlaceholderText('Buscar item, ID, monstro ou mapa')
        self.typing = QTimer(self); self.typing.setSingleShot(True); self.typing.setInterval(300)
        self.typing.timeout.connect(self.reload)
        self.search.textChanged.connect(self.typing.start)
        layout.addWidget(self.search)
        if species:
            hunt = QPushButton('Cacar este monstro')
            hunt.clicked.connect(self.hunt)
            layout.addWidget(hunt)
        self.summary = QLabel(); layout.addWidget(self.summary)
        tabs = QTabWidget(); layout.addWidget(tabs, 1)

        items = QWidget(); items_layout = QVBoxLayout(items)
        items_layout.addWidget(QLabel('Cada item com os monstros de maior chance. Duplo clique: todos os monstros que '
                                      'dropam o item e a chance de cada um.'))
        self.item_table = make_table(['ID item', 'Item', 'Maior chance', '2ª', '3ª', 'Monstros'], stretch=(1,))
        self.item_table.doubleClicked.connect(self.open_item)
        items_layout.addWidget(self.item_table, 1)
        tabs.addTab(items, 'Itens')

        server = QWidget(); server_layout = QVBoxLayout(server)
        server_note = QLabel('Lista enviada pelo servidor com o comando @mi ID (taxas do servidor, inclusive itens raros). '
                             'O bot consulta sozinho cada monstro novo que aparece, uma vez, com intervalo entre os comandos.')
        server_note.setWordWrap(True); server_layout.addWidget(server_note)
        ask = QHBoxLayout(); server_layout.addLayout(ask)
        ask.addWidget(QLabel('ID do monstro:'))
        self.species_box = QSpinBox(); self.species_box.setRange(1, 99999); self.species_box.setValue(species or 1002)
        ask.addWidget(self.species_box)
        query = QPushButton('Consultar @mi agora'); query.clicked.connect(self.ask_server); ask.addWidget(query)
        ask.addStretch(1)
        self.server_table = make_table(['ID monstro', 'Monstro', 'ID item', 'Item', 'Chance', 'Tipo', 'Vistos'], stretch=(3,))
        server_layout.addWidget(self.server_table, 1)
        tabs.addTab(server, 'Por monstro (@mi)')

        observed = QWidget(); observed_layout = QVBoxLayout(observed)
        note = QLabel('Coleta passiva: itens no chao, mortes observadas e possiveis associacoes. Proximidade nao prova '
                      'origem: jogadores tambem podem jogar itens no chao. Confirme um vinculo somente apos conferir no jogo.')
        note.setWordWrap(True); observed_layout.addWidget(note)
        self.table = make_table(['ID item', 'Item', 'ID monstro', 'Monstro observado', 'Mapa',
                                 'Observacoes', 'Quantidade', 'Evidencia', 'Estado'], stretch=(1, 3))
        observed_layout.addWidget(self.table, 1)
        buttons = QHBoxLayout(); observed_layout.addLayout(buttons)
        review = QPushButton('Confirmar vinculo conferido no jogo'); review.clicked.connect(self.review); buttons.addWidget(review)
        export = QPushButton('Exportar consulta JSON'); export.clicked.connect(self.export); buttons.addWidget(export)
        tabs.addTab(observed, 'Observacoes no jogo')

        self.timer = QTimer(self); self.timer.setInterval(2000); self.timer.timeout.connect(self.refresh)
        self.reload()

    def hunt(self):
        from .hunt_dialog import HuntDialog
        HuntDialog(self, [self.species]).exec()

    def showEvent(self, event):
        super().showEvent(event); self.timer.start()

    def hideEvent(self, event):
        self.timer.stop(); super().hideEvent(event)

    def refresh(self):
        """Every 2 s: only a database written meanwhile rebuilds the tables."""
        if drop_db.data_stamp() != self.stamp:
            self.reload()

    def reload(self):
        text = self.search.text()
        self.stamp = drop_db.data_stamp()
        try:
            self.items = drop_db.item_overview(text, self.species)
            self.entries = drop_db.rows(text, self.species)
            official = drop_db.server_drops(text, self.species)
        except (sqlite3.Error, OSError) as exc:
            self.summary.setText('Database temporariamente indisponivel: '+str(exc)); return
        best = lambda item, n: (f"{item['sources'][n]['monster_name']} {chance(item['sources'][n])}"
                                if len(item['sources']) > n else '')
        fill(self.item_table, [[i['item_id'] or '?', i['item_name'], best(i, 0), best(i, 1), best(i, 2), len(i['sources'])]
                               for i in self.items])
        fill(self.server_table, [[e['species_id'], e['monster_name'], e['item_id'] or '?', e['item_name'],
                                  f"{e['rate']:.2f}%", 'MVP' if e['mvp'] else 'Drop', e['seen']] for e in official])
        status = {'candidate': 'Candidato; revisar', 'reviewed': 'Revisado pelo usuario', 'unlinked': 'Sem vinculo'}
        fill(self.table, [[e['item_id'], e['item_name'], e['species_id'] or '—', e['monster_name'] or 'Nao identificado',
                           e['map'], e['observations'], e['quantity'],
                           'Morte proxima no tempo e espaco' if e['species_id'] else (
                               'Inventario; origem nao informada' if e['source'] == 'inventory' else
                               'Item novo no chao' if e['fresh'] else 'Ja estava no chao'),
                           status[e['status']]] for e in self.entries])
        monsters = len({e['species_id'] for e in official})
        self.summary.setText(f'{len(self.items)} itens • {len(official)} drops do servidor ({monsters} monstros) • '
                             f'{len(self.entries)} registros observados (limite 500).')

    def open_item(self, index):
        if 0 <= index.row() < len(self.items):
            ItemSourcesDialog(self, self.items[index.row()]).exec()

    def ask_server(self):
        owner = self.parent().window() if self.parent() is not None else None
        command = getattr(owner, 'command', None)
        if command is None:
            self.summary.setText('Abra a conexao pelo painel principal para consultar o servidor.'); return
        command('mob_info', species_id=self.species_box.value())
        self.summary.setText(f'Consulta @mi {self.species_box.value()} enviada ao bot; o resultado aparece aqui em alguns segundos.')

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
