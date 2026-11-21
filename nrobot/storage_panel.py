"""Aba "Armazem": deposito automatico por peso e janela para retirar itens do @storage."""
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QSpinBox,
                               QLineEdit, QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
                               QDialogButtonBox, QGroupBox, QMessageBox)

from . import storage

ITEMS_PATH = Path(__file__).resolve().parents[1]/'data/recursos/itens.json'


def item_names():
    try:
        return json.loads(ITEMS_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


class WithdrawDialog(QDialog):
    """Pesquisa por nome ou ID; marque os itens e a quantidade (0 = tudo o que estiver guardado)."""
    LIMIT = 300

    def __init__(self, parent, stored):
        super().__init__(parent)
        self.setWindowTitle('Retirar do armazem')
        self.resize(620, 560)
        self.names = item_names()
        self.stored = {}
        for item in stored:
            self.stored[item['item_id']] = self.stored.get(item['item_id'], 0)+item['amount']
        self.chosen = {}  # item_id -> amount
        layout = QVBoxLayout(self)
        self.only_stored = QCheckBox('Mostrar so o que o bot viu no armazem deste personagem')
        self.only_stored.setChecked(bool(self.stored))
        self.only_stored.toggled.connect(self.refresh)
        layout.addWidget(self.only_stored)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Pesquisar por nome ou ID')
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Retirar', 'ID', 'Nome', 'Quantidade (0 = tudo)'])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        layout.addWidget(self.table, 1)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Retirar selecionados')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def candidates(self):
        text = self.search.text().strip().lower()
        pool = (self.stored if self.only_stored.isChecked() else
                {int(k): 0 for k in self.names if str(k).isdigit()})
        result = []
        for identity in sorted(pool):
            name = self.names.get(str(identity), f'item {identity}')
            if text and not (text == str(identity) or text in name.lower() or str(identity).startswith(text)):
                continue
            result.append((identity, name))
            if len(result) >= self.LIMIT:
                break
        chosen = [(i, self.names.get(str(i), f'item {i}')) for i in self.chosen if i not in dict(result)]
        return chosen+result

    def refresh(self):
        rows = self.candidates()
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for row, (identity, name) in enumerate(rows):
            check = QCheckBox()
            check.setChecked(identity in self.chosen)
            check.toggled.connect(lambda on, i=identity, r=row: self.toggle(i, r, on))
            holder = QWidget()
            box = QHBoxLayout(holder)
            box.setContentsMargins(6, 0, 0, 0)
            box.addWidget(check)
            self.table.setCellWidget(row, 0, holder)
            self.table.setItem(row, 1, QTableWidgetItem(str(identity)))
            stored = self.stored.get(identity)
            self.table.setItem(row, 2, QTableWidgetItem(name+(f'  (guardado: {stored})' if stored else '')))
            amount = QSpinBox()
            amount.setRange(0, 30000)
            amount.setValue(self.chosen.get(identity, 0))
            amount.valueChanged.connect(lambda value, i=identity: self.chosen.__setitem__(i, value) if i in self.chosen else None)
            self.table.setCellWidget(row, 3, amount)
        self.table.blockSignals(False)
        self.update_summary()

    def toggle(self, identity, row, on):
        if on:
            spin = self.table.cellWidget(row, 3)
            self.chosen[identity] = spin.value() if spin else 0
        else:
            self.chosen.pop(identity, None)
        self.update_summary()

    def update_summary(self):
        self.summary.setText(f'{len(self.chosen)} item(ns) selecionado(s)' if self.chosen
                             else 'Nenhum item selecionado')

    def selection(self):
        return [dict(item_id=i, amount=a) for i, a in self.chosen.items()]


class StoragePanel(QWidget):
    def __init__(self):
        super().__init__()
        self.state = {}
        layout = QVBoxLayout(self)
        info = QLabel('Na primeira vez, ensine ao bot como o jogo guarda, retira e fecha o armazem: clique em '
                      'cada "Aprender" e faca a acao no jogo, com o @storage aberto. Depois disso o bot repete sozinho.')
        info.setWordWrap(True)
        layout.addWidget(info)
        learn = QGroupBox('Aprendizado')
        row = QHBoxLayout(learn)
        for label, what in (('Aprender guardar', 'store'), ('Aprender retirar', 'take'), ('Aprender fechar', 'close')):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, w=what: self.request('storage_learn', what=w))
            row.addWidget(button)
        cancel = QPushButton('Cancelar')
        cancel.clicked.connect(lambda: self.request('storage_learn_cancel'))
        row.addWidget(cancel)
        layout.addWidget(learn)
        auto = QGroupBox('Deposito automatico')
        box = QVBoxLayout(auto)
        line = QHBoxLayout()
        self.auto = QCheckBox('Ao passar de')
        self.threshold = QSpinBox()
        self.threshold.setRange(10, 95)
        self.threshold.setSuffix('%')
        line.addWidget(self.auto)
        line.addWidget(self.threshold)
        line.addWidget(QLabel('do peso durante a caca: @storage, guarda tudo das abas Item e Etc, fecha e volta a cacar'), 1)
        box.addLayout(line)
        keep = QHBoxLayout()
        keep.addWidget(QLabel('Nunca guardar (IDs separados por virgula):'))
        self.keep = QLineEdit()
        keep.addWidget(self.keep, 1)
        box.addLayout(keep)
        save = QPushButton('Salvar opcoes')
        save.clicked.connect(self.store)
        self.auto.toggled.connect(self.store)
        box.addWidget(save)
        refused = QHBoxLayout()
        self.refused = QLabel('')
        self.refused.setWordWrap(True)
        refused.addWidget(self.refused, 1)
        retry = QPushButton('Tentar de novo os recusados')
        retry.clicked.connect(self.clear_refused)
        refused.addWidget(retry)
        box.addLayout(refused)
        layout.addWidget(auto)
        withdraw = QPushButton('Retirar itens do armazem...')
        withdraw.clicked.connect(self.open_withdraw)
        layout.addWidget(withdraw)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch(1)
        self.show_config(storage.load())

    def request(self, command, **values):
        from .hunt_dialog import send_command
        if not send_command(self, command, **values):
            self.status.setText('Abra a conexao pelo painel principal primeiro.')

    def show_config(self, config):
        for widget, value in ((self.auto, config['auto_enabled']), (self.threshold, config['threshold'])):
            widget.blockSignals(True)
            (widget.setChecked if widget is self.auto else widget.setValue)(value)
            widget.blockSignals(False)
        self.keep.setText(', '.join(str(i) for i in config['keep_ids']))
        self.show_refused(config.get('refused_ids') or [])

    def show_refused(self, ids):
        self.refused.setText('Itens que o servidor nao deixa guardar (nao sao tentados de novo): '
                             + (', '.join(str(i) for i in ids) if ids else 'nenhum'))

    def store(self, *args):
        keep = sorted({int(p) for p in self.keep.text().replace(';', ',').split(',') if p.strip().isdigit()})
        values = dict(auto_enabled=self.auto.isChecked(), threshold=self.threshold.value(), keep_ids=keep)
        try:
            config = storage.save(values)
        except OSError as exc:
            QMessageBox.warning(self, 'Opcoes nao salvas', str(exc))
            return
        self.show_config(config)
        from .hunt_dialog import send_command
        send_command(self, 'storage_config', **values)  # the running bot uses them right away

    def clear_refused(self):
        try:
            self.show_config(storage.save(dict(refused_ids=[])))
        except OSError as exc:
            QMessageBox.warning(self, 'Opcoes nao salvas', str(exc))
            return
        from .hunt_dialog import send_command
        send_command(self, 'storage_config', refused_ids=[])

    def open_withdraw(self):
        name = self.state.get('character') or ''
        stored = storage.load_contents().get(name, [])
        dialog = WithdrawDialog(self, stored)
        if dialog.exec() != QDialog.Accepted:
            return
        items = dialog.selection()
        if not items:
            return
        self.request('storage_withdraw', items=items)

    def update_state(self, state):
        self.state = state or {}
        s = self.state
        if 'refused_ids' in s:
            self.show_refused(s['refused_ids'])
        parts = []
        if s.get('weight') is not None and s.get('max_weight'):
            parts.append(f"Peso: {s['weight']/10:g}/{s['max_weight']/10:g} ({100*s['weight']/s['max_weight']:.0f}%)")
        missing = s.get('missing') or []
        parts.append('Falta aprender: '+', '.join(missing) if missing else 'Pacotes do armazem aprendidos')
        if s.get('learning'):
            parts.append('Aguardando a acao no jogo')
        if s.get('busy'):
            parts.append('Usando o armazem agora')
        if s.get('reason'):
            parts.append(s['reason'])
        self.status.setText(' • '.join(parts))
