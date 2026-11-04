"""Isolated editor for the learned Kuchiyose profiles."""
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QComboBox, QTableWidget,
    QTableWidgetItem, QCheckBox, QDoubleSpinBox, QSpinBox, QDialogButtonBox, QHeaderView)


class KuchiyoseDialog(QDialog):
    def __init__(self, entries, mode='cycle', parent=None, runtime=None):
        super().__init__(parent)
        self.setWindowTitle('Configurar Kuchiyose')
        self.resize(1060, 450)
        self.runtime = runtime or {}
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Somente Kuchiyose aprendidas. Menor prioridade primeiro. Uma ativa por vez, perto de alvos.'))
        self.mode = QComboBox()
        self.mode.addItem('Ciclo continuo: 1, 2, 3, depois recomeca', 'cycle')
        self.mode.addItem('Prioridade disponivel: volta a maior prioridade assim que recarregar', 'priority')
        self.mode.setCurrentIndex(max(0, self.mode.findData(mode)))
        layout.addWidget(self.mode)
        self.table = QTableWidget(len(entries), 6)
        self.table.setHorizontalHeaderLabels(['Usar', 'Kuchiyose', 'Duracao ativa (s)', 'Recarga da mesma (s)', 'Prioridade', 'Recarga restante'])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.rows = {}
        for i, (identity, name, profile) in enumerate(entries):
            enabled=QCheckBox();enabled.setChecked(profile['enabled'])
            duration=QDoubleSpinBox();duration.setRange(0,86400);duration.setDecimals(1)
            duration.setSpecialValueText('Aprender / efeito');duration.setValue(profile.get('summon_duration',0))
            cooldown=QDoubleSpinBox();cooldown.setRange(.1,86400);cooldown.setDecimals(2);cooldown.setValue(profile['interval'])
            duration.setToolTip('Duracao maior que zero determina quando liberar a fila, independentemente de icones de recarga. Ao terminar, outra Kuchiyose pronta pode entrar imediatamente.')
            cooldown.setToolTip('Contada desde o envio desta habilidade. Nao e uma espera global entre Kuchiyose. Exemplo: uso em 0s e recarga 46s libera a mesma em 46s.')
            priority=QSpinBox();priority.setRange(0,999);priority.setValue(profile.get('summon_priority',0))
            self.rows[identity]={'enabled':enabled,'duration':duration,'cooldown':cooldown,'priority':priority}
            self.table.setItem(i,1,QTableWidgetItem(name))
            for col,w in ((0,enabled),(2,duration),(3,cooldown),(4,priority)):self.table.setCellWidget(i,col,w)
        layout.addWidget(self.table)
        self.timing_note = QLabel()
        self.timing_note.setWordWrap(True)
        layout.addWidget(self.timing_note)
        for row in self.rows.values():
            row['enabled'].toggled.connect(self.update_timing_note)
            row['duration'].valueChanged.connect(self.update_timing_note)
            row['cooldown'].valueChanged.connect(self.update_timing_note)
        self.update_timing_note()
        self.update_cooldowns()
        self.cooldown_timer = QTimer(self)
        self.cooldown_timer.timeout.connect(self.update_cooldowns)
        self.cooldown_timer.start(500)
        note=QLabel('Duracao maior que 0 libera a fila ao terminar; 0 acompanha efeito ou duracao aprendida. A recarga informada pelo servidor continua obrigatoria. Mudar a prioridade nao substitui uma invocacao ainda ativa.')
        note.setWordWrap(True);layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def update_timing_note(self, *args):
        rows = [r for r in self.rows.values() if r['enabled'].isChecked()]
        if len(rows) == 1 and rows[0]['duration'].value() > 0 and rows[0]['cooldown'].value() > rows[0]['duration'].value():
            duration, cooldown = rows[0]['duration'].value(), rows[0]['cooldown'].value()
            text = (f'Somente uma Kuchiyose marcada: {duration:g}s ativa, recarga {cooldown:g}s desde o uso. '
                    f'Lacuna local prevista: aproximadamente {cooldown-duration:g}s. Marque outra Kuchiyose pronta para alternar durante essa recarga.')
        else:
            text = 'Duas contagens independentes: termina a duracao da ativa -> procura outra pronta; a recarga bloqueia somente a mesma habilidade. Se todas estiverem recarregando, a fila aguarda.'
        self.timing_note.setText(text)

    def update_cooldowns(self):
        cooldowns = self.runtime.get('cooldowns', {})
        now = time.monotonic()
        for i, identity in enumerate(self.rows):
            entry = cooldowns.get(str(identity), cooldowns.get(identity))
            text = f"{max(0, entry['ready_at']-now):.1f} s" if entry is not None else 'Sem dados da sessao'
            item = self.table.item(i,5)
            if item is None:
                self.table.setItem(i,5,QTableWidgetItem(text))
            elif item.text() != text:
                item.setText(text)

    def values(self):
        return {identity:dict(enabled=r['enabled'].isChecked(), role='summon',
                summon_duration=r['duration'].value(), interval=r['cooldown'].value(),
                summon_priority=r['priority'].value()) for identity,r in self.rows.items()}
