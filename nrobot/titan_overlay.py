"""Titan side overlay: a small always-on-top window listing every Titan shortcut and its state.

Meant to sit beside the game (outside it): tecla, o que faz, ligado/desligado. Arraste para
mover; a posição fica no titan.json (campo overlay). Only reads the panel's config: nothing
here changes the game.
"""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from . import titan_settings as ts

STYLE = '''
QFrame#TitanOverlay { background: rgba(12, 20, 35, 230); border: 1px solid #2f4462; border-radius: 10px; }
QLabel { color: #d7e2f0; font-size: 12px; background: transparent; }
QLabel#Title { font-weight: 700; color: #8fd3ff; }
QLabel#Key { font-weight: 700; color: #ffffff; background: #2a3a52; border-radius: 4px; padding: 1px 6px; }
QLabel#On { font-weight: 700; color: #ff8a65; }
QLabel#Off { color: #7a8699; }
QLabel#Empty { color: #7a8699; }
'''


def percent(scale):
    return f'{round(scale*100)}%'


def shortcut_rows(config):
    """(tecla, descrição, ligado): keyed shortcuts in key order, then the ones without a key."""
    rows = []
    for group in config['hide_groups']:
        what = ts.HIDE_WHAT[group['what']][0].lower()
        marked = len(group['except_ids'])+len(group.get('except_names', []))+len(group.get('except_species', []))
        if group.get('mode') == 'only':
            text = f'Esconder {marked} marcado(s) ({what})'
        else:
            text = f'Esconder {what}' + (f' (menos {marked})' if marked else '')
        rows.append((group['key'], text, group['active']))
    for rule in config['rules']:
        parts = []
        if rule['scale'] != 1.0:
            parts.append(percent(rule['scale']))
        if rule['color'] != 'none':
            parts.append(ts.COLORS[rule['color']]['label'].split(' (')[0].lower())
        rows.append((rule['key'], f'{rule["label"] or rule["value"]}: {", ".join(parts)}', rule['enabled']))
    order = list(ts.KEYS)
    keyed = sorted((r for r in rows if r[0] in ts.KEYS), key=lambda r: order.index(r[0]))
    return keyed + [r for r in rows if r[0] not in ts.KEYS]


class TitanOverlay(QWidget):
    def __init__(self, on_moved=None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.on_moved = on_moved
        self.drag = None
        self.shown_rows = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame()
        self.frame.setObjectName('TitanOverlay')
        self.frame.setStyleSheet(STYLE)
        outer.addWidget(self.frame)
        box = QVBoxLayout(self.frame)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(6)
        title = QLabel('TITAN — atalhos')
        title.setObjectName('Title')
        box.addWidget(title)
        host = QWidget()
        self.grid = QGridLayout(host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(4)
        box.addWidget(host)
        self.setToolTip('Arraste para mover. Liga/desliga na aba Titan.')

    def show_config(self, config):
        enabled = bool(config.get('enabled'))
        rows = shortcut_rows(config) if enabled else []
        if (enabled, rows) == self.shown_rows:
            return
        self.shown_rows = (enabled, rows)
        while self.grid.count():
            widget = self.grid.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        if not enabled or not rows:
            empty = QLabel('Titan desligado' if not enabled else 'Nenhum atalho na aba Titan')
            empty.setObjectName('Empty')
            self.grid.addWidget(empty, 0, 0)
        for index, (key, text, on) in enumerate(rows):
            key_label = QLabel(key if key in ts.KEYS else '—')
            key_label.setObjectName('Key')
            key_label.setAlignment(Qt.AlignCenter)
            state = QLabel('LIGADO' if on else 'desligado')
            state.setObjectName('On' if on else 'Off')
            self.grid.addWidget(key_label, index, 0)
            self.grid.addWidget(QLabel(text), index, 1)
            self.grid.addWidget(state, index, 2, Qt.AlignRight)
        self.adjustSize()

    def place(self, position):
        if isinstance(position, list) and len(position) == 2:
            point = QPoint(int(position[0]), int(position[1]))
            if any(s.availableGeometry().contains(point) for s in QApplication.screens()):
                self.move(point)
                return
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right()-self.width()-16, screen.top()+120)  # right edge by default

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag = event.globalPosition().toPoint()-self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            self.move(event.globalPosition().toPoint()-self.drag)

    def mouseReleaseEvent(self, event):
        if self.drag is not None:
            self.drag = None
            if self.on_moved:
                self.on_moved([self.x(), self.y()])
