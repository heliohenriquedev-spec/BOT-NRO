"""Quest routes: the missions to take and the hunting map to go to.

Monsters and amounts come from the missions themselves ("Monstros necessarios" of each one),
paths to hunting maps are recorded once in "Mapas de caca" and picked by name.
"""
import copy
from PySide6.QtCore import Qt, Signal, QItemSelectionModel
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QFormLayout,QLabel,QPushButton,QListWidget,QListWidgetItem,
    QLineEdit,QDialog,QDialogButtonBox,QTableWidget,QTableWidgetItem,QComboBox,QMessageBox,QTabWidget,QGroupBox,QSpinBox,
    QInputDialog,QCheckBox)
from .quest_routes import load, save, validate_routes
from .responsive_ui import FlowLayout, scroll_page
from .npc_labels import clean, plain, rank, mission_label, mission_option
from . import map_routes
from .portals import PortalGuard
map_routes_key=PortalGuard.key


class QuestQueueList(QListWidget):
    order_changed = Signal()

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setDragDropMode(QListWidget.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDropIndicatorShown(True)

    def dropEvent(self, event):
        before = [self.item(i).data(Qt.UserRole) for i in range(self.count())]
        blocked = self.blockSignals(True)
        try:
            super().dropEvent(event)
        finally:
            self.blockSignals(blocked)
        after = [self.item(i).data(Qt.UserRole) for i in range(self.count())]
        if before != after:
            self.order_changed.emit()

TYPES={'walk':'Caminhar','portal':'Entrar no portal','npc':'Falar com NPC','select':'Escolher opcao',
       'next':'Proximo dialogo','close':'Fechar dialogo','cancel':'Cancelar/fechar menu','wait_map':'Confirmar mapa de chegada','wait_transfer':'Aguardar teletransporte Retorno',
       'select_free_slot':'Escolher slot livre','select_mission_slot':'Localizar missao no slot','verify_slot':'Confirmar missao aceita','verify_slot_absent':'Confirmar entrega no slot'}


RANK_LETTERS=('D','C','B','A','S','SS')


def rank_order(label):
    """Rank D-1 < D-2 < ... < C-1 < ... < SS; anything without a rank goes last."""
    import re
    found=re.match(r'Rank ([A-Z]{1,3})(?:-(\d+))?$',rank(label))
    if not found:return (len(RANK_LETTERS)+1,0,plain(label))
    letter=RANK_LETTERS.index(found[1]) if found[1] in RANK_LETTERS else len(RANK_LETTERS)
    return (letter,int(found[2] or 0),plain(label))


def linked_missions(route=None):
    """{mission id: [names of the other quests that already take it]}."""
    try:routes=load()
    except (OSError,ValueError):return {}
    own=(route or {}).get('id');result={}
    for other in routes:
        if own and other.get('id')==own:continue
        for identity in other.get('mission_ids',[]):
            result.setdefault(identity,[]).append(other.get('name') or 'sem nome')
    return result


def mission_choices(library):
    """Every mission the boards offer: the registered ones and every rank seen in their menus."""
    from . import quest_library as lib, quest_daily
    daily=quest_daily.load();names={b['id']:b['name'] for b in library['boards']}
    choices=[];seen=set()
    for m in library['missions']:
        for value in (m['name'],m.get('menu_option') or '',m.get('rank') or ''):
            if value:seen.add((m['board_id'],plain(value)))
        choices.append(dict(key=m['id'],mission=m))
    monsters=None
    for board_id,menus in library['menus'].items():
        for menu in menus:
            for option in menu:
                if not mission_option(option) or not rank(option) or (board_id,plain(option)) in seen:continue
                seen.add((board_id,plain(option)))
                if monsters is None:
                    from .monster_db import all_monsters
                    monsters=all_monsters()
                m=lib.enrich_mission(dict(name=clean(option)),lib.option_descriptions(library,board_id,option),monsters=monsters)
                m.update(board_id=board_id,menu_option=option)
                choices.append(dict(key='new:'+board_id+':'+option,mission=m))
    from .quest_library import BOARD_ORDER
    board=lambda b:BOARD_ORDER.index(b) if b in BOARD_ORDER else len(BOARD_ORDER)
    choices.sort(key=lambda c:(board(c['mission']['board_id']),rank_order(c['mission'].get('rank') or c['mission']['name'])))
    for choice in choices:
        m=choice['mission']
        label=names.get(m['board_id'],m['board_id'])+' / '+mission_label(m)
        if not m.get('monster_targets'):label=label.replace('monstros: nao informados','monstros: lidos do quadro ao pegar')
        if quest_daily.done_today(m['board_id'],m.get('rank') or m['name'],daily):label+=' • ✓ concluida hoje'
        choice['label']=label
    return choices


class RouteEditor(QDialog):
    def __init__(self,route,state,parent=None):
        super().__init__(parent);self.route=copy.deepcopy(route);self.state=state or {}
        self.setWindowTitle('Configurar rota de quest')
        root=QVBoxLayout(self);page=QWidget();layout=QVBoxLayout(page);root.addWidget(scroll_page(page))
        form=QFormLayout();self.name=QLineEdit(route.get('name',''))
        self.map_route=QComboBox();self.map_route.addItem('Escolha o mapa de caca (cadastre em Mapas de caca)',None)
        self.map_entries={e['id']:e for e in map_routes.load()}
        for entry in self.map_entries.values():self.map_route.addItem(f"{entry['target_map']} • {entry['name']}",entry['id'])
        if route.get('steps') and not self.map_entries.get(route.get('map_route_id') or ''):
            self.map_route.addItem(f"Percurso gravado nesta rota ({route.get('target_map') or 'sem destino'})",'')
        index=self.map_route.findData(route.get('map_route_id') or ('' if route.get('steps') else None))
        self.map_route.setCurrentIndex(max(index,0))
        form.addRow('Nome da quest',self.name);form.addRow('Mapa de caca',self.map_route);layout.addLayout(form)
        hint=QLabel('Marque as missoes que serao pegas; o bot faz primeiro as de Kakashi e depois as da Sala Vip. Os monstros e as quantidades vem de cada missao; '
                    'missoes ainda sem descricao tem os monstros lidos do quadro na hora de pegar. A caca continua em todos os '
                    'monstros ate todos os contadores fecharem; so entao volta para entregar.')
        hint.setWordWrap(True);layout.addWidget(hint)
        from . import quest_library as lib
        self.library=lib.load();self.choices={c['key']:c for c in mission_choices(self.library)}
        self.mission_list=QListWidget();self.mission_list.setMinimumHeight(220);layout.addWidget(self.mission_list,1)
        chosen=list(route.get('mission_ids',[]))
        self.linked=linked_missions(route)
        self.only_free=QCheckBox('Mostrar so as missoes ainda sem quest (as ja vinculadas a outra quest ficam em amarelo)')
        layout.insertWidget(layout.indexOf(self.mission_list),self.only_free)
        from PySide6.QtGui import QBrush,QColor
        for key in [k for k in chosen if k not in self.choices]+list(self.choices):
            choice=self.choices.get(key)
            label=choice['label'] if choice else 'Cadastro ausente: '+key
            if self.linked.get(key):label+='   • ja na quest: '+', '.join(self.linked[key])
            item=QListWidgetItem(label);item.setData(Qt.UserRole,key)
            if self.linked.get(key):item.setForeground(QBrush(QColor(240,200,90)))
            item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(Qt.Checked if key in chosen else Qt.Unchecked)
            self.mission_list.addItem(item)
        self.only_free.toggled.connect(self.filter_linked)
        self.counter=QLabel();self.counter.setWordWrap(True);layout.addWidget(self.counter)
        from .responsive_ui import WrappingCheckBox
        self.ignore_finished=WrappingCheckBox('Ignorar os monstros que ja completaram a quantidade e os que nao sao da quest '
                                              '(so ataca o que ainda falta, mais os marcados abaixo)')
        self.ignore_finished.setChecked(route.get('ignore_finished',False));layout.addWidget(self.ignore_finished)
        self.chain_next=WrappingCheckBox('Encadear com a proxima rota da fila: pega as missoes de todas juntas, caca um mapa de '
                                         'cada vez (ate fechar os monstros daquele mapa) e no fim entrega todas juntas')
        self.chain_next.setChecked(route.get('chain_next',False));layout.addWidget(self.chain_next)
        always=QLabel('Nao ignorar (atacar sempre), mesmo concluido ou fora da quest: marque o monstro que da problema no mapa. '
                      'Prioridade: 1 e finalizado primeiro, depois 2, 3...; vazio = sem prioridade (monstros fortes primeiro).')
        always.setWordWrap(True);layout.addWidget(always)
        self.always=QTableWidget(0,2);self.always.setHorizontalHeaderLabels(['Monstro (atacar sempre)','Prioridade'])
        self.always.verticalHeader().setVisible(False);self.always.horizontalHeader().setStretchLastSection(False)
        self.always.horizontalHeader().setSectionResizeMode(0,self.always.horizontalHeader().ResizeMode.Stretch)
        self.always.setMaximumHeight(160);layout.addWidget(self.always)
        self.always_chosen=set(route.get('always_attack',[]))
        self.always_priority={int(k):v for k,v in (route.get('attack_priority') or {}).items()}
        self.map_route.currentIndexChanged.connect(self.fill_monsters);self.fill_monsters()
        self.error=QLabel();self.error.setWordWrap(True);self.error.setStyleSheet('color:#ffb59e');root.addWidget(self.error)
        self.mission_list.itemChanged.connect(self.update_counter);self.update_counter()
        self.mission_list.itemChanged.connect(self.fill_monsters)
        self.mission_list.itemChanged.connect(self.suggest_maps);self.suggest_maps()
        accept=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);accept.accepted.connect(self.accept);accept.rejected.connect(self.reject);root.addWidget(accept)
        accept.button(QDialogButtonBox.Save).setText('Salvar rota');accept.button(QDialogButtonBox.Cancel).setText('Cancelar')
        screen=self.screen().availableGeometry();self.resize(min(900,screen.width()-40),min(640,screen.height()-60))

    def filter_linked(self,only_free):
        """Hide the missions another quest already takes (the ones marked here stay visible)."""
        for i in range(self.mission_list.count()):
            item=self.mission_list.item(i)
            item.setHidden(bool(only_free and self.linked.get(item.data(Qt.UserRole)) and item.checkState()!=Qt.Checked))

    def hunting_map(self):
        chosen=self.map_route.currentData()
        if chosen:return self.map_entries[chosen]['target_map']
        return self.route.get('target_map','') if chosen=='' else ''

    def fill_monsters(self,*args):
        """Monsters of the hunting map (and of the marked missions), to be attacked always."""
        from .monster_db import monsters_of_map,name_of
        if self.always.rowCount():
            self.always_chosen=set(self.always_attack());self.always_priority=self.attack_priority(all_rows=True)
        ids=set(self.always_chosen)
        try:on_map=set(monsters_of_map(self.hunting_map()))
        except (OSError,ValueError,KeyError):on_map=set()
        ids|=on_map
        self.highlight_missions(on_map)
        for key in self.selected_missions():
            ids|=set((self.choices.get(key) or {}).get('mission',{}).get('monster_ids',[]))
        self.always.setRowCount(0)
        for row,identity in enumerate(sorted(ids,key=lambda i:(self.always_priority.get(i,1000),name_of(i) or str(i)))):
            self.always.insertRow(row)
            item=QTableWidgetItem(f'{name_of(identity) or "Monstro"} (ID {identity})');item.setData(Qt.UserRole,identity)
            item.setFlags((item.flags()|Qt.ItemIsUserCheckable)&~Qt.ItemIsEditable)
            item.setCheckState(Qt.Checked if identity in self.always_chosen else Qt.Unchecked);self.always.setItem(row,0,item)
            order=QSpinBox();order.setRange(0,99);order.setSpecialValueText('-');order.setValue(self.always_priority.get(identity,0))
            order.setToolTip('1 = finalizado primeiro; - = sem prioridade');self.always.setCellWidget(row,1,order)

    def suggest_maps(self,*args):
        """Hunting maps where the marked missions' monsters live get a green background; with a
        single one and no map chosen yet, it is chosen."""
        from PySide6.QtGui import QBrush,QColor
        from .monster_db import monsters_of_map
        marked=[(self.choices.get(key) or {}).get('mission',{}) for key in self.selected_missions()]
        matches=[]
        for index in range(self.map_route.count()):
            identity=self.map_route.itemData(index)
            entry=self.map_entries.get(identity) if identity else None
            try:here=bool(entry and marked and any(self.mission_on_map(m,entry['target_map'],set(monsters_of_map(entry['target_map'])))
                                                   for m in marked))
            except (OSError,ValueError,KeyError):here=False
            self.map_route.setItemData(index,QBrush(QColor(28,92,72)) if here else QBrush(),Qt.BackgroundRole)
            if here:matches.append(index)
        if len(matches)==1 and self.map_route.currentData() is None:self.map_route.setCurrentIndex(matches[0])

    @staticmethod
    def mission_on_map(m,map_name,species_on_map):
        """The mission's monsters live on that map: by name where the name was seen somewhere (one sprite
        serves several NRO monsters), by sprite id only for names never seen."""
        from .monster_db import maps_for_name,map_key
        names=m.get('monster_names') or [t['name'] for t in m.get('monster_targets',[])]
        unseen=False
        for name in names:
            from .monster_origin import excluded_spawn
            if excluded_spawn(None, map_name, name):
                continue
            where=maps_for_name(name)
            if where:
                if map_key(map_name) in where:return True
            else:unseen=True
        return bool((unseen or not names) and set(m.get('monster_ids',[]))&species_on_map)

    def highlight_missions(self,on_map):
        """Missions whose monsters live on the chosen hunting map get a coloured background."""
        from PySide6.QtGui import QBrush,QColor
        self.mission_list.blockSignals(True)
        hunting=self.hunting_map()
        for i in range(self.mission_list.count()):
            item=self.mission_list.item(i);m=(self.choices.get(item.data(Qt.UserRole)) or {}).get('mission',{})
            here=bool(hunting and self.mission_on_map(m,hunting,on_map))
            item.setBackground(QBrush(QColor(28,92,72)) if here else QBrush())
            item.setToolTip('Monstros desta missao estao no mapa de caca escolhido' if here else '')
        self.mission_list.blockSignals(False)

    def always_attack(self):
        return sorted(self.always.item(i,0).data(Qt.UserRole) for i in range(self.always.rowCount())
                      if self.always.item(i,0).checkState()==Qt.Checked)

    def attack_priority(self,all_rows=False):
        """{species: order} of the marked monsters with a number (all rows while refilling the list)."""
        result={}
        for i in range(self.always.rowCount()):
            item,order=self.always.item(i,0),self.always.cellWidget(i,1)
            if order.value() and (all_rows or item.checkState()==Qt.Checked):result[item.data(Qt.UserRole)]=order.value()
        return result

    def selected_missions(self):
        return [self.mission_list.item(i).data(Qt.UserRole) for i in range(self.mission_list.count()) if self.mission_list.item(i).checkState()==Qt.Checked]

    def update_counter(self,*args):
        missions=[self.choices[k]['mission'] for k in self.selected_missions() if k in self.choices]
        if not missions:self.counter.setText('Contador: marque as missoes desta rota.');return
        known=[m for m in missions if m.get('monster_targets')]
        text=', '.join(f"{t['name']} {t['count']}" for t in self.preview(known)) or 'nenhum ainda'
        later=len(missions)-len(known)
        shared=[self.choices[k]['mission']['name']+' ('+', '.join(self.linked[k])+')' for k in self.selected_missions()
                if k in self.choices and self.linked.get(k)]
        self.counter.setText('Contador: '+text+(f' (+ {later} missao(oes) com monstros lidos do quadro ao pegar)' if later else '')+
                             (' • Atencao, ja vinculadas a outra quest: '+'; '.join(shared) if shared else ''))

    @staticmethod
    def preview(missions):
        result={}
        for m in missions:
            for t in m.get('monster_targets',[]):
                entry=result.setdefault(plain(t['name']),dict(name=t['name'],count=0));entry['count']=max(entry['count'],t['count'])
        return list(result.values())

    def accept(self):
        from . import quest_library as lib
        import uuid
        try:
            keys=self.selected_missions()
            if not self.name.text().strip():raise ValueError('Informe o nome da quest')
            if not keys:raise ValueError('Marque ao menos uma missao')
            chosen=self.map_route.currentData()
            if chosen is None:raise ValueError('Escolha o mapa de caca; grave a rota ate ele na aba Mapas de caca')
            ids=[];created=False
            for key in keys:
                if not key.startswith('new:'):ids.append(key);continue
                m=dict(self.choices[key]['mission'],id=uuid.uuid4().hex);self.library['missions'].append(m);ids.append(m['id']);created=True
            if created:self.library=lib.save(self.library)
            species={i for m in self.library['missions'] if m['id'] in ids for i in m.get('monster_ids',[])}
            self.route.update(ignore_finished=self.ignore_finished.isChecked(),always_attack=self.always_attack(),
                              attack_priority={str(k):v for k,v in self.attack_priority().items()},
                              chain_next=self.chain_next.isChecked())
            self.route.update(name=self.name.text().strip(),mission_ids=ids,lifecycle_enabled=True,kill_targets=[],
                              species=sorted(species|set(self.route.get('species',[])) if chosen=='' else sorted(species)))
            if chosen:
                entry=self.map_entries[chosen]
                self.route.update(map_route_id=chosen,steps=copy.deepcopy(entry['steps']),target_map=entry['target_map'],needs_recording=False)
            self.route=validate_routes([self.route])[0]
        except (ValueError,KeyError) as exc:self.error.setText(str(exc));return
        super().accept()


class MapRoutesPanel(QWidget):
    """Aba Mapas de caca: paths recorded in the game, reused by every quest route."""
    command_requested=Signal(str,dict)

    def __init__(self):
        super().__init__();self.entries=[];self.stamp=None;self.was_recording=False;self.recorded_maps=[]
        layout=QVBoxLayout(self)
        intro=QLabel('Grave uma vez o caminho ate cada mapa de caca: posicione o personagem onde o bot vai partir (onde o Retorno te deixa), '
                     'clique em Gravar nova rota, caminhe, entre nos portais e fale com os NPCs de transporte. No mapa de caca, '
                     'espere parar e clique em Salvar gravacao. Rotas gravadas tambem servem de ligacao (ex.: a volta de um mapa ate a cidade).')
        intro.setWordWrap(True);layout.addWidget(intro)
        self.list=QListWidget();self.list.setMinimumHeight(160);layout.addWidget(self.list,1)
        actions=FlowLayout();layout.addLayout(actions);self.idle_buttons=[]
        for title,callback in (('Gravar nova rota',lambda:self.request('quest_map_record')),('Regravar selecionada',self.rerecord),
                               ('Executar rota selecionada',self.test),('Renomear',self.rename),('Ver etapas',self.preview),('Excluir',self.delete)):
            b=QPushButton(title);b.clicked.connect(callback);actions.addWidget(b);self.idle_buttons.append(b)
        finish=FlowLayout();layout.addLayout(finish)
        self.save_button=QPushButton('Salvar gravacao');self.save_button.clicked.connect(self.finish);finish.addWidget(self.save_button)
        self.cancel_button=QPushButton('Descartar gravacao');self.cancel_button.clicked.connect(lambda:self.request('quest_record_cancel'));finish.addWidget(self.cancel_button)
        self.stop_button=QPushButton('Parar teste');self.stop_button.clicked.connect(lambda:self.request('quest_stop'));finish.addWidget(self.stop_button)
        self.notice=QLabel();self.notice.setWordWrap(True);layout.addWidget(self.notice)
        self.reload();self.update_state({})

    def request(self,command,**values):self.command_requested.emit(command,values)

    def reload(self):
        try:self.entries=map_routes.load();self.stamp=map_routes.FILE.stat().st_mtime_ns if map_routes.FILE.exists() else None
        except (OSError,ValueError) as exc:self.notice.setText(str(exc));return
        current=self.selected();self.list.clear()
        for entry in self.entries:
            item=QListWidgetItem(f"{entry['name']} • {entry['start_map']} → {entry['target_map']} • {len(entry['steps'])} etapas")
            item.setData(Qt.UserRole,entry['id']);self.list.addItem(item)
            if current and current['id']==entry['id']:self.list.setCurrentItem(item)

    def selected(self):
        item=self.list.currentItem()
        return next((e for e in self.entries if item and e['id']==item.data(Qt.UserRole)),None)

    def rerecord(self):
        entry=self.selected()
        if entry:self.request('quest_map_record',replace_id=entry['id'])
        else:self.notice.setText('Selecione a rota que sera regravada')

    def test(self):
        entry=self.selected()
        if entry:self.request('quest_map_test',id=entry['id'])
        else:self.notice.setText('Selecione uma rota para executar')

    def finish(self):
        """One name per map passed (each becomes a route), with the monsters seen there as a hint."""
        maps=self.recorded_maps[1:]
        if not maps:
            name,ok=QInputDialog.getText(self,'Salvar rota de mapa','Nome (vazio = origem → destino):')
            if ok:self.request('quest_map_save',name=name.strip())
            return
        start=self.recorded_maps[0];key=map_routes_key
        dialog=QDialog(self);dialog.setWindowTitle('Salvar rota de mapa');dialog.resize(760,420);layout=QVBoxLayout(dialog)
        layout.addWidget(QLabel('Cada mapa do percurso vira uma rota a partir de '+start+'. Dê um nome a cada um '
                                '(vazio mantém o nome atual ou usa origem → destino). Os monstros já vistos em cada mapa ajudam a reconhecê-lo.'))
        table=QTableWidget(len(maps),3);table.setHorizontalHeaderLabels(['Mapa','Nome','Monstros vistos no mapa'])
        table.verticalHeader().setVisible(False);table.horizontalHeader().setStretchLastSection(True)
        edits={}
        for row,map_name in enumerate(maps):
            old=next((e['name'] for e in self.entries if key(e['target_map'])==key(map_name) and key(e['start_map'])==key(start)),'')
            item=QTableWidgetItem(map_name+(' (destino)' if row==len(maps)-1 else ''));item.setFlags(Qt.ItemIsEnabled)
            table.setItem(row,0,item)
            edit=QLineEdit(old);edit.setPlaceholderText(start+' → '+map_name);table.setCellWidget(row,1,edit);edits[map_name]=edit
            monsters=self.monsters_on(map_name)
            item=QTableWidgetItem(monsters or 'nenhum monstro visto ainda neste mapa');item.setToolTip(monsters);item.setFlags(Qt.ItemIsEnabled)
            table.setItem(row,2,item)
        table.setColumnWidth(0,170);table.setColumnWidth(1,220);layout.addWidget(table,1)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec()!=QDialog.Accepted:return
        names={m:e.text().strip() for m,e in edits.items()}
        self.request('quest_map_save',name=names[maps[-1]],names=names)

    @staticmethod
    def monsters_on(map_name):
        from .monster_db import names_for_map
        try:seen=names_for_map(map_name)
        except (OSError,ValueError):return ''
        return ', '.join(sorted({n for names in seen.values() for n in names},key=str.casefold))

    def rename(self):
        entry=self.selected()
        if not entry:return
        name,ok=QInputDialog.getText(self,'Renomear rota','Nome:',text=entry['name'])
        if ok and name.strip():
            entry['name']=name.strip()
            try:map_routes.save(self.entries)
            except (OSError,ValueError) as exc:self.notice.setText(str(exc))
            self.reload()

    def delete(self):
        entry=self.selected()
        if not entry:return
        try:users=[r['name'] for r in load() if r.get('map_route_id')==entry['id']]
        except (OSError,ValueError):users=[]
        if users:self.notice.setText('Usada pelas rotas: '+', '.join(users)+'. Escolha outro mapa nelas antes de excluir.');return
        if QMessageBox.question(self,'Excluir rota de mapa','Excluir '+entry['name']+'?')==QMessageBox.Yes:
            self.entries.remove(entry)
            try:map_routes.save(self.entries)
            except (OSError,ValueError) as exc:self.notice.setText(str(exc))
            self.reload()

    def preview(self):
        entry=self.selected()
        if not entry:return
        dialog=QDialog(self);dialog.setWindowTitle(entry['name']);layout=QVBoxLayout(dialog)
        table=QTableWidget(0,3);table.setHorizontalHeaderLabels(['Mapa','Acao','Detalhes']);table.setEditTriggers(QTableWidget.NoEditTriggers)
        for step in entry['steps']:
            row=table.rowCount();table.insertRow(row)
            for col,value in enumerate((step['map'],TYPES.get(step['kind'],step['kind']),step.get('option') or step.get('name') or str(step.get('position','')))):
                table.setItem(row,col,QTableWidgetItem(clean(value)))
        table.resizeColumnsToContents();layout.addWidget(table)
        close=QDialogButtonBox(QDialogButtonBox.Close);close.rejected.connect(dialog.reject);layout.addWidget(close)
        dialog.resize(700,500);dialog.exec()

    def update_state(self,state):
        q=state.get('quests',{});recording=q.get('recording_scope')=='map';self.recorded_maps=q.get('recorded_maps') or [];busy=bool(q.get('recording')) or q.get('phase') in ('pickup','travel','hunt','delivery','return')
        stamp=map_routes.FILE.stat().st_mtime_ns if map_routes.FILE.exists() else None
        if stamp!=self.stamp:self.reload()
        for b in self.idle_buttons:b.setEnabled(not busy)
        self.save_button.setEnabled(recording);self.cancel_button.setEnabled(recording)
        self.stop_button.setEnabled(bool(q.get('validation')) and q.get('phase') in ('travel',))
        if recording:self.notice.setText(f"Gravando • {q.get('recorded_steps',0)} etapas • {q.get('reason','')}")
        elif self.was_recording or q.get('validation'):self.notice.setText(q.get('reason',''))
        self.was_recording=recording


class ItemsTable(QTableWidget):
    """Items of one kind with a "Usar" check column; single=True keeps one checked."""
    COLUMNS=['Usar','ID','Nome','Equipado em','Onde equipa','Funcao']

    def __init__(self,rows,chosen,names,descriptions,*,single):
        super().__init__(len(rows),len(self.COLUMNS));self.single=single
        from PySide6.QtWidgets import QHeaderView,QAbstractItemView
        from . import item_names
        self.setHorizontalHeaderLabels(self.COLUMNS);self.verticalHeader().setVisible(False);self.setWordWrap(False)
        self.verticalHeader().setSectionResizeMode(QHeaderView.Fixed);self.verticalHeader().setDefaultSectionSize(26)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive);self.horizontalHeader().setStretchLastSection(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel);self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        for r,item in enumerate(rows):
            description=descriptions.get(item['item_id'],'')
            where=0x8000 if item.get('type')==10 else item.get('equip_location',0)
            values=['',str(item['item_id']),names.get(item['item_id'],'(nome nao encontrado)'),
                    item_names.slots(item['worn']) if item.get('worn') else '—',item_names.slots(where),item_names.summary(description)]
            for c,value in enumerate(values):
                cell=QTableWidgetItem(value);cell.setData(Qt.UserRole,item['item_id'])
                if c==0:
                    cell.setFlags(Qt.ItemIsEnabled|Qt.ItemIsUserCheckable)
                    cell.setCheckState(Qt.Checked if item['item_id'] in chosen else Qt.Unchecked)
                else:cell.setFlags(Qt.ItemIsEnabled|Qt.ItemIsSelectable)
                if c==2 and description:cell.setToolTip(description)
                self.setItem(r,c,cell)
        self.resizeColumnsToContents();self.setColumnWidth(5,min(self.columnWidth(5),420))
        self.itemChanged.connect(self.only_one)

    def only_one(self,cell):
        if not self.single or cell.column()!=0 or cell.checkState()!=Qt.Checked:return
        self.blockSignals(True)
        for r in range(self.rowCount()):
            if self.item(r,0) is not cell:self.item(r,0).setCheckState(Qt.Unchecked)
        self.blockSignals(False)

    def chosen(self):
        return [self.item(r,0).data(Qt.UserRole) for r in range(self.rowCount()) if self.item(r,0).checkState()==Qt.Checked]


class SwitchDialog(QDialog):
    """Switch: which mount to ride on the trips and which equipment/ammo to wear in combat."""

    def __init__(self,name,inventory,chosen,names,descriptions,parent=None):
        super().__init__(parent);self.setWindowTitle('Switch de '+name)
        from . import item_names
        layout=QVBoxLayout(self);tabs=QTabWidget();layout.addWidget(tabs)
        mounts=item_names.mount_choices(inventory,descriptions,names);combat=item_names.combat_choices(inventory,descriptions,names)
        saved_mount=chosen.get('mount_item')
        self.mounts=ItemsTable(mounts,[saved_mount],names,descriptions,single=True)
        self.combat=ItemsTable(combat,chosen.get('combat_items') or [i['item_id'] for i in combat if i.get('worn')],
                               names,descriptions,single=False)
        for title,table,text in (('Montaria',self.mounts,'Todas as montarias do inventario. Escolha a usada nos deslocamentos (equipada fora de combate).'),
                                 ('Equipamentos',self.combat,'Equipamentos de baixo, mao direita e mao esquerda (o que a montaria tira) e municao '
                                  '(kunai/shuriken; marque so uma). Sao equipados ao comecar a caca.')):
            page=QWidget();box=QVBoxLayout(page);hint=QLabel(text);hint.setWordWrap(True);box.addWidget(hint)
            if not table.rowCount():box.addWidget(QLabel('Nenhum item deste tipo no inventario.'))
            box.addWidget(table,1);tabs.addTab(page,title)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        screen=self.screen().availableGeometry();self.resize(min(1000,screen.width()-40),min(560,screen.height()-60))

    def selection(self):
        mount=self.mounts.chosen()
        return dict(mount_item=mount[0] if mount else None,combat_items=self.combat.chosen())


class ExtrasBox(QGroupBox):
    """@voltar after the hunt and the mount for the trips; both learned from the player once."""
    command_requested=Signal(str,dict)

    def __init__(self):
        super().__init__('Ao terminar a caca e na locomocao')
        from .responsive_ui import WrappingCheckBox
        from . import quest_extras
        try:self.config=quest_extras.load()
        except OSError:self.config=quest_extras.load_defaults()
        layout=QVBoxLayout(self)
        self.voltar=WrappingCheckBox('Ao concluir as quests da rota: parar, matar os monstros ao redor e usar @voltar '
                                     '(fora de combate; se a conjuracao for cancelada por dano, mata os monstros e tenta de novo)')
        self.mount=WrappingCheckBox('Usar a montaria para se locomover entre os destinos (equipa fora de combate; ao comecar a '
                                    'caca, recoloca os equipamentos que ela tirou)')
        learn=FlowLayout()
        self.learn_voltar=QPushButton('Aprender @voltar');self.learn_voltar.clicked.connect(lambda:self.request('quest_extras_learn',what='voltar'))
        self.learn_mount=QPushButton('Aprender montaria');self.learn_mount.clicked.connect(lambda:self.request('quest_extras_learn',what='mount'))
        self.cancel=QPushButton('Cancelar aprendizado');self.cancel.clicked.connect(lambda:self.request('quest_extras_learn_cancel'))
        self.switch=QPushButton('Switch');self.switch.setToolTip('Escolher a montaria e os equipamentos de combate deste personagem')
        self.switch.clicked.connect(self.choose_items)
        for b in (self.switch,self.learn_voltar,self.cancel):learn.addWidget(b)
        self.learn_mount.hide()  # the mount is picked from the inventory now
        self.state={};self.item_tables=None
        import threading
        def load():
            from . import item_names
            try:self.item_tables=item_names.tables()
            except Exception as exc:self.item_tables=({},{});print('Nomes de itens indisponiveis: '+str(exc))
        threading.Thread(target=load,daemon=True).start()
        form=QFormLayout()
        self.calm=QSpinBox();self.calm.setRange(1,60);self.calm.setSuffix(' s')
        self.radius=QSpinBox();self.radius.setRange(2,20);self.radius.setSuffix(' celulas')
        self.timeout=QSpinBox();self.timeout.setRange(3,60);self.timeout.setSuffix(' s')
        form.addRow('Tempo sem combate antes de usar',self.calm);form.addRow('Monstros ao redor (raio)',self.radius)
        form.addRow('Espera maxima do teletransporte',self.timeout)
        self.status=QLabel();self.status.setWordWrap(True)
        for widget in (self.voltar,self.mount):layout.addWidget(widget)
        layout.addLayout(learn);layout.addLayout(form);layout.addWidget(self.status)
        self.show_config()
        for widget in (self.voltar,self.mount):widget.toggled.connect(self.store)
        for widget in (self.calm,self.radius,self.timeout):widget.valueChanged.connect(self.store)

    def request(self,command,**values):self.command_requested.emit(command,values)

    def show_config(self):
        c=self.config
        for widget,value in ((self.voltar,c['voltar_enabled']),(self.mount,c['mount_enabled'])):
            widget.blockSignals(True);widget.setChecked(bool(value));widget.blockSignals(False)
        for widget,value in ((self.calm,c['calm_seconds']),(self.radius,c['clear_radius']),(self.timeout,c['cast_timeout'])):
            widget.blockSignals(True);widget.setValue(int(value));widget.blockSignals(False)
        mount=c.get('mount')
        name=((self.state.get('own_look') or {}).get('name') if hasattr(self,'state') else None) or ''
        chosen=(c.get('characters') or {}).get(name)
        if chosen and (chosen.get('mount_item') or chosen.get('combat_items')):
            mount=dict(item_id=chosen.get('mount_item'),displaced=chosen.get('combat_items',[]))
        self.learned=('@voltar: '+('aprendido'+(' ('+c['voltar_name']+')' if c.get('voltar_name') else '') if c.get('voltar_frame') else 'nao aprendido')+
                      ' • Montaria: '+(f"item {mount['item_id']}, tira {len(mount.get('displaced',[]))} equipamento(s)" if mount else 'nao aprendida'))
        self.status.setText(self.learned)

    def choose_items(self):
        """Switch: pick the mount and the combat equipment; kept for this character, used by the queue."""
        from . import quest_extras
        name=(self.state.get('own_look') or {}).get('name')
        inventory=(self.state.get('quests') or {}).get('inventory') or []
        if not name or not inventory:
            self.status.setText('Entre no personagem pelo bot e aguarde o inventario chegar (trocar de mapa ou relogar envia a lista).');return
        if self.item_tables is None:
            self.status.setText('Carregando os nomes dos itens do jogo; tente de novo em alguns segundos.');return
        names,descriptions=self.item_tables
        try:self.config=quest_extras.load()
        except OSError as exc:QMessageBox.warning(self,'Switch',str(exc));return
        mine=self.config.setdefault('characters',{}).setdefault(name,{})
        dialog=SwitchDialog(name,inventory,mine,names,descriptions,self)
        if not dialog.exec():return
        selection=dialog.selection()
        try:
            self.config=quest_extras.load()  # fresh: the relay may have saved @voltar meanwhile
            mine=self.config.setdefault('characters',{}).setdefault(name,{});mine.update(selection)
            if mine.get('mount_item'):self.config['mount_enabled']=True
            quest_extras.save(self.config)
            saved=quest_extras.load().get('characters',{}).get(name,{})
            if saved.get('mount_item')!=selection['mount_item'] or saved.get('combat_items')!=selection['combat_items']:
                raise OSError('O Switch nao ficou gravado em '+str(quest_extras.FILE)+'; tente de novo.')
        except OSError as exc:
            # A message box: the status line is rewritten on every refresh and would hide the error.
            QMessageBox.warning(self,'Switch nao salvo',str(exc));return
        self.extras_stamp=None;self.show_config()
        mount=selection['mount_item']
        QMessageBox.information(self,'Switch salvo',f"Switch de {name} salvo: montaria "+(str(mount) if mount else 'nenhuma')+
                                f", {len(selection['combat_items'])} item(ns) de combate.")

    def store(self,*args):
        from . import quest_extras
        try:
            self.config=quest_extras.load()
            self.config.update(voltar_enabled=self.voltar.isChecked(),mount_enabled=self.mount.isChecked(),
                               calm_seconds=self.calm.value(),clear_radius=self.radius.value(),cast_timeout=self.timeout.value())
            quest_extras.save(self.config)
        except OSError as exc:QMessageBox.warning(self,'Opcoes nao salvas',str(exc));return
        self.show_config()

    def update_state(self,state):
        from . import quest_extras
        self.state=state or {}
        q=state.get('quests',{});learning=q.get('learning')
        if not learning:
            # Read again only when the file changed: reading it on every refresh competed with the
            # relay's writes (Windows refuses to replace a file another process is reading).
            try:stamp=quest_extras.FILE.stat().st_mtime_ns
            except OSError:stamp=None
            if stamp!=getattr(self,'extras_stamp',None):
                try:fresh=quest_extras.load()
                except OSError:fresh=None
                if fresh is not None:
                    self.extras_stamp=stamp
                    if fresh!=self.config:self.config=fresh;self.show_config()
        busy=bool(learning) or q.get('phase') in ('pickup','travel','hunt','delivery','return')
        for b in (self.learn_voltar,self.learn_mount,self.switch):b.setEnabled(not busy)
        self.cancel.setEnabled(bool(learning))
        if learning:self.status.setText('Aprendendo: '+q.get('reason',''))
        elif q.get('errand'):self.status.setText(self.learned+' • Agora: '+q.get('reason',''))
        else:self.status.setText(self.learned)


def route_done_today(route,missions,daily):
    """(missions of the route done today, missions in the route), from the board's daily marks."""
    from . import quest_daily
    by_id={m['id']:m for m in missions}
    chosen=[by_id[i] for i in route.get('mission_ids',[]) if i in by_id]
    done=sum(quest_daily.done_today(m['board_id'],m.get('rank') or m['name'],daily) for m in chosen)
    return done,len(chosen)


class QuestPanel(QWidget):
    command_requested=Signal(str,dict)

    def __init__(self):
        super().__init__();self.routes=[];self.state={}
        outer=QVBoxLayout(self);self.sections=QTabWidget();outer.addWidget(self.sections)
        queue=QWidget();self.sections.addTab(scroll_page(queue),'Fila de rotas');layout=QVBoxLayout(queue)
        intro=QLabel('Ciclo de cada rota: 1. Pegar as missoes marcadas → 2. Ir ao mapa de caca → 3. Matar ate todos os contadores '
                     'fecharem → 4. Entregar as missoes. A proxima rota so comeca depois das entregas confirmadas pelo quadro.')
        intro.setWordWrap(True);layout.addWidget(intro)
        self.status=QLabel('Fila parada');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.list=QuestQueueList();self.list.setMinimumHeight(170);layout.addWidget(self.list,1);self.list.itemChanged.connect(self.checked)
        self.list.order_changed.connect(self.dropped)
        self.list.setToolTip('Arraste para ordenar. Ctrl seleciona varias rotas; Shift seleciona um intervalo. A ordem e salva automaticamente.')
        self.edit_buttons=[]
        actions=FlowLayout();layout.addLayout(actions)
        for name,callback in [('Nova quest',self.new),('Editar rota',self.edit),('Excluir',self.delete),('Subir',lambda:self.reorder(-1)),('Descer',lambda:self.reorder(1)),('Recarregar',self.reload),('Executar somente viagem',self.test_travel),
                              ('Executar so coleta da rota',lambda:self.test_stage('pickup')),('Executar so entrega da rota',lambda:self.test_stage('delivery'))]:
            b=QPushButton(name);b.clicked.connect(callback);actions.addWidget(b);self.edit_buttons.append(b)
        execution=FlowLayout();layout.addLayout(execution)
        self.start=QPushButton('Executar fila marcada');self.start.setObjectName('StartAction');self.start.clicked.connect(lambda:self.request('quest_start'));execution.addWidget(self.start)
        self.resume=QPushButton('Retomar fila');self.resume.setToolTip('Continua de onde parou: mesma rota, etapa, missoes ja feitas e contador')
        self.resume.clicked.connect(lambda:self.request('quest_resume'));execution.addWidget(self.resume)
        stop=QPushButton('Pausar fila');stop.clicked.connect(lambda:self.request('quest_stop'));execution.addWidget(stop)
        self.progress=QLabel();self.progress.setWordWrap(True);layout.addWidget(self.progress)
        self.notice=QLabel('Arraste as rotas para ordenar. Ctrl seleciona varias; Shift seleciona um intervalo. '
                          'A ordem e salva automaticamente. Pause a fila para editar.');self.notice.setWordWrap(True);layout.addWidget(self.notice)
        self.extras=ExtrasBox();self.extras.command_requested.connect(self.command_requested.emit);layout.addWidget(self.extras)
        self.map_panel=MapRoutesPanel();self.map_panel.command_requested.connect(self.command_requested.emit)
        self.sections.addTab(scroll_page(self.map_panel),'Mapas de caca')
        from .quest_library_panel import QuestLibraryPanel
        self.library_panel=QuestLibraryPanel();self.library_panel.command_requested.connect(self.command_requested.emit)
        self.sections.addTab(scroll_page(self.library_panel),'Quadros e missoes compartilhados')
        self.reload();self.update_state({})

    def selected(self):
        item=self.list.currentItem()
        return next((r for r in self.routes if item and r['id']==item.data(Qt.UserRole)),None)

    def reload(self):
        selected=self.selected();identity=selected['id'] if selected else None
        selected_ids={item.data(Qt.UserRole) for item in self.list.selectedItems()}
        try:self.routes=load()
        except (ValueError,OSError) as exc:self.notice.setText(str(exc));return
        try:
            from .quest_library import load as load_library
            library=load_library()['missions'];names={m['id']:m['name'] for m in library}
        except (OSError,ValueError):library,names=[],{}
        from . import quest_daily
        daily=quest_daily.load();running,paused=self.route_marks()
        self.list.blockSignals(True);self.list.clear()
        for i,r in enumerate(self.routes):
            missions=', '.join(names.get(m,'?') for m in r['mission_ids']) or 'nenhuma missao'
            done,total=route_done_today(r,library,daily)
            mark=('▶ em andamento  ' if r['name']==running else '⏸ fila pausada aqui  ' if r['id']==paused else
                  '✔ concluida hoje  ' if total and done==total else f'◐ {done}/{total} hoje  ' if done else '')
            item=QListWidgetItem(f"{mark}{i+1}. {r['name']}  |  {r['target_map'] or 'escolha o mapa de caca'}  |  {missions}"
                                 +('  |  ⛓ encadeada com a proxima' if r.get('chain_next') else ''))
            if total and done==total and r['name']!=running:item.setForeground(QColor('#5fd68a'))
            elif r['name']==running:item.setForeground(QColor('#ffd166'))
            item.setData(Qt.UserRole,r['id'])
            item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(Qt.Checked if r['enabled'] else Qt.Unchecked);self.list.addItem(item)
            item.setSelected(r['id'] in selected_ids)
            if r['id']==identity:self.list.setCurrentRow(i,QItemSelectionModel.NoUpdate)
        self.list.blockSignals(False)

    def route_marks(self):
        """(name of the route the queue is running, id of the route a paused queue would resume)."""
        q=(self.state or {}).get('quests',{})
        running=q.get('quest') if q.get('phase') in ('pickup','travel','hunt','delivery','return') else None
        try:
            from . import quest_progress
            paused=(quest_progress.load() or {}).get('route_id')
        except (OSError,ValueError):paused=None
        return running,paused

    def marks_key(self):
        from . import quest_daily
        try:stamp=quest_daily.FILE.stat().st_mtime_ns
        except OSError:stamp=None
        import datetime
        return stamp,datetime.date.today(),self.route_marks()

    def persist(self):
        try:self.routes=save(self.routes);self.reload();return True
        except (ValueError,OSError) as exc:self.notice.setText(str(exc));return False

    def checked(self,item):
        route=next((r for r in self.routes if r['id']==item.data(Qt.UserRole)),None)
        if route:route['enabled']=item.checkState()==Qt.Checked;self.persist()

    def dropped(self):
        by_id={r['id']:r for r in self.routes}
        ids=[self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]
        if len(ids)!=len(by_id) or set(ids)!=set(by_id):
            self.reload();return
        self.routes=[by_id[identity] for identity in ids]
        if self.persist():self.notice.setText('Ordem da fila salva. Ctrl/Shift permitem arrastar varias rotas juntas.')

    def new(self):
        dialog=RouteEditor(dict(name='',enabled=True,kills=1,species=[],steps=[],target_map='',lifecycle_enabled=True),self.state,self)
        if dialog.exec():self.routes.append(dialog.route);self.persist()

    def edit(self):
        route=self.selected()
        if route is None:return
        dialog=RouteEditor(route,self.state,self)
        if dialog.exec():self.routes[self.list.currentRow()]=dialog.route;self.persist()

    def delete(self):
        if self.selected() and QMessageBox.question(self,'Excluir quest','Excluir esta rota salva?')==QMessageBox.Yes:
            del self.routes[self.list.currentRow()];self.persist()

    def reorder(self,direction):
        selected={item.data(Qt.UserRole) for item in self.list.selectedItems()}
        indices=range(len(self.routes)) if direction<0 else range(len(self.routes)-1,-1,-1)
        for row in indices:
            other=row+direction
            if self.routes[row]['id'] in selected and 0<=other<len(self.routes) and self.routes[other]['id'] not in selected:
                self.routes[row],self.routes[other]=self.routes[other],self.routes[row]
        self.persist()

    def test_travel(self):
        route=self.selected()
        if route:self.request('quest_test_route',route_id=route['id'])
        else:self.notice.setText('Selecione uma rota salva para testar a viagem')

    def test_stage(self,stage):
        route=self.selected()
        if route:self.request('quest_test_stage_route',route_id=route['id'],stage=stage)

    def request(self,command,**values):self.command_requested.emit(command,values)

    def update_state(self,state):
        self.state=state;q=state.get('quests',{});recording=bool(q.get('recording'));active=q.get('phase') in ('pickup','travel','hunt','delivery','return')
        progress=' | '.join(f"{p['name']} {p['done']}/{p['count']}"+(' ✓' if p['complete'] else '') for p in q.get('kill_progress') or [])
        self.status.setText(f"{q.get('reason','Fila parada')} | Quest: {q.get('quest') or '-'} | Etapa: {q.get('step',0)}"+
                            (f" | Contador: {progress}" if q.get('phase')=='hunt' and progress else '')+
                            (f" | Missao: {q['mission']}" if q.get('mission') else ''))
        for button in self.edit_buttons:button.setEnabled(not active and not recording)
        self.list.setEnabled(not active and not recording);self.start.setEnabled(not active and not recording)
        from . import quest_progress
        saved=quest_progress.load()
        self.resume.setEnabled(bool(saved) and not active and not recording)
        self.progress.setText(quest_progress.describe(saved))
        key=self.marks_key()
        if key!=getattr(self,'shown_marks',None):  # a mission done, the queue moved on, a new day
            self.shown_marks=key;self.reload()
        self.map_panel.update_state(state)
        self.library_panel.update_state(state)
        self.extras.update_state(state)
