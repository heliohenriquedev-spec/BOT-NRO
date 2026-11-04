"""Rank, hunting targets and description shared by every route using a mission."""
import copy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QLineEdit,QLabel,QPlainTextEdit,
                              QListWidget,QListWidgetItem,QDialogButtonBox)
from .npc_labels import clean,plain,rank


class MissionDetails(QDialog):
    def __init__(self,mission,parent=None):
        super().__init__(parent);self.mission=copy.deepcopy(mission);self.setWindowTitle('Rank e monstros da missao')
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.name=QLineEdit(clean(mission['name']));self.rank=QLineEdit(mission.get('rank') or rank(mission['name']))
        self.map=QLineEdit(mission.get('target_map',''));self.map.setPlaceholderText('Mapa dos monstros, ex.: anthell02')
        for title,field in [('Missao',self.name),('Rank',self.rank),('Mapa de caca',self.map)]:form.addRow(title,field)
        label=QLabel('Marque os monstros desta missao. Descricoes recebidas do NPC ajudam na identificacao; voce pode corrigir os alvos manualmente. Esses nomes aparecem ao selecionar a missao em uma rota.')
        label.setWordWrap(True);layout.addWidget(label)
        self.search=QLineEdit();self.search.setPlaceholderText('Buscar monstro por nome ou ID');layout.addWidget(self.search)
        self.monsters=QListWidget();layout.addWidget(self.monsters,1)
        from .monster_db import all_monsters,name_of
        known={m['species_id']:m['name'] for m in all_monsters()}
        for identity in mission.get('monster_ids',[]):known.setdefault(identity,name_of(identity))
        for identity,name in sorted(known.items(),key=lambda kv:plain(kv[1])):
            item=QListWidgetItem(f'{name} (ID {identity})');item.setData(Qt.UserRole,identity)
            item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(Qt.Checked if identity in mission.get('monster_ids',[]) else Qt.Unchecked)
            self.monsters.addItem(item)
        self.search.textChanged.connect(self.filter)
        self.description=QPlainTextEdit(mission.get('description',''));self.description.setPlaceholderText('Descricao da quest recebida do quadro ou anotacao manual');self.description.setMaximumHeight(100);layout.addWidget(self.description)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('Salvar alvos');buttons.button(QDialogButtonBox.Cancel).setText('Cancelar')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        area=self.screen().availableGeometry();self.resize(min(700,area.width()-40),min(680,area.height()-60))

    def filter(self,value):
        value=plain(value)
        for i in range(self.monsters.count()):self.monsters.item(i).setHidden(value not in plain(self.monsters.item(i).text()))

    def accept(self):
        if not clean(self.name.text()):return
        self.mission.update(name=clean(self.name.text()),rank=clean(self.rank.text()),target_map=self.map.text().strip(),
                            description=clean(self.description.toPlainText()),monster_ids_manual=True,monster_ids=[self.monsters.item(i).data(Qt.UserRole) for i in range(self.monsters.count()) if self.monsters.item(i).checkState()==Qt.Checked])
        super().accept()
