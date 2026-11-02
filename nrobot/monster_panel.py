"""Aba Monstros (todos os monstros do jogo) e lista de alvos do mapa atual (REDE-79)."""
from __future__ import annotations

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import monster_db

ICON = 40


def plain(text):
    """Lowercase without accents, so 'magnolia' finds 'Magnólia'."""
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFKD', str(text).lower()) if not unicodedata.combining(c))


def icon_for(species_id, cache={}):
    path = monster_db.sprite_path(species_id)
    stamp = path.stat().st_mtime_ns if path.is_file() else None
    cached = cache.get(species_id)
    if cached and cached[0] == stamp:
        return cached[1]
    icon = QIcon(QPixmap(str(path)).scaled(ICON, ICON, Qt.KeepAspectRatio, Qt.SmoothTransformation)) if stamp else QIcon()
    cache[species_id] = (stamp, icon)
    return icon


class SpriteExtractor(QObject):
    """Writes the sprites the client files have, once, outside the interface thread."""
    progress = Signal(int, int)
    finished = Signal(int, int)

    def run(self):
        from .game_folder import find
        from .grf import GrfError, GrfSet
        folder = find()
        written = missing = 0
        try:
            grfs = GrfSet(str(folder)) if folder else None
        except (GrfError, OSError):
            grfs = None
        ids = sorted(monster_db.catalog())
        for index, identity in enumerate(ids, 1):
            state = monster_db.ensure_sprite(grfs, identity)
            written += state == 'grf'
            missing += state is None
            if index % 40 == 0:
                self.progress.emit(index, len(ids))
        self.finished.emit(written, missing)


class MonsterPanel(QWidget):
    COLUMNS = ['Sprite', 'Nome', 'ID', 'Mapas', 'HP', 'Origem', 'Sprite']

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Todos os monstros do jogo. Os que não têm sprite nos arquivos do cliente são '
                                'capturados do próprio jogo quando você passa o mouse sobre eles.'))
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Buscar por nome, ID ou mapa')
        self.search.textChanged.connect(self.fill)
        row.addWidget(self.search, 1)
        self.only_missing = QCheckBox('Só sem sprite')
        self.only_missing.toggled.connect(self.fill)
        row.addWidget(self.only_missing)
        self.extract_button = QPushButton('Extrair sprites dos arquivos do jogo')
        self.extract_button.clicked.connect(self.extract)
        row.addWidget(self.extract_button)
        layout.addLayout(row)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setIconSize(QSize(ICON, ICON))
        self.table.verticalHeader().setDefaultSectionSize(ICON+6)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)
        self.rows = []
        self.signature = None
        self.thread = None
        self.extracted = False

    def showEvent(self, event):
        super().showEvent(event)
        self.reload()
        if not self.extracted:
            self.extract()

    def extract(self):
        if self.thread is not None:
            return
        self.extracted = True
        self.extract_button.setEnabled(False)
        self.thread = QThread(self)
        self.worker = SpriteExtractor()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(lambda done, total: self.summary.setText(f'Extraindo sprites: {done}/{total}...'))
        self.worker.finished.connect(self.extraction_done)
        self.thread.start()

    def extraction_done(self, written, missing):
        self.thread.quit()
        self.thread.wait()
        self.thread = None
        self.extract_button.setEnabled(True)
        self.signature = None
        self.reload()

    def reload(self):
        """Re-read the monsters (cheap); rebuild the table only when something changed."""
        rows = monster_db.all_monsters()
        signature = tuple((r['species_id'], r['name'], r['has_sprite'], r.get('max_hp'), tuple(r['seen_maps'])) for r in rows)
        if signature == self.signature:
            return
        self.signature, self.rows = signature, rows
        self.fill()

    def fill(self):
        text = plain(self.search.text().strip())
        rows = [r for r in self.rows
                if (not text or text in plain(r['name']) or text == str(r['species_id'])
                    or any(text in m for m in r['maps']+r['seen_maps']))
                and (not self.only_missing.isChecked() or not r['has_sprite'])]
        game = sum(r['origin'] == 'jogo' for r in self.rows)
        captured = sum(r['origin'] != 'jogo' for r in self.rows)
        without = sum(not r['has_sprite'] for r in self.rows)
        if self.thread is None:
            self.summary.setText(f'{len(self.rows)} monstros: {game} dos arquivos do jogo, {captured} descobertos jogando • '
                                 f'{without} ainda sem sprite (passe o mouse sobre eles no jogo)')
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            maps = sorted(set(row['maps']) | set(row['seen_maps']))
            sprite = ('capturado do jogo' if row.get('captured_sprite') else 'arquivos do jogo') if row['has_sprite'] \
                else 'falta: passe o mouse sobre ele no jogo'
            values = ['', row['name'], str(row['species_id']), ', '.join(maps) or '—',
                      str(row['max_hp']) if row.get('max_hp') else '—', row['origin'], sprite]
            for column, value in enumerate(values):
                item = self.table.item(index, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(index, column, item)
                item.setText(value)
            self.table.item(index, 0).setIcon(icon_for(row['species_id']))
        self.table.setUpdatesEnabled(True)


class MapTargets(QWidget):
    """Monsters of the current map only, each one checked or not as a hunt target."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.selected = set()
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

    def show_map(self, map_name, seen=None, force=False):
        """seen: {species_id: {'name', 'present'}} confirmed on this map by the server."""
        seen = seen or {}
        ids = monster_db.monsters_of_map(map_name, seen=seen)
        key = (monster_db.map_key(map_name), tuple(ids), tuple(sorted((i, v.get('present', 0)) for i, v in seen.items())))
        if key == self.shown and not force:
            return
        self.shown, self.map_name = key, map_name
        captured = monster_db.load_captured()
        self.list.blockSignals(True)
        self.list.clear()
        for identity in ids:
            name = seen.get(identity, {}).get('name') or monster_db.name_of(identity, captured)
            present = seen.get(identity, {}).get('present')
            item = QListWidgetItem(icon_for(identity), f'{name}  (ID {identity})'+(f' • {present} por perto' if present else ''))
            item.setData(Qt.UserRole, identity)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if identity in self.selected else Qt.Unchecked)
            self.list.addItem(item)
        self.list.blockSignals(False)
        key_name = monster_db.map_key(map_name)
        self.title.setText(f'Monstros do mapa {key_name}: marque os que deseja caçar.' if ids else
                           (f'Nenhum monstro conhecido em {key_name} ainda; eles aparecem aqui assim que forem vistos.'
                            if key_name else 'Conecte e entre no mapa para ver os monstros dele.'))

    def item_changed(self, item):
        identity = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            self.selected.add(identity)
        else:
            self.selected.discard(identity)
        self.changed.emit()

    def set_all(self, value):
        for index in range(self.list.count()):
            self.list.item(index).setCheckState(Qt.Checked if value else Qt.Unchecked)

    def setEnabled(self, enabled):
        self.list.setEnabled(enabled)
