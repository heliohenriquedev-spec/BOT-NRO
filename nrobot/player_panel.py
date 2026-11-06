"""Aba Jogadores: every character ever seen, searchable; those in view right now come first.

The relay keeps data/jogadores/registro.json; this tab only reads it and marks the ids the
current state reports as present. It also edits the lista de observação and, on every panel
refresh (tab open or not), reports watched characters newly found, @hide included.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QCheckBox, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import player_registry, watchlist
from .monster_panel import plain


@lru_cache(maxsize=1)
def job_names():
    """{class id: (male name, female name)} from the client's own pcjobnamegender table."""
    from .game_folder import saved
    from .grf import GrfSet
    from .lua_tables import tables
    folder = saved()
    if folder is None:
        return {}
    data = GrfSet(str(folder)).read('data\\lua files\\datainfo\\pcjobnamegender.lub')
    table = tables(data)
    identities = json.loads((Path(__file__).resolve().parents[1]/'data/rede/identidades_cliente.json')
                            .read_text(encoding='utf-8'))['identidades']
    men, women = table.get('PCJobNameTableMan', {}), table.get('PCJobNameTableWoman', {})
    return {identities[key]: (name, women.get(key, name)) for key, name in men.items() if key in identities}


class PlayerPanel(QWidget):
    HEADERS = ['Na tela', 'Observado', 'Nome', 'ID', 'Nível', 'Sexo', 'Classe', 'Guilda', 'Cargo', 'Grupo', 'Último mapa',
               'Última célula', 'Visto', 'Primeira vez', 'Última vez', 'Observações']

    def __init__(self):
        super().__init__()
        self.stamp = None
        self.players = {}
        self.present = set()
        self.names = {}
        self.watch = watchlist.load()
        self.alerted = {}  # entity id -> detection kind already alerted
        layout = QVBoxLayout(self)
        watch_box = QGroupBox('Lista de observação: alerta na tela quando for identificado (inclusive em @hide)')
        watch_layout = QHBoxLayout(watch_box)
        editor = QVBoxLayout()
        self.observe_enabled = QCheckBox('Ativar observacao: pausar e alertar sobre jogadores da lista')
        self.observe_enabled.setChecked(watchlist.enabled())
        self.observe_enabled.toggled.connect(self.toggle_observation)
        editor.addWidget(self.observe_enabled)
        add_row = QHBoxLayout()
        self.watch_input = QLineEdit()
        self.watch_input.setPlaceholderText('ID ou nome exato do personagem')
        self.watch_input.returnPressed.connect(self.add_watch)
        add_row.addWidget(self.watch_input, 1)
        add = QPushButton('Adicionar')
        add.clicked.connect(self.add_watch)
        add_row.addWidget(add)
        editor.addLayout(add_row)
        selected = QPushButton('Observar jogador selecionado na tabela')
        selected.clicked.connect(self.watch_selected)
        editor.addWidget(selected)
        remove = QPushButton('Remover da lista')
        remove.clicked.connect(self.remove_watch)
        editor.addWidget(remove)
        self.watch_status = QLabel('Ninguém da lista identificado agora.')
        self.watch_status.setWordWrap(True)
        editor.addWidget(self.watch_status)
        chat_note = QLabel('Mensagens no chat geral ou privado emitem alerta visual e sonoro somente '
                           'quando enviadas por jogadores desta lista de observacao.')
        chat_note.setWordWrap(True)
        editor.addWidget(chat_note)
        editor.addStretch()
        watch_layout.addLayout(editor, 1)
        self.watch_list = QListWidget()
        self.watch_list.setMaximumHeight(120)
        watch_layout.addWidget(self.watch_list, 1)
        layout.addWidget(watch_box)
        self.show_watch()
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Buscar por nome, ID, guilda, classe ou mapa…')
        self.search.textChanged.connect(self.fill)
        top.addWidget(self.search, 1)
        self.only_present = QCheckBox('Somente na tela agora')
        self.only_present.toggled.connect(self.fill)
        top.addWidget(self.only_present)
        layout.addLayout(top)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        # Sized once per fill: ResizeToContents re-measured every row on each cell written,
        # and the table is refilled whenever someone enters or leaves the screen.
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.sized = False
        self.shown_rows = None
        layout.addWidget(self.table, 1)
        threading.Thread(target=self.load_job_names, daemon=True).start()

    def load_job_names(self):
        try:
            self.names = job_names()
        except Exception as error:  # class names are a convenience: ids stay visible
            print(f'Nomes de classe indisponiveis: {error}')

    def update_state(self, state):
        presence = (state or {}).get('presence') or {}
        present = set(presence.get('players', [])) | {row['entity_id'] for row in (state or {}).get('players_nearby', [])}
        try:
            info = player_registry.FILE.stat()
            stamp = (info.st_mtime_ns, info.st_size)
        except OSError:
            stamp = None
        if stamp != self.stamp:
            self.stamp, self.players = stamp, player_registry.load()
            self.show_watch()  # ids in the list get their names
        elif present == self.present:
            return
        self.present = present
        if self.isVisible():
            self.fill()

    def showEvent(self, event):
        super().showEvent(event)
        self.fill()

    # -- lista de observação ------------------------------------------------------------
    def show_watch(self):
        self.watch_list.clear()
        for entry in self.watch:
            known = self.players.get(entry) if entry.isdigit() else None
            label = f"{entry} ({known['name']})" if known and known.get('name') else entry
            item = QListWidgetItem(label, self.watch_list)
            item.setData(Qt.UserRole, entry)

    def set_watch(self, entries):
        self.watch = list(dict.fromkeys(e.strip() for e in entries if e.strip()))
        watchlist.save(self.watch)
        self.alerted.clear()  # a new entry already in view is alerted right away
        self.show_watch()
        self.fill()

    def toggle_observation(self, enabled):
        try:
            watchlist.set_enabled(enabled)
            self.alerted.clear()
            if not enabled:
                self.watch_status.setText('Observacao desligada: jogadores cadastrados nao pausam nem emitem alertas.')
        except OSError as exc:
            self.observe_enabled.blockSignals(True)
            self.observe_enabled.setChecked(not enabled)
            self.observe_enabled.blockSignals(False)
            self.watch_status.setText('Nao foi possivel salvar: '+str(exc))

    def add_watch(self):
        text = self.watch_input.text().strip()
        if text:
            self.set_watch(self.watch+[text])
            self.watch_input.clear()

    def watch_selected(self):
        rows = {index.row() for index in self.table.selectedIndexes()}
        ids = [self.table.item(row, self.HEADERS.index('ID')).text() for row in rows]
        if ids:
            self.set_watch(self.watch+ids)

    def remove_watch(self):
        chosen = {item.data(Qt.UserRole) for item in self.watch_list.selectedItems()}
        if chosen:
            self.set_watch([e for e in self.watch if e not in chosen])

    def is_watched(self, entry):
        return any(watchlist.watched(e, entry['entity_id'], entry.get('name')) for e in self.watch)

    def check_watch(self, state):
        """New detections of watched characters (or a stronger one, e.g. visible -> @hide)."""
        self.update_state(state)
        if not self.observe_enabled.isChecked():
            self.alerted.clear()
            self.watch_status.setText('Observacao desligada: lista preservada; sem pausas ou alertas desses jogadores.')
            return []
        if state.get("observation_suspended_for_route"):
            self.alerted.clear()
            self.watch_status.setText("Observacao suspensa no percurso entre mapas; volta na caca.")
            return []
        found = watchlist.detections(self.watch, state, self.players)
        now = {d['entity_id']: d['kind'] for d in found}
        fresh = [d for d in found
                 if watchlist.STATUS[d['kind']][0] > watchlist.STATUS.get(self.alerted.get(d['entity_id']), (0,))[0]]
        # Someone who is gone is alerted again the next time they are found.
        self.alerted = {identity: max(kind, self.alerted.get(identity, kind), key=lambda k: watchlist.STATUS[k][0])
                        for identity, kind in now.items()}
        self.watch_status.setText('Identificados agora: '+'; '.join(
            f"{d['name'] or d['entity_id']} — {d['text']}" for d in found) if found else 'Ninguém da lista identificado agora.')
        return fresh

    def job(self, entry):
        if entry.get('job') is None:
            return '—'
        names = self.names.get(entry['job'])
        return f"{names[0]} ({entry['job']})" if names else str(entry['job'])

    @staticmethod
    def when(stamp):
        try:
            return datetime.fromisoformat(stamp).strftime('%d/%m %H:%M')
        except (TypeError, ValueError):
            return '—'

    def fill(self):
        text = plain(self.search.text().strip())
        rows = []
        for entry in self.players.values():
            present = entry['entity_id'] in self.present
            if self.only_present.isChecked() and not present:
                continue
            notes = []
            if entry.get('hidden_seen'):
                notes.append('@hide visto' if entry['hidden_seen'] == 'gm' else 'hide visto')
            if entry.get('disguised'):
                notes.append(f"disfarce (sprite {entry['disguised']})")
            if entry.get('former_names'):
                notes.append('antes: '+', '.join(entry['former_names']))
            values = ['● sim' if present else '', '★' if self.is_watched(entry) else '',
                      entry.get('name') or '(nome não recebido)', str(entry['entity_id']),
                      str(entry['level']) if entry.get('level') else '—',
                      {'M': 'Masc.', 'F': 'Fem.'}.get(entry.get('sex'), '—'),
                      self.job(entry), entry.get('guild') or '—', entry.get('guild_title') or '—', entry.get('party') or '—',
                      entry.get('last_map') or '—',
                      str(entry.get('last_position') or '—'), f"{entry.get('sightings', 0)}x",
                      self.when(entry.get('first_seen')), self.when(entry.get('last_seen')), ', '.join(notes)]
            search = plain(' '.join(values+entry.get('maps', [])))
            if text and text not in search:
                continue
            look = entry.get('look') or {}
            visual = ('Visual: arma '+str(look.get('weapon'))+', escudo '+str(look.get('shield'))+', cabeca topo/meio/baixo '
                      +f"{look.get('head_top')}/{look.get('head_mid')}/{look.get('head_bottom')}"
                      +f", cabelo {look.get('hair')} cor {look.get('hair_color')}, roupa cor {look.get('clothes_color')}"
                      +(f", guilda ID {entry['guild_id']}" if entry.get('guild_id') else '')) if look else ''
            rows.append((not present, -(datetime.fromisoformat(entry['last_seen']).timestamp() if entry.get('last_seen') else 0), values, present, visual))
        rows.sort(key=lambda row: row[:2])
        looks = [row[4] for row in rows]
        rows = [row[:4] for row in rows]
        shown = [(values, present) for _, _, values, present in rows]
        if shown == self.shown_rows:
            return  # nothing visible changed
        self.shown_rows = shown
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(rows))
        highlight = QBrush(QColor(40, 110, 60, 120))
        for r, (_, _, values, present) in enumerate(rows):
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                if present:
                    item.setBackground(highlight)
                if c == 2 and looks[r]:
                    item.setToolTip(looks[r])
                self.table.setItem(r, c, item)
        if not self.sized and rows:
            self.table.resizeColumnsToContents()
            self.sized = True
        self.table.setUpdatesEnabled(True)
        self.summary.setText(f'{len(self.players)} jogadores registrados • {len(self.present)} na tela agora • '
                             f'{len(rows)} na lista')
