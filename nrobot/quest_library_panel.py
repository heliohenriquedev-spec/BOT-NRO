"""Shared board paths and per-mission conversations, independent of hunting routes."""
import uuid
from PySide6.QtCore import Qt,Signal
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QLabel,QComboBox,QListWidget,QListWidgetItem,
    QPushButton,QInputDialog,QMessageBox,QDialog,QDialogButtonBox,QTableWidget,QTableWidgetItem)
from . import quest_library as lib
from .responsive_ui import FlowLayout,scroll_page
from .npc_labels import clean,plain,mission_option,mission_label


class QuestLibraryPanel(QWidget):
    command_requested=Signal(str,dict)
    def __init__(self):
        super().__init__();self.data={};self.state={};self.stamp=None;self.was_shared=False
        layout=QVBoxLayout(self)
        hint=QLabel('Cadastre uma vez e reutilize em todas as rotas. 1. Grave o acesso ate cada quadro, sem abri-lo. 2. Ao lado do quadro, crie cada missao e grave como pegar e entregar. 3. Em Editar rota, marque as missoes desejadas, de um quadro ou dos dois.')
        hint.setWordWrap(True);layout.addWidget(hint)
        self.boards=QComboBox()
        for b in lib.BOARDS:self.boards.addItem(b['name'],b['id'])
        self.boards.currentIndexChanged.connect(self.show_board);layout.addWidget(self.boards)
        self.location=QLabel();self.location.setWordWrap(True);layout.addWidget(self.location)
        layout.addWidget(QLabel('Percursos compartilhados ate este quadro'))
        self.paths=QListWidget();self.paths.setMinimumHeight(80);self.paths.setMaximumHeight(110);layout.addWidget(self.paths)
        path_actions=FlowLayout();layout.addLayout(path_actions);self.edit_buttons=[]
        self.add_button(path_actions,'Gravar novo percurso de acesso',lambda:self.request('quest_library_record',scope='access',board_id=self.boards.currentData()))
        self.add_button(path_actions,'Executar percurso selecionado',self.test_access)
        self.add_button(path_actions,'Excluir percurso',lambda:self.delete('access_paths'))
        self.add_button(path_actions,'Ver percurso',lambda:self.preview('access_paths'))
        returns=FlowLayout();layout.addLayout(returns)
        self.add_button(returns,'Gravar retorno do quadro',lambda:self.request('quest_library_record',scope='return',board_id=self.boards.currentData()))
        self.add_button(returns,'Executar Retorno',lambda:self.request('quest_library_test',mode='return',board_id=self.boards.currentData()))
        layout.addWidget(QLabel('Missoes e opcoes deste quadro'))
        menu_actions=FlowLayout();layout.addLayout(menu_actions)
        self.add_button(menu_actions,'Gravar menus do quadro',lambda:self.request('quest_library_record',scope='menus',board_id=self.boards.currentData()))
        self.add_button(menu_actions,'Selecionar missoes das opcoes salvas',self.import_options)
        self.missions=QListWidget();self.missions.setMinimumHeight(110);self.missions.setMaximumHeight(145);layout.addWidget(self.missions,1)
        self.missions.itemChanged.connect(self.check_changed)
        checks=FlowLayout();layout.addLayout(checks)
        self.add_button(checks,'Marcar todas',lambda:self.check_all(True))
        self.add_button(checks,'Desmarcar todas',lambda:self.check_all(False))
        self.checked_label=QLabel();checks.addWidget(self.checked_label)
        actions=FlowLayout();layout.addLayout(actions)
        self.add_button(actions,'Nova missao',self.new_mission)
        self.add_button(actions,'Renomear',self.rename)
        self.add_button(actions,'Configurar rank e monstros',self.configure_mission)
        self.add_button(actions,'Gravar como pegar',lambda:self.record_mission('pickup'))
        self.add_button(actions,'Gravar como entregar',lambda:self.record_mission('delivery'))
        self.add_button(actions,'Ver opcoes',lambda:self.preview('missions'))
        self.add_button(actions,'Excluir missao',lambda:self.delete('missions'))
        tests=FlowLayout();layout.addLayout(tests)
        self.add_button(tests,'Executar: pegar missoes marcadas',lambda:self.test_mission('pickup'))
        self.add_button(tests,'Executar: entregar/completar marcadas',lambda:self.test_mission('delivery'))
        self.stop_test=QPushButton('Parar teste');self.stop_test.clicked.connect(lambda:self.request('quest_stop'));tests.addWidget(self.stop_test)
        finish_actions=FlowLayout();layout.addLayout(finish_actions)
        self.finish=QPushButton('Salvar gravacao compartilhada');self.finish.clicked.connect(self.finish_recording);finish_actions.addWidget(self.finish)
        self.cancel=QPushButton('Descartar gravacao');self.cancel.clicked.connect(lambda:self.request('quest_record_cancel'));finish_actions.addWidget(self.cancel)
        self.notice=QLabel();self.notice.setWordWrap(True);layout.addWidget(self.notice)
        self.reload();self.update_state({})

    def add_button(self,layout,title,callback):
        b=QPushButton(title);b.clicked.connect(callback);layout.addWidget(b);self.edit_buttons.append(b)

    def request(self,command,**values):self.command_requested.emit(command,values)

    def reload(self):
        try:
            self.data=lib.load();self.stamp=lib.FILE.stat().st_mtime_ns if lib.FILE.exists() else None
            self.show_board()
        except (OSError,ValueError) as exc:self.notice.setText(str(exc))

    def show_board(self):
        if not self.data:return
        b=lib.board(self.data,self.boards.currentData());via=b['via']
        self.location.setText(f"{b['map']} {b['position']} • Acesso por {via['name'] or 'NPC de entrada'} em {via['map']} {via['position']}. "
                              'Ao gravar o acesso, caminhe ate perto do quadro e salve antes de abrir sua conversa. Grave outros percursos para ensinar retornos e ligacoes entre quadros. '+
                              f"Retorno em {b['return_npc']['position']}. Catalogo: {len(self.data['menus'].get(b['id'],[]))} menus / {len({s for menu in self.data['menus'].get(b['id'],[]) for s in menu})} opcoes salvas.")
        self.missions.blockSignals(True)
        for widget,group in ((self.paths,'access_paths'),(self.missions,'missions')):
            old=widget.currentItem().data(Qt.UserRole) if widget.currentItem() else None;widget.clear()
            for entry in self.data[group]:
                if entry['board_id']!=b['id']:continue
                if group=='access_paths':description=f"{entry['name']} • {len(entry['steps'])} etapas"
                else:
                    from .quest_slots import effective_steps
                    statuses=[]
                    for stage,title in (('pickup','Pegar'),('delivery','Entregar')):
                        script=effective_steps(self.data,entry,stage)
                        status='slots automaticos' if any(s['kind']=='select_free_slot' for s in script) else 'gravado' if entry[stage+'_steps'] else 'modelo do quadro' if script else 'falta gravar modelo'
                        statuses.append(title+': '+status)
                    description=mission_label(entry)+' • '+' • '.join(statuses)
                item=QListWidgetItem(description);item.setData(Qt.UserRole,entry['id'])
                if group=='missions':
                    item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if entry['id'] in self.data['checked_missions'] else Qt.Unchecked)
                widget.addItem(item)
                if old==entry['id']:widget.setCurrentItem(item)
        self.missions.blockSignals(False)
        count=len(self.checked());self.checked_label.setText(f'{count} marcada(s) para executar' if count else 'Nenhuma marcada: executa a selecionada')

    def checked(self):
        board=self.boards.currentData()
        board_ids={m['id'] for m in self.data['missions'] if m['board_id']==board}
        return [i for i in self.data['checked_missions'] if i in board_ids]

    def check_changed(self,item):
        identity=item.data(Qt.UserRole);checked=self.data['checked_missions']
        if item.checkState()==Qt.Checked and identity not in checked:checked.append(identity)
        elif item.checkState()!=Qt.Checked and identity in checked:checked.remove(identity)
        self.persist()

    def check_all(self,value):
        board=self.boards.currentData()
        ids=[m['id'] for m in self.data['missions'] if m['board_id']==board]
        others=[i for i in self.data['checked_missions'] if i not in ids]
        self.data['checked_missions']=others+(ids if value else [])
        self.persist()

    def selected(self,group):
        widget=self.paths if group=='access_paths' else self.missions
        item=widget.currentItem()
        return next((m for m in self.data[group] if item and m['id']==item.data(Qt.UserRole)),None)

    def persist(self):
        try:lib.save(self.data);self.reload();return True
        except (OSError,ValueError) as exc:self.notice.setText(str(exc));return False

    def new_mission(self):
        name,ok=QInputDialog.getText(self,'Nova missao','Nome da missao como aparece no quadro:')
        if ok and name.strip():
            identity=uuid.uuid4().hex
            self.data['missions'].append(dict(id=identity,name=name.strip(),board_id=self.boards.currentData()))
            if self.persist():
                for i in range(self.missions.count()):
                    if self.missions.item(i).data(Qt.UserRole)==identity:self.missions.setCurrentRow(i)

    def import_options(self):
        choices={}
        for menu in self.data['menus'].get(self.boards.currentData(),[]):
            for option in menu:
                if mission_option(option):choices.setdefault(plain(option),option)
        options=list(choices.values())
        if not options:self.notice.setText('Use Gravar menus do quadro, abra as opcoes no jogo, feche o dialogo e salve.');return
        dialog=QDialog(self);dialog.setWindowTitle('Opcoes recebidas do quadro');layout=QVBoxLayout(dialog)
        hint=QLabel('Marque as missoes desejadas. Slots vazios e opcoes de navegacao nao sao missoes. Monstros aparecem quando a descricao foi recebida ou cadastrada; use Configurar rank e monstros para completar.');hint.setWordWrap(True);layout.addWidget(hint)
        items=QListWidget();layout.addWidget(items)
        from .monster_db import all_monsters
        monsters=all_monsters() if self.data.get('option_details',{}).get(self.boards.currentData()) else []
        # Linked to the registered missions: those already registered come ticked; unticking removes them.
        board=self.boards.currentData()
        def registered(option):
            return next((m for m in self.data['missions'] if m['board_id']==board
                         and plain(option) in (plain(m['name']),plain(m.get('menu_option') or ''))),None)
        for option in options:
            candidate=lib.enrich_mission(dict(name=clean(option)),lib.option_descriptions(self.data,board,option),monsters=monsters)
            item=QListWidgetItem(mission_label(candidate));item.setData(Qt.UserRole,option)
            item.setToolTip(candidate.get('description',''));item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if registered(option) else Qt.Unchecked);items.addItem(item)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec():
            removed=[]
            for i in range(items.count()):
                item=items.item(i);option=item.data(Qt.UserRole);existing=registered(option)
                if item.checkState()==Qt.Checked and existing is None:
                    m=dict(id=uuid.uuid4().hex,name=clean(option),menu_option=option,board_id=board)
                    lib.enrich_mission(m,lib.option_descriptions(self.data,board,option),monsters=monsters)
                    self.data['missions'].append(m)
                elif item.checkState()!=Qt.Checked and existing is not None:removed.append(existing)
            if removed:
                from .quest_routes import load
                try:used={i for r in load() for i in r['mission_ids']}
                except (OSError,ValueError):used=set()
                kept=[m for m in removed if m['id'] in used];removed=[m for m in removed if m['id'] not in used]
                if removed and QMessageBox.question(self,'Remover missoes','Remover do cadastro: '+', '.join(m['name'] for m in removed)+'?')==QMessageBox.Yes:
                    for m in removed:self.data['missions'].remove(m)
                if kept:self.notice.setText('Mantidas porque estao em rotas (desmarque nas rotas antes): '+', '.join(m['name'] for m in kept))
            self.persist()

    def rename(self):
        m=self.selected('missions')
        if not m:return
        name,ok=QInputDialog.getText(self,'Renomear missao','Nome:',text=m['name'])
        if ok and name.strip():m['name']=name.strip();self.persist()

    def configure_mission(self):
        m=self.selected('missions')
        if not m:return
        from .mission_details import MissionDetails
        dialog=MissionDetails(m,self)
        if dialog.exec():
            self.data['missions'][self.data['missions'].index(m)]=dialog.mission;self.persist()

    def delete(self,group):
        entry=self.selected(group)
        if not entry:return
        if group=='missions':
            from .quest_routes import load
            try:users=[r['name'] for r in load() if entry['id'] in r['mission_ids']]
            except (OSError,ValueError) as exc:self.notice.setText(str(exc));return
            if users:self.notice.setText('Desmarque esta missao nas rotas antes de excluir: '+', '.join(users));return
        if QMessageBox.question(self,'Excluir cadastro','Excluir '+entry['name']+'?')==QMessageBox.Yes:
            self.data[group].remove(entry);self.persist()

    def record_mission(self,stage):
        m=self.selected('missions')
        if m:self.request('quest_library_record',scope='mission',mission_id=m['id'],stage=stage)
        else:self.notice.setText('Crie ou selecione uma missao deste quadro')

    def test_access(self):
        path=self.selected('access_paths')
        if path:self.request('quest_library_test',mode='access',path_id=path['id'])
        else:self.notice.setText('Selecione um percurso salvo para executar')

    def test_mission(self,stage):
        # Ticked missions in list order; without ticks, the highlighted one.
        order=[m['id'] for m in self.data['missions']]
        ids=sorted(self.checked(),key=order.index)
        if not ids and self.selected('missions'):ids=[self.selected('missions')['id']]
        if ids:self.request('quest_library_test',mode=stage,mission_ids=ids,mission_id=ids[0])
        else:self.notice.setText('Marque as missoes (ou selecione uma) com esta etapa gravada para executar')

    def finish_recording(self):
        q=self.state.get('quests',{});values={}
        if q.get('recording_scope')=='mission':
            confirmation,ok=QInputDialog.getText(self,'Mensagem de sucesso',
                'Trecho da resposta que confirmou esta missao (nao use apenas o nome):',text=q.get('last_npc_text',''))
            if not ok:return
            values['confirmation']=confirmation.strip()
        self.request('quest_library_save',**values)

    def preview(self,group):
        entry=self.selected(group)
        if not entry:return
        dialog=QDialog(self);dialog.setWindowTitle(entry['name']);layout=QVBoxLayout(dialog)
        table=QTableWidget(0,4);table.setHorizontalHeaderLabels(['Trecho','Mapa','Acao','Detalhes']);table.setEditTriggers(QTableWidget.NoEditTriggers)
        sets=[('Acesso',entry['steps'])] if group=='access_paths' else [('Pegar',entry['pickup_steps']),('Entregar',entry['delivery_steps'])]
        for name,steps in sets:
            for step in steps:
                row=table.rowCount();table.insertRow(row)
                for col,value in enumerate((name,step['map'],step['kind'],step.get('option') or step.get('name') or str(step.get('position','')))):
                    table.setItem(row,col,QTableWidgetItem(clean(value)))
        table.resizeColumnsToContents();layout.addWidget(table)
        if group=='missions':
            label=QLabel('Confirmacao ao pegar: '+entry['pickup_confirmation']+'\nConfirmacao ao entregar: '+entry['delivery_confirmation']);label.setWordWrap(True);layout.addWidget(label)
        close=QDialogButtonBox(QDialogButtonBox.Close);close.rejected.connect(dialog.reject);layout.addWidget(close)
        area=self.screen().availableGeometry();dialog.resize(min(800,area.width()-40),min(550,area.height()-60));dialog.exec()

    def update_state(self,state):
        self.state=state;q=state.get('quests',{});recording=bool(q.get('recording'));active=q.get('phase') in ('pickup','travel','hunt','delivery','return')
        stamp=lib.FILE.stat().st_mtime_ns if lib.FILE.exists() else None
        if stamp!=self.stamp:self.reload()
        for b in self.edit_buttons:b.setEnabled(not active and not recording)
        self.boards.setEnabled(not active and not recording)
        shared=q.get('recording_scope') in ('access','return','mission','menus')
        self.finish.setEnabled(shared);self.cancel.setEnabled(shared)
        if shared:self.notice.setText(f"Gravando {q.get('recording_label') or ''} • {q.get('recorded_steps',0)} etapas • {q.get('recorded_menus',0)} menus / {q.get('recorded_options',0)} opcoes • {q.get('reason','')}")
        elif self.was_shared:self.notice.setText(q.get('reason','Gravacao encerrada'))
        elif q.get('validation'):self.notice.setText(q.get('reason','Teste em andamento'))
        self.stop_test.setEnabled(bool(q.get('validation')) and active)
        self.was_shared=shared
