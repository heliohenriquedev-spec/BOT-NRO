"""Aba PvP -> X1: import behaviour files and pick one per character."""
import json
from PySide6.QtWidgets import (QGroupBox, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel, QFileDialog,
                               QDialog, QPlainTextEdit, QDialogButtonBox)
from . import x1_scripts


class X1Box(QGroupBox):
    def __init__(self):
        super().__init__('X1: comportamento por personagem (arquivo de regras)')
        self.character = None
        layout = QVBoxLayout(self)
        hint = QLabel('Cada personagem usa um arquivo .json de regras: lidas de cima para baixo, a primeira cujas '
                      'condicoes valem decide a acao (atacar, habilidade, afastar, aproximar, esperar, item, parar). '
                      'O arquivo e so dados: nao executa codigo. Veja docs/exemplo_x1.json.')
        hint.setWordWrap(True); layout.addWidget(hint)
        row = QHBoxLayout(); layout.addLayout(row)
        self.files = QComboBox(); row.addWidget(self.files, 1)
        for title, callback in (('Importar arquivo', self.import_file), ('Usar para este personagem', self.use),
                                ('Ver regras', self.preview), ('Importar exemplo', self.import_example)):
            button = QPushButton(title); button.clicked.connect(callback); row.addWidget(button)
        self.status = QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.reload()

    def reload(self):
        current = self.files.currentText()
        self.loaded = x1_scripts.scripts()
        self.files.clear(); self.files.addItem('(nenhum)', '')
        for name, data in self.loaded.items():
            self.files.addItem(name if isinstance(data, dict) else name+' (com erro)', name)
        index = self.files.findText(current)
        if index >= 0:
            self.files.setCurrentIndex(index)
        self.show_status()

    def set_character(self, name):
        if name != self.character:
            self.character = name
            self.show_status()

    def show_status(self):
        mine = x1_scripts.chosen().get(self.character or '')
        problem = self.loaded.get(mine) if mine else None
        self.status.setText(('Personagem: '+self.character+' • arquivo: '+(mine or 'nenhum') if self.character else
                             'Entre no personagem para escolher o arquivo dele.')
                            + (f' • ERRO: {problem}' if isinstance(problem, str) else ''))

    def import_file(self, path=None):
        path = path or QFileDialog.getOpenFileName(self, 'Importar arquivo de X1', '', 'Regras de X1 (*.json)')[0]
        if not path:
            return
        try:
            name = x1_scripts.import_file(path)
        except (OSError, ValueError) as exc:
            self.status.setText('Arquivo nao importado: '+str(exc)); return
        self.reload(); self.files.setCurrentIndex(self.files.findData(name))
        self.status.setText('Importado: '+name+'. Use "Usar para este personagem" para escolher.')

    def import_example(self):
        self.import_file(str(x1_scripts.EXAMPLE))

    def use(self):
        if not self.character:
            self.status.setText('Entre no personagem pelo bot antes de escolher o arquivo dele.'); return
        name = self.files.currentData()
        if name and not isinstance(self.loaded.get(name), dict):
            self.status.setText('Corrija o arquivo antes: '+str(self.loaded.get(name))); return
        x1_scripts.choose(self.character, name)
        self.show_status()

    def preview(self):
        name = self.files.currentData()
        data = self.loaded.get(name)
        if not name:
            return
        dialog = QDialog(self); dialog.setWindowTitle(name); layout = QVBoxLayout(dialog)
        text = QPlainTextEdit(json.dumps(data, ensure_ascii=False, indent=2) if isinstance(data, dict) else 'ERRO: '+str(data))
        text.setReadOnly(True); layout.addWidget(text)
        close = QDialogButtonBox(QDialogButtonBox.Close); close.rejected.connect(dialog.reject); layout.addWidget(close)
        dialog.resize(640, 520); dialog.exec()
