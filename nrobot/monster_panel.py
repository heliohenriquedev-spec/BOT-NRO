"""Aba Monstros (todos os monstros do jogo) e lista de alvos do mapa atual (REDE-79/81).

A tabela é um modelo: só as linhas visíveis são desenhadas e cada sprite é carregado quando
a linha aparece. A extração dos sprites roda em outro processo, para o painel não travar.
"""
from __future__ import annotations

import os
import sys
import unicodedata

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QProcess, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QTableView, QVBoxLayout, QWidget)

from . import monster_db

ICON = 40
_icons = {}


def plain(text):
    """Lowercase without accents, so 'magnolia' finds 'Magnólia'."""
    return ''.join(c for c in unicodedata.normalize('NFKD', str(text).lower()) if not unicodedata.combining(c))


def icon_for(species_id, path=None):
    path = path or monster_db.find_sprite(species_id)
    key = (species_id, str(path) if path else None)
    if key not in _icons:
        _icons[key] = (QIcon(QPixmap(str(path)).scaled(ICON, ICON, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                       if path else QIcon())
    return _icons[key]


def data_stamp():
    """Cheap change check: the monster files and sprite folders."""
    stamp = []
    for path in (monster_db.CAPTURED, monster_db.BASE_INFO, monster_db.SPRITES, monster_db.BASE_SPRITES, monster_db.ROOT/'Arquivos_grf'/'prioridade.tsv'):
        try:
            info = os.stat(path)
            stamp.append((info.st_mtime_ns, info.st_size))
        except OSError:
            stamp.append(None)
    return tuple(stamp)


class MonsterModel(QAbstractTableModel):
    HEADERS = ['Sprite', 'Nome', 'ID', 'Mapas', 'HP', 'Origem', 'Sprite de']

    def __init__(self):
        super().__init__()
        self.rows, self.visible, self.sprites = [], [], {}

    def set_rows(self, rows, sprites):
        self.beginResetModel()
        self.rows, self.sprites = rows, sprites
        for row in rows:
            maps = sorted(set(row['maps']) | set(row['seen_maps']))
            row['text'] = ('', row['name'], str(row['species_id']), ', '.join(maps) or '—',
                           str(row['max_hp']) if row.get('max_hp') else '—', row['origin'],
                           row['sprite_source'] if row['has_sprite'] else 'falta: passe o mouse sobre ele no jogo')
            row['search'] = plain(' '.join((row['name'], str(row['species_id']), *maps)))
        self.visible = list(range(len(rows)))
        self.endResetModel()

    def filter(self, text, only_missing):
        text = plain(text.strip())
        self.beginResetModel()
        self.visible = [i for i, row in enumerate(self.rows)
                        if (not text or text in row['search']) and (not only_missing or not row['has_sprite'])]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.visible)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[self.visible[index.row()]]
        if role == Qt.DisplayRole:
            return row['text'][index.column()]
        if role == Qt.DecorationRole and index.column() == 0:
            return icon_for(row['species_id'], self.sprites.get(row['species_id']))  # only for rows on screen
        return None


class MonsterPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Todos os monstros do jogo. Os monstros custom do servidor têm o sprite tirado dos dados '
                                'do jogo; os que faltarem são capturados quando você passa o mouse sobre eles no jogo.'))
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Buscar por nome, ID ou mapa')
        self.search.textChanged.connect(self.apply_filter)
        row.addWidget(self.search, 1)
        self.only_missing = QCheckBox('Só sem sprite')
        self.only_missing.toggled.connect(self.apply_filter)
        row.addWidget(self.only_missing)
        self.extract_button = QPushButton('Extrair sprites dos arquivos do jogo')
        self.extract_button.clicked.connect(self.extract)
        row.addWidget(self.extract_button)
        layout.addLayout(row)
        database = QPushButton('Database de itens e drops')
        database.clicked.connect(lambda: self.show_drops())
        layout.addWidget(database)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.model = MonsterModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.doubleClicked.connect(self.show_drops)
        self.table.setIconSize(QSize(ICON, ICON))
        self.table.verticalHeader().setDefaultSectionSize(ICON+6)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        for column, width in enumerate((60, 220, 70, 0, 80, 150, 0)):
            if width:
                self.table.setColumnWidth(column, width)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)
        self.stamp = None
        self.extracted = False
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(monster_db.ROOT))
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_progress)
        self.process.finished.connect(self.extraction_done)

    def show_drops(self, index=None):
        from .drop_panel import DropDatabaseDialog
        species = None
        if index is not None and index.isValid():
            species = self.model.rows[self.model.visible[index.row()]]['species_id']
        dialog = DropDatabaseDialog(self, species=species)
        dialog.exec()

    def showEvent(self, event):
        super().showEvent(event)
        self.reload()
        if not self.extracted:
            self.extract()

    def extract(self):
        if self.process.state() != QProcess.NotRunning:
            return
        self.extracted = True
        self.extract_button.setEnabled(False)
        self.summary.setText('Extraindo sprites dos arquivos do jogo em segundo plano...')
        self.process.start(sys.executable, ['-u', '-m', 'nrobot.monster_db'])

    def read_progress(self):
        for line in bytes(self.process.readAllStandardOutput()).decode('utf-8', 'replace').splitlines():
            if line.startswith('progresso'):
                self.summary.setText('Extraindo sprites dos arquivos do jogo: '+line.split()[1]+'...')
            elif line.startswith('ERRO'):
                self.summary.setText(line)

    def extraction_done(self, *args):
        self.extract_button.setEnabled(True)
        self.stamp = None
        self.reload()

    def reload(self):
        """Cheap when nothing changed on disk (the panel calls it every refresh)."""
        stamp = data_stamp()
        if stamp == self.stamp:
            return
        self.stamp = stamp
        rows = monster_db.all_monsters()
        self.model.set_rows(rows, monster_db.sprite_index())
        self.apply_filter()

    def apply_filter(self, *args):
        self.model.filter(self.search.text(), self.only_missing.isChecked())
        rows = self.model.rows
        if self.process.state() == QProcess.NotRunning:
            custom = sum(r['origin'] != 'jogo' for r in rows)
            without = sum(not r['has_sprite'] for r in rows)
            self.summary.setText(f'{len(rows)} monstros: {len(rows)-custom} do catálogo do jogo, {custom} custom do servidor • '
                                 f'{without} ainda sem sprite (passe o mouse sobre eles no jogo)')


class MapTargets(QWidget):
    """Monsters of the current map only, each one checked or not as a hunt target."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.selected = set()
        self.name_choices = {}
        self.automatic = False
        self.map_name = None
        self.shown = ()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel('Conecte e entre no mapa para ver os monstros dele.')
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.list = QListWidget()
        self.list.setIconSize(QSize(ICON, ICON))
        self.list.itemChanged.connect(self.item_changed)
        layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        for label, value in (('Marcar todos', True), ('Desmarcar todos', False)):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, v=value: self.set_all(v))
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def show_map(self, map_name, seen=None, force=False, variants=()):
        """seen: {species_id: {'name', 'present'}} confirmed on this map by the server."""
        seen = seen or {}
        variants = {(row['species_id'], row['name']): row.get('present', 0) for row in variants}
        key = (monster_db.map_key(map_name), data_stamp(), self.automatic,
               tuple(sorted((i, v.get('name'), v.get('present', 0)) for i, v in seen.items())),
               tuple(sorted(variants.items())))
        if key == self.shown and not force:
            return
        captured = monster_db.load_captured()
        ids = monster_db.monsters_of_map(map_name, captured=captured, seen=seen, include_catalog=False, catalog_fallback=True)
        self.shown, self.map_name = key, map_name
        self.list.blockSignals(True)
        self.list.clear()
        names = monster_db.names_for_map(map_name, captured)
        for identity, name in variants:
            names.setdefault(identity, set()).add(name)
        for identity in sorted(set(ids) | names.keys()):
            named = names.get(identity)
            labels = sorted(named, key=str.casefold) if named else [
                seen.get(identity, {}).get('name') or monster_db.name_of(identity, captured)]
            for name in labels:
                from .monster_origin import excluded_spawn
                if excluded_spawn(identity, map_name, name):
                    continue
                choice = monster_db.monster_choice_key(map_name, identity, name) if named else None
                present = variants.get((identity, name)) if named else seen.get(identity, {}).get('present')
                item = QListWidgetItem(icon_for(identity), f'{name}  (ID {identity})'+(f' • {present} por perto' if present else ''))
                item.setData(Qt.UserRole, identity)
                item.setData(Qt.UserRole+1, choice)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                if self.automatic and choice is None:
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                checked = self.automatic or identity in self.selected
                if choice is not None:
                    checked = self.name_choices.get(choice, checked)
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
                self.list.addItem(item)
        self.list.blockSignals(False)
        key_name = monster_db.map_key(map_name)
        self.title.setText(f'Monstros registrados em {key_name}: marque os que deseja caçar.' if ids else
                           (f'Nenhum monstro conhecido em {key_name} ainda; eles aparecem aqui assim que forem vistos.'
                            if key_name else 'Conecte e entre no mapa para ver os monstros dele.'))

    def item_changed(self, item):
        identity = item.data(Qt.UserRole)
        choice = item.data(Qt.UserRole+1)
        if choice is not None:
            self.name_choices[choice] = item.checkState() == Qt.Checked
        elif item.checkState() == Qt.Checked:
            self.selected.add(identity)
        else:
            self.selected.discard(identity)
        self.changed.emit()

    def set_all(self, value):
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.flags() & Qt.ItemIsEnabled:
                item.setCheckState(Qt.Checked if value else Qt.Unchecked)

    def set_automatic(self, enabled):
        self.automatic = enabled
        self.shown = ()
