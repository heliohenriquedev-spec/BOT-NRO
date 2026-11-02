"""Isolated editor for the learned Kuchiyose profiles."""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QComboBox, QTableWidget,
    QTableWidgetItem, QCheckBox, QDoubleSpinBox, QSpinBox, QDialogButtonBox, QHeaderView)


class KuchiyoseDialog(QDialog):
    def __init__(self, entries, mode='cycle', parent=None):
        super().__init__(parent)
        self.setWindowTitle('Configurar Kuchiyose')
        self.resize(860, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Somente Kuchiyose aprendidas. Menor prioridade primeiro. Uma ativa por vez, perto de alvos.'))
        self.mode = QComboBox()
        self.mode.addItem('Ciclo continuo: 1, 2, 3, depois recomeca', 'cycle')
        self.mode.addItem('Prioridade disponivel: volta a maior prioridade assim que recarregar', 'priority')
        self.mode.setCurrentIndex(max(0, self.mode.findData(mode)))
        layout.addWidget(self.mode)
        self.table = QTableWidget(len(entries), 5)
        self.table.setHorizontalHeaderLabels(['Usar', 'Kuchiyose', 'Duracao (s)', 'Recarga local (s)', 'Prioridade'])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.rows = {}
        for i, (identity, name, profile) in enumerate(entries):
            enabled=QCheckBox();enabled.setChecked(profile['enabled'])
            duration=QDoubleSpinBox();duration.setRange(0,86400);duration.setDecimals(1)
            duration.setSpecialValueText('Aprender / efeito');duration.setValue(profile.get('summon_duration',0))
            cooldown=QDoubleSpinBox();cooldown.setRange(.1,86400);cooldown.setDecimals(2);cooldown.setValue(profile['interval'])
            priority=QSpinBox();priority.setRange(0,999);priority.setValue(profile.get('summon_priority',0))
            self.rows[identity]={'enabled':enabled,'duration':duration,'cooldown':cooldown,'priority':priority}
            self.table.setItem(i,1,QTableWidgetItem(name))
            for col,w in ((0,enabled),(2,duration),(3,cooldown),(4,priority)):self.table.setCellWidget(i,col,w)
        layout.addWidget(self.table)
        note=QLabel('Duracao 0 acompanha o efeito ou a duracao aprendida. A recarga informada pelo servidor continua obrigatoria. Mudar a prioridade nao substitui uma invocacao ainda ativa.')
        note.setWordWrap(True);layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def values(self):
        return {identity:dict(enabled=r['enabled'].isChecked(), role='summon',
                summon_duration=r['duration'].value(), interval=r['cooldown'].value(),
                summon_priority=r['priority'].value()) for identity,r in self.rows.items()}
