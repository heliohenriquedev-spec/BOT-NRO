"""Ordered, optional quest itineraries, with a visual step editor and manual recorder."""
import copy
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QPushButton,
    QListWidget,QListWidgetItem,QLineEdit,QSpinBox,QDialog,QDialogButtonBox,QTableWidget,
    QTableWidgetItem,QComboBox,QMessageBox,QHeaderView,QTabWidget,QInputDialog,QAbstractItemView)
from .quest_routes import load, save, validate_routes, STAGES, STAGE_FIELDS
from .responsive_ui import FlowLayout, scroll_page, WrappingCheckBox
from .npc_labels import clean,mission_label
from .portals import PortalGuard

TYPES={'walk':'Caminhar','portal':'Entrar no portal','npc':'Falar com NPC','select':'Escolher opcao',
       'next':'Proximo dialogo','close':'Fechar dialogo','cancel':'Cancelar/fechar menu','wait_map':'Confirmar mapa de chegada','wait_transfer':'Aguardar teletransporte Retorno',
       'select_free_slot':'Escolher slot livre','select_mission_slot':'Localizar missao no slot','verify_slot':'Confirmar missao aceita','verify_slot_absent':'Confirmar entrega no slot'}
BOARDS=(('Quadro de Missoes - Sala Vip',dict(kind='npc',map='ra_in01',position=[219,95],name='Quadro de Missões')),
        ('Quadro de Missoes - Kakashi',dict(kind='npc',map='kakashi',position=[87,140],name='Quadro de Missões')),
        ('Entrada hospital2 para Kakashi',dict(kind='npc',map='hospital2',position=[16,74],name='')))


class RouteEditor(QDialog):
    def __init__(self,route,state,parent=None):
        super().__init__(parent);self.route=copy.deepcopy(route);self.state=state or {}
        self.setWindowTitle('Configurar rota de quest');self.resize(940,680)
        root=QVBoxLayout(self);page=QWidget();layout=QVBoxLayout(page);root.addWidget(scroll_page(page))
        form=QFormLayout();self.name=QLineEdit(route.get('name',''))
        self.map=QLineEdit(route.get('target_map',''));self.map.setPlaceholderText('Ex.: anthell01')
        self.species=QLineEdit(', '.join(map(str,route.get('species',[]))))
        self.species.setPlaceholderText('IDs de aparencia separados por virgula')
        self.kills=QSpinBox();self.kills.setRange(1,100000);self.kills.setValue(route.get('kills',1))
        for title,field in [('Nome da quest',self.name),('Mapa de caca',self.map),('Monstros da quest',self.species),('Mortes para concluir',self.kills)]:form.addRow(title,field)
        self.lifecycle=WrappingCheckBox('Pegar quests antes de viajar e entregar antes de avancar a fila')
        self.lifecycle.setChecked(route.get('lifecycle_enabled',True));form.addRow(self.lifecycle)
        self.confirmations={}
        for stage,title in (('pickup','Confirmacao ao pegar'),('delivery','Confirmacao ao entregar')):
            field=QLineEdit(route.get(stage+'_confirmation',''));field.setPlaceholderText('Trecho da mensagem de sucesso do NPC')
            field.setToolTip('A etapa so termina quando este texto aparece em uma resposta nova do NPC acessado nesta etapa.')
            self.confirmations[stage]=field;form.addRow(title,field)
        layout.addLayout(form);choose=QPushButton('Escolher monstros registrados no mapa de caca');choose.clicked.connect(self.choose_monsters);layout.addWidget(choose)
        from .quest_library import load as load_library
        library=load_library();board_names={b['id']:b['name'] for b in library['boards']}
        self.mission_catalog={m['id']:m for m in library['missions']}
        label=QLabel('Missoes do cadastro compartilhado: marque de um quadro ou dos dois; arraste para ordenar. Coleta e entrega serao buscadas do cadastro, sem copiar dialogos para esta rota.')
        label.setWordWrap(True);layout.addWidget(label)
        self.mission_list=QListWidget();self.mission_list.setMinimumHeight(90)
        self.mission_list.setDragDropMode(QAbstractItemView.InternalMove);layout.addWidget(self.mission_list)
        available={m['id']:m for m in library['missions']};ordered=list(route.get('mission_ids',[]))
        ordered.extend(i for i in available if i not in ordered)
        for identity in ordered:
            m=available.get(identity)
            title=board_names[m['board_id']]+' / '+mission_label(m) if m else 'Cadastro ausente: '+identity
            item=QListWidgetItem(title);item.setData(Qt.UserRole,identity);item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if identity in route.get('mission_ids',[]) else Qt.Unchecked);self.mission_list.addItem(item)
        use_targets=QPushButton('Usar monstros das missoes marcadas nesta rota');use_targets.clicked.connect(self.use_mission_targets);layout.addWidget(use_targets)
        hint=QLabel('Cada etapa informa o mapa em que deve ocorrer. Apos um portal ou teletransporte, adicione Confirmar mapa de chegada. Opcoes de NPC usam o texto completo, nao o numero. Voce tambem pode gravar o percurso no jogo.')
        hint.setWordWrap(True);layout.addWidget(hint)
        if route.get('notes'):
            note=QLabel(route['notes']);note.setWordWrap(True);layout.addWidget(note)
        self.stage_tabs=QTabWidget();self.stage_tables={};layout.addWidget(self.stage_tabs,1)
        for stage,title in (('pickup','1. Pegar quests'),('travel','2. Rota da quest'),('delivery','4. Entregar quests')):
            table=QTableWidget(0,5);self.stage_tables[stage]=table;self.stage_tabs.addTab(table,title)
            table.setHorizontalHeaderLabels(['Mapa','Acao','X','Y','Nome NPC / opcao'])
            table.horizontalHeader().setSectionResizeMode(4,QHeaderView.Stretch)
            for col,width in ((0,130),(1,195),(2,60),(3,60)):table.setColumnWidth(col,width)
            table.setMinimumHeight(240);table.verticalHeader().setDefaultSectionSize(42)
            for step in route.get(STAGE_FIELDS[stage],[]):self.add_step(step,table)
            if table.rowCount():table.setCurrentCell(0,0);table.scrollToTop()
        buttons=FlowLayout();layout.addLayout(buttons)
        for label,callback in [('Adicionar etapa',lambda:self.add_step()),('Remover etapa',self.remove_step),
                               ('Subir etapa',lambda:self.move_step(-1)),('Descer etapa',lambda:self.move_step(1))]:
            b=QPushButton(label);b.clicked.connect(callback);buttons.addWidget(b)
        board_actions=FlowLayout();layout.addLayout(board_actions)
        self.board=QComboBox()
        for title,step in BOARDS:self.board.addItem(title,step)
        board_actions.addWidget(self.board)
        insert_board=QPushButton('Inserir NPC na etapa aberta')
        insert_board.clicked.connect(lambda:self.add_step(copy.deepcopy(self.board.currentData())))
        board_actions.addWidget(insert_board)
        self.error=QLabel();self.error.setWordWrap(True);self.error.setStyleSheet('color:#ffb59e');root.addWidget(self.error)
        self.mission_list.itemChanged.connect(self.update_shared_selection);self.update_shared_selection()
        accept=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);accept.accepted.connect(self.accept);accept.rejected.connect(self.reject);root.addWidget(accept)
        accept.button(QDialogButtonBox.Save).setText('Salvar rota')
        accept.button(QDialogButtonBox.Cancel).setText('Cancelar')
        screen=self.screen().availableGeometry();self.resize(min(940,screen.width()-40),min(680,screen.height()-60))

    @property
    def steps(self):return self.stage_tabs.currentWidget()

    def selected_missions(self):
        return [self.mission_list.item(i).data(Qt.UserRole) for i in range(self.mission_list.count()) if self.mission_list.item(i).checkState()==Qt.Checked]

    def update_shared_selection(self,*args):
        shared=bool(self.selected_missions())
        if shared:self.lifecycle.setChecked(True);self.stage_tabs.setCurrentIndex(1)
        self.lifecycle.setEnabled(not shared)
        for field in self.confirmations.values():field.setEnabled(not shared)
        self.stage_tabs.setTabEnabled(0,not shared);self.stage_tabs.setTabEnabled(2,not shared)

    def use_mission_targets(self):
        selected=[self.mission_catalog[i] for i in self.selected_missions() if i in self.mission_catalog]
        ids=sorted({i for m in selected for i in m.get('monster_ids',[])})
        maps={PortalGuard.key(m['target_map']) for m in selected if m.get('target_map')}
        if not ids:self.error.setText('Configure os monstros das missoes no cadastro compartilhado primeiro.');return
        if len(maps)>1:self.error.setText('Missoes de mapas diferentes: separe-as em rotas de caca.');return
        self.species.setText(', '.join(map(str,ids)))
        if maps:self.map.setText(next(iter(maps)))
        self.error.clear()

    def add_step(self,step=None,table=None):
        step=step or dict(kind='walk',map=self.state.get('map_name') or '',position=self.state.get('player_position') or [0,0])
        table=table if table is not None else self.steps
        row=table.rowCount();table.insertRow(row)
        combo=QComboBox()
        for key,label in TYPES.items():combo.addItem(label,key)
        combo.setCurrentIndex(combo.findData(step['kind']));table.setCellWidget(row,1,combo)
        for col,value in ((0,step['map']),(2,step.get('position',[0,0])[0]),(3,step.get('position',[0,0])[1]),
                          (4,step.get('option',step.get('name','')))):
            table.setItem(row,col,QTableWidgetItem(str(value)))
        table.setCurrentCell(row,0)

    def read_steps(self,stage=None):
        result=[]
        table=self.stage_tables[stage] if stage else self.steps
        for row in range(table.rowCount()):
            value=lambda col:table.item(row,col).text().strip()
            kind=table.cellWidget(row,1).currentData();step=dict(kind=kind,map=value(0))
            if kind in ('walk','portal','npc'):step['position']=[int(value(2)),int(value(3))]
            if kind=='npc':step['name']=value(4)
            if kind=='select':step['option']=value(4)
            result.append(step)
        return result

    def remove_step(self):
        row=self.steps.currentRow()
        if row>=0:self.steps.removeRow(row)

    def move_step(self,direction):
        try:
            steps=self.read_steps();row=self.steps.currentRow();other=row+direction
            if row<0 or not 0<=other<len(steps):return
            steps[row],steps[other]=steps[other],steps[row];self.steps.setRowCount(0)
            for step in steps:self.add_step(step)
            self.steps.setCurrentCell(other,0)
        except ValueError:self.error.setText('Corrija as coordenadas antes de reordenar')

    def choose_monsters(self):
        dialog=QDialog(self);dialog.setWindowTitle('Monstros recebidos');layout=QVBoxLayout(dialog);items=QListWidget();layout.addWidget(items)
        selected={s.strip() for s in self.species.text().split(',')};known={}
        from .monster_db import monsters_of_map,name_of,map_key
        for identity in monsters_of_map(self.map.text()):known[identity]=name_of(identity)
        for value in selected:
            if value.isdigit():known.setdefault(int(value),name_of(int(value)))
        observed=self.state.get('map_monsters',[]) if map_key(self.map.text())==map_key(self.state.get('map_name')) else []
        for monster in observed:
            identity=monster.get('species_id');name=monster.get('name',str(identity))
            if identity:known[identity]=name
        for identity in sorted(known):
            item=QListWidgetItem(f'{known[identity]} (ID {identity})');item.setData(Qt.UserRole,identity)
            item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(Qt.Checked if str(identity) in selected else Qt.Unchecked);items.addItem(item)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec():self.species.setText(', '.join(str(items.item(i).data(Qt.UserRole)) for i in range(items.count()) if items.item(i).checkState()==Qt.Checked))

    def accept(self):
        try:
            self.route.update(name=self.name.text().strip(),target_map=self.map.text().strip(),kills=self.kills.value(),
                              species=[int(s.strip()) for s in self.species.text().split(',') if s.strip()],lifecycle_enabled=self.lifecycle.isChecked())
            self.route['mission_ids']=self.selected_missions()
            for stage,field in STAGE_FIELDS.items():self.route[field]=self.read_steps(stage)
            for stage,field in self.confirmations.items():self.route[stage+'_confirmation']=field.text().strip()
            self.route=validate_routes([self.route])[0]
        except (ValueError,KeyError) as exc:self.error.setText(str(exc));return
        super().accept()


class QuestPanel(QWidget):
    command_requested=Signal(str,dict)
    def __init__(self):
        super().__init__();self.routes=[];self.state={};self.was_recording=False
        outer=QVBoxLayout(self);self.sections=QTabWidget();outer.addWidget(self.sections)
        queue=QWidget();self.sections.addTab(queue,'Fila de rotas');layout=QVBoxLayout(queue)
        intro=QLabel('Ciclo da fila: 1. Pegar quests → 2. Viajar → 3. Matar os monstros → 4. Entregar quests. A proxima rota so comeca depois da entrega confirmada. Grave cada trecho uma vez e configure as mensagens de sucesso dos NPCs.')
        intro.setWordWrap(True);layout.addWidget(intro)
        self.status=QLabel('Fila parada');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.list=QListWidget();self.list.setMinimumHeight(170);layout.addWidget(self.list,1);self.list.itemChanged.connect(self.checked)
        self.edit_buttons=[]
        actions=FlowLayout();layout.addLayout(actions)
        for name,callback in [('Nova quest',self.new),('Editar rota',self.edit),('Excluir',self.delete),('Subir',lambda:self.reorder(-1)),('Descer',lambda:self.reorder(1)),('Recarregar',self.reload),('Executar somente viagem',self.test_travel),
                              ('Executar so coleta da rota',lambda:self.test_stage('pickup')),('Executar so entrega da rota',lambda:self.test_stage('delivery'))]:
            b=QPushButton(name);b.clicked.connect(callback);actions.addWidget(b);self.edit_buttons.append(b)
        record=FlowLayout();layout.addLayout(record)
        self.record_stage=QComboBox()
        for stage,title in STAGES.items():
            if stage in STAGE_FIELDS:self.record_stage.addItem(title,stage)
        record.addWidget(self.record_stage)
        self.record_button=QPushButton('Gravar trecho selecionado');self.record_button.clicked.connect(self.record);record.addWidget(self.record_button)
        self.finish=QPushButton('Salvar trecho gravado');self.finish.clicked.connect(self.finish_recording);record.addWidget(self.finish)
        self.cancel=QPushButton('Descartar gravacao');self.cancel.clicked.connect(lambda:self.request('quest_record_cancel'));record.addWidget(self.cancel)
        execution=FlowLayout();layout.addLayout(execution)
        self.start=QPushButton('Executar fila marcada');self.start.setObjectName('StartAction');self.start.clicked.connect(lambda:self.request('quest_start'));execution.addWidget(self.start)
        stop=QPushButton('Pausar fila');stop.clicked.connect(lambda:self.request('quest_stop'));execution.addWidget(stop)
        self.notice=QLabel('Grave separadamente: pegar quests (incluindo o NPC), viajar ate os monstros e retornar/entregar (incluindo o NPC). A caca fica pausada ao gravar. Home, F12 e Pausar interrompem a fila.')
        self.notice.setWordWrap(True);layout.addWidget(self.notice)
        from .quest_library_panel import QuestLibraryPanel
        self.library_panel=QuestLibraryPanel();self.library_panel.command_requested.connect(self.command_requested.emit)
        self.sections.addTab(scroll_page(self.library_panel),'Quadros e missoes compartilhados')
        self.reload();self.update_state({})

    def selected(self):
        row=self.list.currentRow();return self.routes[row] if 0<=row<len(self.routes) else None

    def reload(self):
        selected=self.selected();identity=selected['id'] if selected else None
        try:self.routes=load()
        except (ValueError,OSError) as exc:self.notice.setText(str(exc));return
        self.list.blockSignals(True);self.list.clear()
        for i,r in enumerate(self.routes):
            item=QListWidgetItem(f"{i+1}. {r['name']}  |  {r['target_map'] or 'destino a gravar'}  |  {r['kills']} mortes  |  "+
                                (f"{len(r['mission_ids'])} missoes compartilhadas" if r['mission_ids'] else f"Coleta {len(r['pickup_steps'])} / Viagem {len(r['steps'])} / Entrega {len(r['delivery_steps'])}" if r['lifecycle_enabled'] else f"Somente rota: {len(r['steps'])} etapas")+
                                (' | Rascunho: gravar percurso' if r.get('needs_recording') else ''))
            item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(Qt.Checked if r['enabled'] else Qt.Unchecked);self.list.addItem(item)
            if r['id']==identity:self.list.setCurrentRow(i)
        self.list.blockSignals(False)

    def persist(self):
        try:self.routes=save(self.routes);self.reload();return True
        except (ValueError,OSError) as exc:self.notice.setText(str(exc));return False

    def checked(self,item):
        self.routes[self.list.row(item)]['enabled']=item.checkState()==Qt.Checked;self.persist()

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
        row=self.list.currentRow();other=row+direction
        if row>=0 and 0<=other<len(self.routes):
            self.routes[row],self.routes[other]=self.routes[other],self.routes[row];self.persist();self.list.setCurrentRow(other)

    def record(self):
        route=self.selected()
        if route and route['mission_ids'] and self.record_stage.currentData()!='travel':
            self.notice.setText('Nesta rota, pegue/entregue pelo cadastro compartilhado. Aqui grave apenas Rota da quest.');return
        if route:self.request('quest_record',route_id=route['id'],stage=self.record_stage.currentData())
        else:self.notice.setText('Crie ou selecione uma quest para gravar')

    def test_travel(self):
        route=self.selected()
        if route:self.request('quest_test_route',route_id=route['id'])
        else:self.notice.setText('Selecione uma rota salva para testar a viagem')

    def test_stage(self,stage):
        route=self.selected()
        if route:self.request('quest_test_stage_route',route_id=route['id'],stage=stage)

    def request(self,command,**values):self.command_requested.emit(command,values)

    def finish_recording(self):
        q=self.state.get('quests',{});stage=q.get('recording_stage','travel');values={}
        if stage in ('pickup','delivery'):
            confirmation,ok=QInputDialog.getText(self,'Confirmacao de '+STAGES[stage],
                'Informe um trecho da mensagem que o NPC mostrou ao concluir com sucesso:',text=q.get('last_npc_text',''))
            if not ok:return
            values['confirmation']=confirmation.strip()
        self.request('quest_record_save',**values)

    def update_state(self,state):
        self.state=state;q=state.get('quests',{});recording=bool(q.get('recording'));active=q.get('phase') in ('pickup','travel','hunt','delivery','return')
        if self.was_recording and not recording:self.reload()
        self.was_recording=recording
        self.status.setText(f"{q.get('reason','Fila parada')} | Quest: {q.get('quest') or '-'} | Etapa: {q.get('step',0)} | Mortes: {q.get('kills',0)}/{q.get('goal',0)}"+
                            (f" | Missao: {q['mission']}" if q.get('mission') else '')+
                            (f" | Gravadas: {q.get('recorded_steps',0)} etapas" if recording else ''))
        for button in self.edit_buttons:button.setEnabled(not active and not recording)
        self.list.setEnabled(not active and not recording);self.start.setEnabled(not active and not recording)
        local_recording=recording and q.get('recording_scope','route')=='route'
        self.record_button.setEnabled(not active and not recording);self.finish.setEnabled(local_recording);self.cancel.setEnabled(local_recording)
        self.record_stage.setEnabled(not active and not recording)
        self.library_panel.update_state(state)
