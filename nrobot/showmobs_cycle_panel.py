"""Aba "Ciclo @showmobs": edita as etapas e inicia/para o ciclo."""
import json
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit, QComboBox

from . import showmobs_cycle
from .mob_scan import MobScan


class ShowmobsCyclePanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        info = QLabel('Cada etapa: sai do ponto salvo, viaja ate o mapa (portais aprendidos e Viajante Ninja), '
                      'usa @showmobs no monstro, vai ate ele e mata 1, da @voltar e so entao passa para a proxima. '
                      'Depois da ultima, recomeca. Se o monstro ainda nao renasceu, fica no mapa e pergunta de novo '
                      f'a cada {MobScan.CYCLE_INTERVAL:.0f} s. Para parar, use "Parar ciclo" ou pause a fila na aba Rotas.')
        info.setWordWrap(True)
        layout.addWidget(info)
        hint = QLabel('Etapas (JSON). "species" e o numero usado no @showmobs; "portal" opcional forca a saida por um portal. '
                      '"salto_ninja": usa o Salto Ninja por cima das paredes na viagem quando economiza ao menos '
                      '"economia_minima" celulas ("ativo": false desliga).')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.editor = QPlainTextEdit()
        layout.addWidget(self.editor, 3)
        row = QHBoxLayout()
        self.start_stage = QComboBox()
        row.addWidget(QLabel('Comecar pela etapa:'))
        row.addWidget(self.start_stage, 1)
        layout.addLayout(row)
        buttons = QHBoxLayout()
        for title, callback in [('Salvar etapas', self.save), ('Recarregar', self.reload),
                                ('Iniciar ciclo', self.start), ('Parar ciclo', self.stop)]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.reload()

    def fill_stages(self, config):
        chosen = self.start_stage.currentIndex()  # kept: "Iniciar ciclo" saves (and refills) first
        self.start_stage.blockSignals(True)
        self.start_stage.clear()
        self.start_stage.addItem('Automatico (a etapa do mapa onde o personagem esta)')
        for i, s in enumerate(config['stages'], 1):
            self.start_stage.addItem(f"{i}. {s['name']} ({s['map']}, @showmobs {s['species']})")
        self.start_stage.setCurrentIndex(chosen if 0 <= chosen < self.start_stage.count() else 0)
        self.start_stage.blockSignals(False)

    def reload(self):
        try:
            config = showmobs_cycle.load()
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))
            return
        self.editor.setPlainText(json.dumps(config, ensure_ascii=False, indent=2))
        self.fill_stages(config)
        self.status.setText('')

    def save(self):
        try:
            config = showmobs_cycle.save(json.loads(self.editor.toPlainText()))
        except (OSError, ValueError) as exc:
            self.status.setText('Nao salvo: '+str(exc))
            return False
        self.editor.setPlainText(json.dumps(config, ensure_ascii=False, indent=2))
        self.fill_stages(config)
        self.status.setText('Etapas salvas.')
        return True

    def start(self):
        if not self.save():
            return
        from .hunt_dialog import send_command
        if not send_command(self, 'quest_showmobs_cycle', start_stage=self.start_stage.currentIndex()-1):
            self.status.setText('Abra a conexao pelo painel principal primeiro.')
            return
        self.status.setText('Ciclo enviado. Acompanhe na aba Rotas e no registro ([CICLO]).')

    def stop(self):
        from .hunt_dialog import send_command
        if send_command(self, 'quest_stop'):
            self.status.setText('Pedido de parada enviado.')
