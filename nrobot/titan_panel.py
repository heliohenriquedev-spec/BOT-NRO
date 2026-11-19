"""Aba Titan: tamanho e cor locais, com ou sem tecla, e atalhos de esconder.

1. Escolha alguém (na tela, entre os jogadores já vistos ou entre os monstros conhecidos).
2. Ajuste tamanho, cor e, se quiser, uma tecla que liga/desliga a mudança.
3. "Esconder com tecla": cada atalho tem a sua tecla e esconde um grupo, menos os jogadores
   marcados como "continuam visíveis".
O painel grava data/rede/titan.json (o relay aplica cor e esconder) e ajusta o zoom de cada
unidade no próprio jogo (titan_zoom). O servidor não recebe nada.
Nomes: jogadores pelo registro da aba Jogadores, monstros pelo banco de monstros.
"""
import copy
import json
import sys
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QSlider, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from . import titan_settings as ts
from .npc_labels import plain
from .titan_zoom import ZoomWriter, desired_scales

KINDS = {'self': 'Você', 'player': 'Jogador', 'monster': 'Monstro', 'summon': 'Invocação', 'npc': 'NPC'}
SOURCES = (('screen', 'Na tela agora'), ('players', 'Todos os jogadores já vistos'), ('monsters', 'Todos os monstros'))
KIND_FILTER = (('', 'Todos os tipos'), ('player', 'Jogadores'), ('monster', 'Monstros'), ('summon', 'Invocações'),
               ('npc', 'NPCs'))
MUTED = 'color: #8fa3bf;'
SEGMENT = ('QPushButton { padding: 6px 14px; } '
           'QPushButton:checked { background: #2f9e7a; color: #ffffff; border: 1px solid #4fd1a5; }')
ACTIVE = 'font-weight: 700; color: #ff8a65;'
LIST_LIMIT = 400


def make_table(headers, stretch=0, min_height=160):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setSelectionBehavior(QAbstractItemView.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SingleSelection)
    widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
    widget.verticalHeader().setVisible(False)
    widget.verticalHeader().setDefaultSectionSize(32)
    widget.setMinimumHeight(min_height)
    widget.setAlternatingRowColors(True)
    header = widget.horizontalHeader()
    for column in range(len(headers)):
        header.setSectionResizeMode(column, QHeaderView.Stretch if column == stretch else QHeaderView.ResizeToContents)
    return widget


def item(text, muted=False):
    cell = QTableWidgetItem(str(text))
    if muted:
        cell.setForeground(QColor('#7a8699'))
    return cell


def percent(scale):
    return f'{round(scale*100)}%'


def rule_matches(rule, row):
    if rule['kind'] == 'entity':
        return row.get('id') is not None and rule['value'] == str(row['id'])
    if rule['kind'] == 'name':
        return bool(row.get('name')) and plain(rule['value']) == plain(row['name'])
    return row.get('species') is not None and rule['value'] == str(row['species'])


def effective_rule(rules, row):
    """The rule the game uses for this unit (ID > nome > espécie)."""
    for kind in ('entity', 'name', 'species'):
        for rule in rules:
            if rule['enabled'] and rule['kind'] == kind and rule_matches(rule, row):
                return rule
    return None


def known_players():
    """{id: name} of every character the bot has ever seen (aba Jogadores)."""
    from . import player_registry
    result = {}
    for key, entry in player_registry.load().items():
        if str(key).isdigit() and entry.get('name'):
            result[int(key)] = entry['name']
    return result


def known_monsters():
    from .monster_db import all_monsters
    try:
        return [dict(id=None, species=row['species_id'], name=row['name'], kind='monster', where='banco de monstros')
                for row in all_monsters()]
    except (OSError, ValueError):
        return []


def species_name(species):
    from .monster_db import name_of
    try:
        return name_of(species)
    except (OSError, ValueError):
        return ''


class TitanPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.config = ts.load()
        self.loading = False
        self.screen_rows = []
        self.shown = []
        self.own_id = None
        self.target = None  # (kind, value, name) the editor changes
        self.target_row = None
        self.monster_scope = 'name'
        self.keys_down = {}
        self.players_cache = (0, {})
        self.monsters_cache = None
        self.zoom = ZoomWriter()
        self.save()  # the relay reads Titan as on only from this file

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setSpacing(12)

        header = QHBoxLayout()
        self.enabled = QCheckBox('Ativar Titan')
        self.enabled.setChecked(self.config['enabled'])
        self.enabled.toggled.connect(self.changed)
        header.addWidget(self.enabled)
        self.status = QLabel()
        self.status.setStyleSheet(MUTED)
        header.addWidget(self.status, 1)
        self.overlay_box = QCheckBox('Mostrar atalhos ao lado (overlay)')
        self.overlay_box.setToolTip('Janela pequena, sempre por cima, com cada atalho e se está ligado. Arraste para '
                                    'deixar fora do jogo.')
        self.overlay_box.setChecked(self.config['overlay']['visible'])
        self.overlay_box.toggled.connect(self.set_overlay)
        header.addWidget(self.overlay_box)
        layout.addLayout(header)
        intro = QLabel('Muda só o que o seu jogo mostra: tamanho, cor e quem aparece. O servidor e os outros '
                       'jogadores não veem nada.')
        intro.setWordWrap(True)
        intro.setStyleSheet(MUTED)
        layout.addWidget(intro)

        # ---- 1. escolher ----
        pick_box = QGroupBox('1. Escolha quem mudar')
        pick_layout = QVBoxLayout(pick_box)
        source_row = QHBoxLayout()
        source_row.setSpacing(4)
        self.source = QButtonGroup(self)
        for index, (key, label) in enumerate(SOURCES):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setStyleSheet(SEGMENT)
            button.setProperty('source', key)
            self.source.addButton(button, index)
            source_row.addWidget(button)
        self.source.button(0).setChecked(True)
        self.source.idToggled.connect(lambda _i, on: on and self.fill_pick())
        source_row.addStretch(1)
        pick_layout.addLayout(source_row)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Procurar por nome ou ID')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.fill_pick)
        self.kind_filter = QComboBox()
        for key, label in KIND_FILTER:
            self.kind_filter.addItem(label, key)
        self.kind_filter.setFixedWidth(160)
        self.kind_filter.currentIndexChanged.connect(self.fill_pick)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.kind_filter)
        pick_layout.addLayout(filters)
        self.pick = make_table(['Nome', 'Tipo', 'ID', 'Espécie', 'Tamanho', 'Cor', 'Situação'], min_height=260)
        self.pick.itemSelectionChanged.connect(self.pick_selected)
        pick_layout.addWidget(self.pick)
        self.pick_note = QLabel()
        self.pick_note.setStyleSheet(MUTED)
        self.pick_note.setWordWrap(True)
        pick_layout.addWidget(self.pick_note)
        layout.addWidget(pick_box)

        # ---- 2. tamanho e cor ----
        edit_box = QGroupBox('2. Tamanho e cor')
        edit_outer = QHBoxLayout(edit_box)
        edit_inner = QWidget()
        edit_inner.setMaximumWidth(980)
        edit_outer.addWidget(edit_inner, 1)
        edit_outer.addStretch(0)
        grid = QGridLayout(edit_inner)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        self.target_label = QLabel('Escolha alguém na lista acima.')
        self.target_label.setStyleSheet('font-weight: 700;')
        grid.addWidget(QLabel('Alvo'), 0, 0)
        grid.addWidget(self.target_label, 0, 1)
        scope_row = QHBoxLayout()
        scope_row.setSpacing(4)
        self.scope = QButtonGroup(self)
        for index, (key, label) in enumerate(ts.RULE_KINDS.items()):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setStyleSheet(SEGMENT)
            button.setProperty('scope', key)
            self.scope.addButton(button, index)
            scope_row.addWidget(button)
        scope_row.addStretch(1)
        self.scope.button(0).setChecked(True)
        self.scope.idToggled.connect(self.scope_changed)
        grid.addWidget(QLabel('Aplicar a'), 1, 0)
        grid.addLayout(scope_row, 1, 1)
        size_row = QHBoxLayout()
        self.size = QSlider(Qt.Horizontal)
        self.size.setRange(round(ts.SCALE_MIN*100), round(ts.SCALE_MAX*100))
        self.size.setSingleStep(5)
        self.size.setPageStep(25)
        self.size.setValue(100)
        self.size_label = QLabel('100%')
        self.size_label.setFixedWidth(50)
        self.size_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        normal = QPushButton('Normal')
        normal.setFixedWidth(80)
        normal.clicked.connect(lambda: self.size.setValue(100))
        size_row.addWidget(self.size, 1)
        size_row.addWidget(self.size_label)
        size_row.addWidget(normal)
        grid.addWidget(QLabel('Tamanho'), 2, 0)
        grid.addLayout(size_row, 2, 1)
        self.color = QComboBox()
        for key, spec in ts.COLORS.items():
            self.color.addItem(spec['label'], key)
        self.color.setFixedWidth(220)
        grid.addWidget(QLabel('Cor'), 3, 0)
        grid.addWidget(self.color, 3, 1, Qt.AlignLeft)
        key_row = QHBoxLayout()
        self.key = QComboBox()
        self.key.addItem('Nenhuma (sempre ligado)', ts.NO_KEY)
        for key in ts.KEYS:
            self.key.addItem(key, key)
        self.key.setFixedWidth(220)
        key_note = QLabel('Com tecla, ela liga/desliga esta mudança no jogo.')
        key_note.setStyleSheet(MUTED)
        key_note.setWordWrap(True)
        key_row.addWidget(self.key)
        key_row.addWidget(key_note, 1)
        grid.addWidget(QLabel('Tecla'), 4, 0)
        grid.addLayout(key_row, 4, 1)
        reset_row = QHBoxLayout()
        reset = QPushButton('Voltar ao normal')
        reset.clicked.connect(self.reset_target)
        reset_row.addWidget(reset)
        reset_row.addStretch(1)
        grid.addLayout(reset_row, 5, 1)
        self.size.valueChanged.connect(self.controls_changed)
        self.color.currentIndexChanged.connect(self.controls_changed)
        self.key.currentIndexChanged.connect(self.controls_changed)
        self.set_editor_enabled(False)
        layout.addWidget(edit_box)

        # ---- 3. mudanças salvas ----
        saved_box = QGroupBox('3. Mudanças salvas')
        saved_layout = QVBoxLayout(saved_box)
        self.saved = make_table(['Alvo', 'Aplica a', 'Tamanho', 'Cor', 'Tecla', 'Estado'], min_height=150)
        self.saved.itemSelectionChanged.connect(self.saved_selected)
        saved_layout.addWidget(self.saved)
        saved_buttons = QHBoxLayout()
        for text, handler in (('Ligar / desligar', self.toggle_saved), ('Remover', self.remove_saved),
                              ('Remover todas', self.clear_saved)):
            button = QPushButton(text)
            button.clicked.connect(handler)
            saved_buttons.addWidget(button)
        saved_buttons.addStretch(1)
        saved_layout.addLayout(saved_buttons)
        layout.addWidget(saved_box)

        # ---- 4. esconder ----
        hide_box = QGroupBox('4. Esconder com tecla')
        hide_layout = QVBoxLayout(hide_box)
        hide_note = QLabel('Cada atalho tem a sua tecla: apertando no jogo, some na hora; apertando de novo, volta. '
                           'Marque na lista por ID (só aquele) ou por nome (todos com o nome) e escolha o modo: '
                           '"Todos menos os marcados" (ex.: só o seu amigo fica) ou "Só os marcados" (ex.: só um '
                           'Bikouchuu some).')
        hide_note.setWordWrap(True)
        hide_note.setStyleSheet(MUTED)
        hide_layout.addWidget(hide_note)
        self.hides = make_table(['Esconder', 'Tecla', 'Marcados', 'Estado'], stretch=2, min_height=140)
        self.hides.itemSelectionChanged.connect(self.hide_selected)
        hide_layout.addWidget(self.hides)
        hide_buttons = QHBoxLayout()
        for text, handler in (('Novo atalho', self.add_hide), ('Remover atalho', self.remove_hide),
                              ('Ligar / desligar agora', self.toggle_selected_hide)):
            button = QPushButton(text)
            button.clicked.connect(handler)
            hide_buttons.addWidget(button)
        hide_buttons.addStretch(1)
        hide_layout.addLayout(hide_buttons)

        self.hide_editor = QWidget()
        editor = QGridLayout(self.hide_editor)
        editor.setContentsMargins(0, 6, 0, 0)
        editor.setHorizontalSpacing(14)
        editor.setColumnStretch(1, 1)
        self.hide_what = QComboBox()
        for key, (label, _flags) in ts.HIDE_WHAT.items():
            self.hide_what.addItem(label, key)
        self.hide_what.setFixedWidth(220)
        self.hide_key = QComboBox()
        self.hide_key.addItems([ts.NO_KEY, *ts.KEYS])
        self.hide_key.setFixedWidth(220)
        self.hide_what.currentIndexChanged.connect(self.hide_edited)
        self.hide_key.currentIndexChanged.connect(self.hide_edited)
        editor.addWidget(QLabel('Esconder'), 0, 0)
        editor.addWidget(self.hide_what, 0, 1, Qt.AlignLeft)
        editor.addWidget(QLabel('Tecla'), 1, 0)
        editor.addWidget(self.hide_key, 1, 1, Qt.AlignLeft)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        self.hide_mode = QButtonGroup(self)
        for index, (key, label) in enumerate((('except', 'Todos menos os marcados'), ('only', 'Só os marcados'))):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setStyleSheet(SEGMENT)
            button.setProperty('mode', key)
            self.hide_mode.addButton(button, index)
            mode_row.addWidget(button)
        mode_row.addStretch(1)
        self.hide_mode.button(0).setChecked(True)
        self.hide_mode.idToggled.connect(lambda _i, on: on and self.hide_edited())
        editor.addWidget(QLabel('Modo'), 2, 0)
        editor.addLayout(mode_row, 2, 1)
        self.keep_title = QLabel('Marcados')
        editor.addWidget(self.keep_title, 3, 0, Qt.AlignTop)
        keep = QVBoxLayout()
        self.keep_search = QLineEdit()
        self.keep_search.setPlaceholderText('Procurar por nome ou ID (quem está na tela vem primeiro)')
        self.keep_search.setClearButtonEnabled(True)
        self.keep_search.textChanged.connect(self.fill_keep)
        self.keep_list = QListWidget()
        self.keep_list.setMinimumHeight(200)
        self.keep_list.setStyleSheet(
            'QListWidget::item { padding: 3px 4px; } '
            'QListWidget::indicator { width: 15px; height: 15px; border: 1px solid #6b7d96; border-radius: 3px; '
            'background: #0f1a2b; } '
            'QListWidget::indicator:checked { background: #2f9e7a; border-color: #4fd1a5; }')
        self.keep_list.itemChanged.connect(self.keep_toggled)
        self.keep_count = QLabel()
        self.keep_count.setStyleSheet(MUTED)
        keep.addWidget(self.keep_search)
        keep.addWidget(self.keep_list)
        keep.addWidget(self.keep_count)
        editor.addLayout(keep, 3, 1)
        hide_layout.addWidget(self.hide_editor)
        self.hide_editor.setEnabled(False)
        summon_row = QHBoxLayout()
        summon = QPushButton('Contar espécie como invocação')
        summon.setToolTip('Escolha a criatura na lista do bloco 1 e clique.')
        summon.clicked.connect(self.mark_summon)
        summon_note = QLabel('Invocações são reconhecidas pelo bot (as suas, pets, homúnculos e as criadas por '
                             'outros jogadores com Kuchiyose). Se alguma escapar, escolha a espécie e clique aqui.')
        summon_note.setWordWrap(True)
        summon_note.setStyleSheet(MUTED)
        summon_row.addWidget(summon, 0, Qt.AlignTop)
        summon_row.addWidget(summon_note, 1)
        hide_layout.addLayout(summon_row)
        marked_row = QHBoxLayout()
        self.summon_marked = QLabel()
        self.summon_marked.setWordWrap(True)
        unmark = QPushButton('Desmarcar todas')
        unmark.setToolTip('Essas espécies voltam a contar como monstro (atalhos de Monstros passam a valer para elas).')
        unmark.clicked.connect(self.clear_summon_species)
        marked_row.addWidget(self.summon_marked, 1)
        marked_row.addWidget(unmark, 0, Qt.AlignTop)
        self.summon_marked_row = QWidget()
        self.summon_marked_row.setLayout(marked_row)
        hide_layout.addWidget(self.summon_marked_row)
        layout.addWidget(hide_box)
        layout.addStretch(1)

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(150)
        self.save_timer.timeout.connect(self.save)
        self.screen_timer = QTimer(self)
        self.screen_timer.timeout.connect(self.read_screen)
        self.screen_timer.start(500)
        self.key_timer = QTimer(self)
        self.key_timer.timeout.connect(self.check_keys)
        self.key_timer.start(15)
        self.game_window = (0, None)
        from .titan_overlay import TitanOverlay
        self.overlay = TitanOverlay(on_moved=self.overlay_moved)
        self.overlay_timer = QTimer(self)
        self.overlay_timer.timeout.connect(lambda: self.overlay.show_config(self.config))
        self.overlay_timer.start(200)
        if self.config['overlay']['visible']:
            self.show_overlay()
        self.zoom_timer = QTimer(self)
        self.zoom_timer.timeout.connect(self.apply_zoom)
        self.zoom_timer.start(150)
        self.fill_saved()
        self.fill_hides()
        self.show_summon_species()
        self.read_screen()

    # ---- persistência ----
    def changed(self, *args):
        if self.loading:
            return
        self.config['enabled'] = self.enabled.isChecked()
        self.save_timer.start()

    def save(self):
        """Writes a validated copy; self.config stays the object every widget edits."""
        try:
            ts.save(copy.deepcopy(self.config))
        except (OSError, ValueError) as exc:
            self.status.setText(f'Titan não salvo: {exc}')

    def save_now(self):
        self.save_timer.stop()
        self.save()

    def apply_zoom(self):
        if sys.platform != 'win32':
            return
        self.zoom.step(desired_scales(self.config, self.screen_rows, self.own_id))

    # ---- fontes de nomes ----
    def players(self):
        """Registro da aba Jogadores, relido a cada 30 s."""
        stamp, names = self.players_cache
        if time.monotonic()-stamp > 30:
            try:
                names = known_players()
            except (OSError, ValueError):
                names = {}
            self.players_cache = (time.monotonic(), names)
        return names

    def monsters(self):
        if self.monsters_cache is None:
            self.monsters_cache = known_monsters()
        return self.monsters_cache

    # ---- 1. lista ----
    def read_screen(self):
        try:
            data = json.loads(ts.SCREEN_FILE.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        fresh = time.time()-data.get('updated', 0) < 30
        rows = [dict(r) for r in data.get('entities', [])] if fresh else []
        self.own_id = data.get('own_id') if fresh else None
        players = self.players()
        for row in rows:
            if not row.get('name'):
                if row['kind'] == 'player':
                    row['name'] = players.get(row['id'], '')
                elif row['kind'] in ('monster', 'summon'):
                    row['name'] = species_name(row['species'])
            row['where'] = 'escondido' if row.get('hidden') else 'na tela'
        if self.own_id and not any(r['id'] == self.own_id for r in rows):
            rows.insert(0, dict(id=self.own_id, species=None, name='Você', kind='self', where='na tela'))
        order = {'self': 0, 'player': 1, 'monster': 2, 'summon': 3, 'npc': 4}
        rows.sort(key=lambda r: (order.get(r['kind'], 5), plain(r.get('name') or '~'), r['id']))
        hidden = sum(1 for r in rows if r.get('hidden'))
        active = [ts.HIDE_WHAT[g['what']][0] for g in self.config['hide_groups'] if g['active']]
        text = (f'{len(rows)} na tela · {hidden} escondidos' if fresh else 'Jogo não conectado pelo bot.')
        text += (' · Escondendo: '+', '.join(active)) if active else ''
        if self.zoom.error and any(r['scale'] != 1.0 for r in self.config['rules']):
            text += f' · Tamanho: {self.zoom.error}'
        self.status.setText(text)
        if rows != self.screen_rows:
            self.screen_rows = rows
            if self.source_key() == 'screen':
                self.fill_pick()
            self.fill_hides()

    def source_key(self):
        return self.source.checkedButton().property('source')

    def rows_for_source(self):
        source = self.source_key()
        if source == 'screen':
            return self.screen_rows
        if source == 'players':
            on_screen = {r['id']: r for r in self.screen_rows if r['kind'] == 'player'}
            rows = [on_screen.get(identity) or dict(id=identity, species=None, name=name, kind='player', where='fora da tela')
                    for identity, name in self.players().items()]
            rows.sort(key=lambda r: (r['where'] == 'fora da tela', plain(r['name'])))
            return rows
        return self.monsters()

    def fill_pick(self, *args):
        needle, kind = plain(self.search.text().strip()), self.kind_filter.currentData()
        rows = [r for r in self.rows_for_source()
                if (not kind or r['kind'] == kind or (kind == 'player' and r['kind'] == 'self'))
                and (not needle or needle in plain(r.get('name') or '') or needle in str(r.get('id') or '')
                     or needle in str(r.get('species') or ''))]
        total = len(rows)
        self.shown = rows[:LIST_LIMIT]
        selected = self.target_row
        self.loading = True
        self.pick.setRowCount(len(self.shown))
        for index, row in enumerate(self.shown):
            rule = effective_rule(self.config['rules'], row)
            muted = row.get('where') != 'na tela'
            values = (row.get('name') or '(sem nome)', KINDS.get(row['kind'], row['kind']),
                      row['id'] if row.get('id') is not None else '—',
                      row['species'] if row.get('species') not in (None, 0) else '—',
                      percent(rule['scale']) if rule else '100%',
                      ts.COLORS[rule['color']]['label'] if rule else 'Original', row.get('where', ''))
            for column, value in enumerate(values):
                self.pick.setItem(index, column, item(value, muted))
            if selected is not None and row.get('id') == selected.get('id') and row.get('species') == selected.get('species') \
                    and row.get('name') == selected.get('name'):
                self.pick.selectRow(index)
        self.loading = False
        source = self.source_key()
        note = {'screen': 'Nomes de jogadores vêm do registro da aba Jogadores; de monstros, do banco de monstros.',
                'players': 'Todos os jogadores que o bot já viu. A mudança vale quando ele aparecer na tela.',
                'monsters': 'Todos os monstros conhecidos. Escolha "Todos com este nome" ou "Toda a espécie".'}[source]
        if total > LIST_LIMIT:
            note += f' Mostrando {LIST_LIMIT} de {total}: use a busca.'
        self.pick_note.setText(note)

    def pick_selected(self):
        if self.loading:
            return
        index = self.pick.currentRow()
        if not 0 <= index < len(self.shown):
            return
        row = self.target_row = self.shown[index]
        if row.get('id') is None:
            scope = self.monster_scope if self.monster_scope != 'entity' else 'name'
        elif row['kind'] in ('player', 'self'):
            scope = 'entity'
        else:
            scope = self.monster_scope
        self.loading = True
        self.scope.button(list(ts.RULE_KINDS).index(scope)).setChecked(True)
        self.scope.button(0).setEnabled(row.get('id') is not None)
        self.scope.button(2).setEnabled(row.get('species') not in (None, 0))
        self.loading = False
        self.saved.clearSelection()
        self.target_from_row()

    def scope_changed(self, _id, checked):
        if checked and not self.loading and self.target_row is not None:
            if self.target_row['kind'] not in ('player', 'self'):
                self.monster_scope = self.scope.checkedButton().property('scope')
            self.target_from_row()

    def target_from_row(self):
        row = self.target_row
        scope = self.scope.checkedButton().property('scope')
        value = {'entity': str(row.get('id') or ''), 'name': row.get('name') or '',
                 'species': str(row.get('species') or '')}[scope]
        name = row.get('name') or f'ID {row.get("id")}'
        if not value:
            self.target = None
            self.target_label.setText(f'{name}: escolha outro "Aplicar a"')
            self.set_editor_enabled(False)
            return
        label = {'entity': f'{name} (ID {value})', 'name': f'todos chamados "{value}"',
                 'species': f'toda a espécie {value} ({name})'}[scope]
        self.set_target(scope, value, label, row.get('name') or '')

    # ---- 2. editor ----
    def set_editor_enabled(self, enabled):
        for widget in (self.size, self.color, self.key):
            widget.setEnabled(enabled)

    def find_rule(self, kind, value):
        return next((r for r in self.config['rules'] if r['kind'] == kind and r['value'].casefold() == value.casefold()), None)

    def set_target(self, kind, value, label, name):
        self.target = (kind, value, name)
        self.target_label.setText(label)
        rule = self.find_rule(kind, value)
        self.loading = True
        self.size.setValue(round((rule['scale'] if rule else 1.0)*100))
        self.size_label.setText(percent(self.size.value()/100))
        self.color.setCurrentIndex(max(0, self.color.findData(rule['color'] if rule else 'none')))
        self.key.setCurrentIndex(max(0, self.key.findData(rule['key'] if rule else ts.NO_KEY)))
        self.loading = False
        self.set_editor_enabled(True)

    def controls_changed(self, *args):
        self.size_label.setText(percent(self.size.value()/100))
        if self.loading or self.target is None:
            return
        kind, value, name = self.target
        scale, color, key = self.size.value()/100, self.color.currentData(), self.key.currentData()
        old = self.find_rule(kind, value)
        rules = [r for r in self.config['rules'] if r is not old]
        if scale != 1.0 or color != 'none':
            rules.append(dict(kind=kind, value=value, scale=scale, color=color, key=key,
                              enabled=old['enabled'] if old else True, label=name))
        self.config['rules'] = rules
        self.refresh_lists()
        self.changed()

    def reset_target(self):
        if self.target is None:
            return
        old = self.find_rule(*self.target[:2])
        if old is not None:
            self.config['rules'].remove(old)
        self.set_target(self.target[0], self.target[1], self.target_label.text(), self.target[2])
        self.refresh_lists()
        self.changed()

    def refresh_lists(self):
        self.fill_pick()
        self.fill_saved()

    # ---- 3. salvas ----
    def fill_saved(self):
        self.loading = True
        selected = self.saved.currentRow()
        self.saved.setRowCount(len(self.config['rules']))
        for index, rule in enumerate(self.config['rules']):
            target = rule['label'] or rule['value']
            if rule['kind'] == 'entity':
                target = f'{target} (ID {rule["value"]})' if rule['label'] else f'ID {rule["value"]}'
            values = (target, ts.RULE_KINDS[rule['kind']], percent(rule['scale']), ts.COLORS[rule['color']]['label'],
                      rule['key'] if rule['key'] != ts.NO_KEY else '—', 'Ligada' if rule['enabled'] else 'Desligada')
            for column, value in enumerate(values):
                self.saved.setItem(index, column, item(value, not rule['enabled']))
        if 0 <= selected < len(self.config['rules']):
            self.saved.selectRow(selected)
        self.loading = False

    def saved_selected(self):
        if self.loading:
            return
        index = self.saved.currentRow()
        if not 0 <= index < len(self.config['rules']):
            return
        rule = self.config['rules'][index]
        self.target_row = None
        self.loading = True
        self.pick.clearSelection()
        for button in self.scope.buttons():
            button.setEnabled(True)
        self.scope.button(list(ts.RULE_KINDS).index(rule['kind'])).setChecked(True)
        self.loading = False
        label = {'entity': f'{rule["label"] or "ID"} (ID {rule["value"]})', 'name': f'todos chamados "{rule["value"]}"',
                 'species': f'toda a espécie {rule["value"]}'}[rule['kind']]
        self.set_target(rule['kind'], rule['value'], label, rule['label'])

    def clear_target(self):
        self.target = None
        self.target_label.setText('Escolha alguém na lista acima.')
        self.set_editor_enabled(False)

    def toggle_saved(self):
        index = self.saved.currentRow()
        if 0 <= index < len(self.config['rules']):
            self.config['rules'][index]['enabled'] = not self.config['rules'][index]['enabled']
            self.refresh_lists()
            self.changed()

    def remove_saved(self):
        index = self.saved.currentRow()
        if 0 <= index < len(self.config['rules']):
            del self.config['rules'][index]
            self.clear_target()
            self.refresh_lists()
            self.changed()

    def clear_saved(self):
        self.config['rules'] = []
        self.clear_target()
        self.refresh_lists()
        self.changed()

    # ---- 4. esconder ----
    def player_name(self, identity):
        row = next((r for r in self.screen_rows if r.get('id') == identity and r.get('name')), None)
        return row['name'] if row else self.players().get(identity, f'ID {identity}')

    def fill_hides(self):
        selected = self.hides.currentRow()
        groups = self.config['hide_groups']
        self.loading = True
        self.hides.setRowCount(len(groups))
        for index, group in enumerate(groups):
            marks = [self.player_name(i) for i in group['except_ids']]
            marks += [f'"{n}"' for n in group['except_names']]
            marks += [f'espécie {n}' for n in group['except_species']]
            kept = ', '.join(marks)
            kept = ('só: ' if group['mode'] == 'only' else 'menos: ')+kept if marks else (
                'nada marcado' if group['mode'] == 'only' else '—')
            what = ts.HIDE_WHAT[group['what']][0]
            values = (what, group['key'] if group['key'] != ts.NO_KEY else 'sem tecla', kept,
                      'ESCONDENDO' if group['active'] else 'Visível')
            for column, value in enumerate(values):
                cell = item(value)
                if column == 3 and group['active']:
                    cell.setForeground(QColor('#ff8a65'))
                self.hides.setItem(index, column, cell)
        if 0 <= selected < len(groups):
            self.hides.selectRow(selected)
        self.loading = False

    def selected_hide(self):
        index = self.hides.currentRow()
        groups = self.config['hide_groups']
        return groups[index] if 0 <= index < len(groups) and self.hides.selectedItems() else None

    def hide_selected(self):
        if self.loading:
            return
        group = self.selected_hide()
        self.hide_editor.setEnabled(group is not None)
        if group is None:
            return
        self.loading = True
        self.hide_what.setCurrentIndex(self.hide_what.findData(group['what']))
        self.hide_key.setCurrentText(group['key'])
        self.hide_mode.button(1 if group['mode'] == 'only' else 0).setChecked(True)
        self.loading = False
        self.fill_keep()

    def hide_edited(self, *args):
        if self.loading:
            return
        group = self.selected_hide()
        if group is None:
            return
        what = self.hide_what.currentData()
        refill = what != group['what']
        group.update(what=what, key=self.hide_key.currentText(), mode=self.hide_mode.checkedButton().property('mode'),
                     players=False, npcs=False, monsters=False, summons=False)
        group.update(ts.HIDE_WHAT[what][1])
        self.fill_hides()
        if refill:
            self.fill_keep()
        else:
            self.update_keep_count(group)
        self.changed()

    def update_keep_count(self, group):
        count = len(group['except_ids'])+len(group['except_names'])+len(group['except_species'])
        meaning = ('somem quando a tecla ligar (o resto fica)' if group['mode'] == 'only'
                   else 'continuam visíveis quando a tecla ligar')
        self.keep_count.setText(f'{count} marcado(s): {meaning}.')

    def keep_entries(self, group):
        """(chave, texto, na tela) da lista de marcados: por ID (jogadores e unidades na tela) ou por nome."""
        players = group['players']
        kinds = {k for k, on in (('monster', group['monsters']), ('summon', group['summons']), ('npc', group['npcs'])) if on}
        entries = []
        seen_ids, seen_names = set(), set()
        for row in self.screen_rows:  # on screen first
            if (players and row['kind'] == 'player') or row['kind'] in kinds:
                label = row.get('name') or f'ID {row["id"]}'
                kind = KINDS.get(row['kind'], row['kind'])
                entries.append((('id', row['id']), f'{label}  ·  ID {row["id"]}  ·  {kind} (só este)', True))
                seen_ids.add(row['id'])
                if row['kind'] != 'player' and row.get('name') and plain(row['name']) not in seen_names:
                    seen_names.add(plain(row['name']))
                    entries.append((('name', row['name']), f'Todos chamados "{row["name"]}"  ·  {kind}', True))
        for identity in group['except_ids']:
            if identity not in seen_ids:
                entries.append((('id', identity), f'{self.player_name(identity)}  ·  ID {identity} (fora da tela)', False))
                seen_ids.add(identity)
        for name in group['except_names']:
            if plain(name) not in seen_names:
                entries.append((('name', name), f'Todos chamados "{name}"', False))
                seen_names.add(plain(name))
        for species in group['except_species']:
            entries.append((('species', species), f'Espécie {species} ({species_name(species)})', False))
        if players:
            for identity, name in sorted(self.players().items(), key=lambda p: plain(p[1])):
                if identity not in seen_ids:
                    entries.append((('id', identity), f'{name}  ·  ID {identity}  ·  Jogador', False))
        if group['monsters']:
            for row in self.monsters():
                if row.get('name') and plain(row['name']) not in seen_names:
                    seen_names.add(plain(row['name']))
                    entries.append((('name', row['name']), f'Todos chamados "{row["name"]}"  ·  Monstro', False))
        return entries

    def marked(self, group, key):
        field, value = key
        if field == 'id':
            return value in group['except_ids']
        if field == 'name':
            return plain(value) in {plain(n) for n in group['except_names']}
        return value in group['except_species']

    def fill_keep(self, *args):
        group = self.selected_hide()
        self.loading = True
        self.keep_list.clear()
        if group is not None:
            needle = plain(self.keep_search.text().strip())
            count = 0
            for key, text, on_screen in self.keep_entries(group):
                if needle and needle not in plain(text):
                    continue
                checked = self.marked(group, key)
                count += 1
                if count > LIST_LIMIT and not checked:
                    continue
                entry = QListWidgetItem(text + ('   (na tela)' if on_screen else ''))
                entry.setFlags(entry.flags() | Qt.ItemIsUserCheckable)
                entry.setCheckState(Qt.Checked if checked else Qt.Unchecked)
                entry.setData(Qt.UserRole, key)
                self.keep_list.addItem(entry)
            self.update_keep_count(group)
        self.loading = False

    def keep_toggled(self, entry):
        if self.loading:
            return
        group = self.selected_hide()
        if group is None:
            return
        field, value = entry.data(Qt.UserRole)
        target = {'id': group['except_ids'], 'name': group['except_names'], 'species': group['except_species']}[field]
        present = [v for v in target if (plain(v) == plain(value) if field == 'name' else v == value)]
        if entry.checkState() == Qt.Checked and not present:
            target.append(value)
        elif entry.checkState() != Qt.Checked:
            for old in present:
                target.remove(old)
        self.update_keep_count(group)
        self.fill_hides()
        self.changed()

    def add_hide(self):
        used = {g['key'] for g in self.config['hide_groups']}
        key = next((k for k in ('F9', 'F10', 'F11', 'F12', '1', '2', '3', '4', '5') if k not in used), ts.NO_KEY)
        self.config['hide_groups'].append(dict(ts.HIDE_DEFAULT, what='players', key=key, except_ids=[], except_names=[],
                                               except_species=[], players=True))
        self.fill_hides()
        self.hides.selectRow(len(self.config['hide_groups'])-1)
        self.changed()

    def remove_hide(self):
        index = self.hides.currentRow()
        if 0 <= index < len(self.config['hide_groups']):
            del self.config['hide_groups'][index]
            self.fill_hides()
            self.hide_selected()
            self.changed()

    def toggle_selected_hide(self):
        group = self.selected_hide()
        if group is not None:
            group['active'] = not group['active']
            self.fill_hides()
            self.changed()
            self.save_now()

    def mark_summon(self):
        row = self.target_row
        if row is None or row['kind'] in ('player', 'self') or row.get('species') in (None, 0):
            self.status.setText('Escolha a criatura (monstro/invocação) na lista do bloco 1.')
            return
        if row['species'] not in self.config['summon_species']:
            self.config['summon_species'].append(row['species'])
        self.status.setText(f'A espécie {row["species"]} agora conta como invocação.')
        self.show_summon_species()
        self.changed()

    def show_summon_species(self):
        species = self.config['summon_species']
        self.summon_marked_row.setVisible(bool(species))
        names = ', '.join(f'{s} ({species_name(s)})' for s in species)
        self.summon_marked.setText(f'Marcadas por você como invocação: {names}. Elas não contam como monstro.')

    def clear_summon_species(self):
        self.config['summon_species'] = []
        self.show_summon_species()
        self.changed()

    # ---- teclas ----
    def check_keys(self):
        if sys.platform != 'win32':
            return
        import ctypes
        user32 = ctypes.windll.user32
        used = {r['key'] for r in self.config['rules']} | {g['key'] for g in self.config['hide_groups']}
        struck = set()
        for key in used & set(ts.KEYS):
            down = bool(user32.GetAsyncKeyState(ts.KEYS[key]) & 0x8000)
            was, self.keys_down[key] = self.keys_down.get(key, False), down
            if down and not was:
                struck.add(key)
        if not struck:
            return
        from PySide6.QtWidgets import QApplication
        front = user32.GetForegroundWindow()
        if front == int(self.window().winId()):
            if isinstance(QApplication.focusWidget(), QLineEdit):
                return  # typing in the panel (e.g. a search box)
        elif front != self.find_game():
            return
        for rule in self.config['rules']:
            if rule['key'] in struck:
                rule['enabled'] = not rule['enabled']
        for group in self.config['hide_groups']:
            if group['key'] in struck:
                group['active'] = not group['active']
        self.save_now()  # first: the relay applies it on its next 15 ms look
        self.apply_zoom()
        self.overlay.show_config(self.config)
        self.refresh_lists()
        self.fill_hides()

    def find_game(self):
        """The game window, looked up again at most every 3 s (a full window scan is slow)."""
        stamp, hwnd = self.game_window
        if time.monotonic()-stamp > 3 or not hwnd:
            from .radar_overlay import find_game_window
            hwnd = find_game_window()
            self.game_window = (time.monotonic(), hwnd)
        return hwnd

    # ---- overlay ----
    def show_overlay(self):
        self.overlay.show_config(self.config)
        self.overlay.place(self.config['overlay']['position'])
        self.overlay.show()

    def set_overlay(self, visible):
        self.config['overlay']['visible'] = visible
        if visible:
            self.show_overlay()
        else:
            self.overlay.hide()
        self.changed()

    def overlay_moved(self, position):
        self.config['overlay']['position'] = position
        self.changed()
