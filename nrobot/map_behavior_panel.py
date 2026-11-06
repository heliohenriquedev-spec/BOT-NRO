"""Import/export controls for declarative map profiles."""
import json
from pathlib import Path
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QFileDialog, QMessageBox, QPlainTextEdit
from . import map_behavior as profiles

class MapBehaviorPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        label = QLabel('Importe um perfil JSON para definir o combate em um mapa. A patrulha continua normal. Aplicacao automatica ao entrar; quests usam suas proprias regras. Um perfil por mapa. As configuracoes gerais voltam ao sair.')
        label.setWordWrap(True)
        layout.addWidget(label)
        self.list = QListWidget()
        layout.addWidget(self.list, 2)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 3)
        buttons = QHBoxLayout()
        for title, callback in [('Importar perfil', self.import_file), ('Exportar selecionado', self.export_file), ('Ativar / desativar', self.toggle), ('Remover', self.remove)]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.list.currentRowChanged.connect(self.describe)
        self.reload()

    def reload(self):
        try:
            self.profiles = profiles.load()
        except (OSError, ValueError) as exc:
            self.profiles = []
            self.details.setPlainText(str(exc))
        self.list.clear()
        for p in self.profiles:
            self.list.addItem(('Ativo' if p['enabled'] else 'Desativado')+' | '+p['map']+' | '+p['name'])

    def selected(self):
        row = self.list.currentRow()
        return self.profiles[row] if 0 <= row < len(self.profiles) else None

    def describe(self, row):
        p = self.selected()
        self.details.setPlainText((p['description']+'\n'+json.dumps({k:p[k] for k in ('settings','combat') if k in p}, ensure_ascii=False, indent=2)) if p else '')

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Importar comportamento', '', 'Perfil JSON (*.json)')
        if not path:
            return
        try:
            if Path(path).stat().st_size > 100000:
                raise ValueError('Arquivo excede 100 KB')
            p = profiles.validate(json.loads(Path(path).read_text(encoding='utf-8-sig')))
            current = profiles.load()
            if any(x['map']==p['map'] for x in current) and QMessageBox.question(self, 'Substituir perfil?', 'Substituir o perfil de '+p['map']+'?') != QMessageBox.Yes:
                return
            profiles.save([x for x in current if x['map']!=p['map']]+[p])
            self.reload()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Perfil nao importado', str(exc))

    def export_file(self):
        p = self.selected()
        if not p:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Exportar perfil', p['map']+'.json', 'Perfil JSON (*.json)')
        if path:
            try:
                Path(path).write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding='utf-8')
            except OSError as exc:
                QMessageBox.warning(self, 'Erro ao exportar', str(exc))

    def modify(self, remove=False):
        p = self.selected()
        if not p:
            return
        try:
            current = profiles.load()
            if remove:
                current = [x for x in current if x['map']!=p['map']]
            else:
                for x in current:
                    if x['map']==p['map']:
                        x['enabled'] = not x['enabled']
            profiles.save(current)
            self.reload()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Erro ao salvar', str(exc))

    def toggle(self):
        self.modify()

    def remove(self):
        if self.selected() and QMessageBox.question(self, 'Remover perfil?', 'Remover o perfil selecionado?') == QMessageBox.Yes:
            self.modify(True)
