"""RCX controls: a lightweight effect list, persistent editor and native live previews."""
import json
import copy
import time
from pathlib import Path
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QGroupBox,
    QLineEdit,QListWidget,QListWidgetItem,QSizePolicy,QCheckBox,QComboBox,QSpinBox,QFormLayout,QColorDialog,QSplitter,QScrollArea)
from . import rcx_settings


class RcxPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("AppRoot")
        from .responsive_ui import install_field_wheel_guard
        install_field_wheel_guard()
        from .rcx_renderer import RcxRenderer
        self.renderer=RcxRenderer()
        self.config=rcx_settings.load()
        self.saved_config=copy.deepcopy(self.config)
        try:
            from .catalog import load
            self.local_names={k:v.get('nome',k) for k,v in ((load() or {}).get('habilidades') or {}).items()}
        except (OSError,ValueError):self.local_names={}
        self.catalog=[]
        for row in rcx_settings.catalog():
            self.catalog.append({**row,'key':'unit:'+str(row['unit_type']),'skills':[],'name':row['name']+' (efeito geral)'})
            for skill in row['skills']:
                self.catalog.append({**row,'key':'skill:'+str(skill['skill_id']),'skills':[skill]})
        self.rows={r['key']:r for r in self.catalog}
        self.learned={};self.seen=set();self.current=None;self.loading=False
        self.feed_path=None;self.feed_stamp=None;self.started_at=0
        layout=QVBoxLayout(self)
        top=QHBoxLayout()
        self.toggle=QPushButton('Ativar RCX');self.toggle.setCheckable(True);self.toggle.toggled.connect(self.set_enabled)
        top.addWidget(self.toggle)
        self.status=QLabel();self.status.setWordWrap(True);top.addWidget(self.status,1);layout.addLayout(top)
        self.observed=QLabel('Aguardando unidades de terreno do servidor.');layout.addWidget(self.observed)
        hint=QLabel('Efeitos ativos e previas possuem controles separados por habilidade. A previa e uma estimativa visual; nao altera as regras do combate.')
        hint.setWordWrap(True);layout.addWidget(hint)
        split=QSplitter(Qt.Horizontal);layout.addWidget(split,1)
        left=QWidget();ll=QVBoxLayout(left);ll.setContentsMargins(0,0,0,0)
        self.search=QLineEdit();self.search.setPlaceholderText('Buscar habilidade, código ou ID de efeito...');self.search.textChanged.connect(self.filter_list);ll.addWidget(self.search)
        filters=QHBoxLayout();self.only_learned=QCheckBox('Do personagem');self.only_seen=QCheckBox('No mapa')
        for field in (self.only_learned,self.only_seen):field.toggled.connect(self.filter_list);filters.addWidget(field)
        ll.addLayout(filters)
        self.effects=QListWidget();self.effects.setMinimumWidth(180);self.effects.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Expanding);self.effects.currentItemChanged.connect(self.select_effect);ll.addWidget(self.effects,1)
        self.count=QLabel();ll.addWidget(self.count);split.addWidget(left)
        right=QScrollArea();right.setWidgetResizable(True);right.setMinimumWidth(230)
        editor=QWidget();form=QVBoxLayout(editor);right.setWidget(editor);split.addWidget(right);split.setSizes([400,680])
        self.effect_title=QLabel('Selecione um efeito');self.effect_title.setWordWrap(True);form.addWidget(self.effect_title)
        self.effect_help=QLabel();self.effect_help.setWordWrap(True);form.addWidget(self.effect_help)
        box=QGroupBox('Aparência das células confirmadas');f=QFormLayout(box)
        self.effect_enabled=QCheckBox('Mostrar este efeito');f.addRow(self.effect_enabled)
        self.fill=QPushButton();self.outline=QPushButton();self.fill.clicked.connect(lambda:self.choose_color(self.fill));self.outline.clicked.connect(lambda:self.choose_color(self.outline))
        f.addRow('Preenchimento',self.fill);f.addRow('Traço',self.outline)
        self.symbol=QComboBox()
        for key,name in rcx_settings.SYMBOLS.items():self.symbol.addItem(name,key)
        f.addRow('Símbolo',self.symbol)
        self.opacity=QSpinBox();self.opacity.setRange(0,100);self.opacity.setSuffix(' %');f.addRow('Opacidade',self.opacity);form.addWidget(box)
        self.preview_box=QGroupBox('Pr\u00e9vias desta habilidade');f=QFormLayout(self.preview_box)
        self.selection_preview=QCheckBox('Mostrar area enquanto escolho a celula no jogo')
        self.cast_preview=QCheckBox('Mostrar durante a conjuracao confirmada')
        f.addRow(self.selection_preview);f.addRow(self.cast_preview)
        self.preview_color=QPushButton();self.preview_color.clicked.connect(lambda:self.choose_color(self.preview_color));f.addRow('Preenchimento',self.preview_color)
        self.preview_outline=QPushButton();self.preview_outline.clicked.connect(lambda:self.choose_color(self.preview_outline));f.addRow('Tra\u00e7o',self.preview_outline)
        self.preview_symbol=QComboBox()
        for key,name in rcx_settings.SYMBOLS.items():self.preview_symbol.addItem(name,key)
        f.addRow('S\u00edmbolo',self.preview_symbol)
        self.preview_opacity=QSpinBox();self.preview_opacity.setRange(0,100);self.preview_opacity.setSuffix(' %');f.addRow('Opacidade',self.preview_opacity)
        note=QLabel('Comeca com a aparencia do efeito acima. Voce pode personalizar a previa separadamente.');note.setWordWrap(True);f.addRow(note)
        form.addWidget(self.preview_box)
        box=QGroupBox('Área de prévia deste efeito');f=QFormLayout(box)
        self.area_override=QCheckBox('Personalizar \u00e1rea (desmarque para usar o padr\u00e3o)');f.addRow(self.area_override)
        area_hint=QLabel('Alterar raio ou formato ativa a personaliza\u00e7\u00e3o automaticamente.');area_hint.setWordWrap(True);f.addRow(area_hint)
        self.radius=QSpinBox();self.radius.setRange(0,15);self.radius.setSuffix(' células');f.addRow('Raio',self.radius)
        self.shape=QComboBox()
        for key,name in rcx_settings.SHAPES.items():self.shape.addItem(name,key)
        f.addRow('Formato',self.shape)
        self.skill_id=QSpinBox();self.skill_id.setRange(0,65535);self.skill_id.setReadOnly(True);self.skill_id.setButtonSymbols(QSpinBox.NoButtons);self.skill_id.setSpecialValueText('Varios IDs (efeito geral)');f.addRow('ID da habilidade (automatico)',self.skill_id)
        info=QLabel('ID obtido automaticamente da habilidade selecionada e bloqueado para edicao. Raio 1 em quadrado = 3x3 celulas; raio 5 = 11x11.');info.setWordWrap(True);f.addRow(info);form.addWidget(box)
        self.area_dimensions=QLabel();self.area_dimensions.setWordWrap(True);form.addWidget(self.area_dimensions)
        reset=QPushButton('Restaurar padrão deste efeito');reset.clicked.connect(self.reset_effect);form.addWidget(reset)
        self.sample=QLabel();self.sample.setMinimumHeight(64);self.sample.setAlignment(Qt.AlignCenter);form.addWidget(self.sample)
        self.save_now_button=QPushButton('Salvar agora');self.save_now_button.clicked.connect(self.save_now);form.addWidget(self.save_now_button)
        self.save_path=QLabel(str(rcx_settings.FILE));self.save_path.setWordWrap(True);self.save_path.setTextInteractionFlags(Qt.TextSelectableByMouse);form.addWidget(self.save_path)
        self.save_status=QLabel('Alteracoes salvas imediatamente neste computador.');self.save_status.setWordWrap(True);form.addWidget(self.save_status);form.addStretch()
        self.save_timer=QTimer(self);self.save_timer.setSingleShot(True);self.save_timer.timeout.connect(self.persist)
        for field in (self.effect_enabled,self.selection_preview,self.cast_preview,self.area_override):field.toggled.connect(self.edited)
        for field in (self.radius,self.opacity,self.preview_opacity):field.valueChanged.connect(self.edited)
        for field in (self.symbol,self.shape,self.preview_symbol):field.currentIndexChanged.connect(self.edited)
        self.timer=QTimer(self);self.timer.setInterval(100);self.timer.timeout.connect(self.refresh_renderer)
        self.catalog_signature=None
        self.build_list();self.set_enabled(False)

    @staticmethod
    def set_color(button,color):
        button.setProperty('rcx_color',color);button.setText(color.upper());button.setStyleSheet('background:'+color+';color:'+('black' if QColor(color).lightness()>140 else 'white'))

    def choose_color(self,button):
        color=QColorDialog.getColor(QColor(button.property('rcx_color')),self,'Cor RCX')
        if color.isValid():self.set_color(button,color.name());self.edited(appearance=button in (self.fill,self.outline))

    def build_list(self):
        selected=self.current
        self.effects.blockSignals(True);self.effects.clear()
        for row in self.catalog:
            names=[]
            for skill in row['skills']:
                metadata=self.learned.get(skill['skill_id']) or {}
                name=metadata.get('name')
                names.append(self.local_names.get(name) or name or self.local_names.get(skill['code']) or skill['name'])
            name=' / '.join(dict.fromkeys(names)) or row['name']
            item=QListWidgetItem(f"{name} — 0x{row['unit_type']:02X}"+(' • no mapa' if row['unit_type'] in self.seen else ''))
            item.setData(Qt.UserRole,row['key']);item.setToolTip(row['code']+'\n'+', '.join(str(s['skill_id'])+': '+s['code']+' / '+s['name'] for s in row['skills']))
            self.effects.addItem(item)
            if row['key']==selected:self.effects.setCurrentItem(item)
        self.effects.blockSignals(False);self.filter_list()
        if selected is None and self.effects.count():self.effects.setCurrentRow(0)

    def filter_list(self):
        query=self.search.text().casefold();visible=0
        for i in range(self.effects.count()):
            item=self.effects.item(i);row=self.rows[item.data(Qt.UserRole)]
            learned=any(s['skill_id'] in self.learned for s in row['skills']) or rcx_settings.style_for(self.config,row['unit_type'])['skill_id'] in self.learned
            hide=(query not in (item.text()+' '+item.toolTip()).casefold() or self.only_learned.isChecked() and not learned or self.only_seen.isChecked() and row['unit_type'] not in self.seen)
            item.setHidden(hide);visible+=not hide
        selected=self.effects.currentItem()
        if selected is not None and selected.isHidden():
            first=next((self.effects.item(i) for i in range(self.effects.count()) if not self.effects.item(i).isHidden()),None)
            if first is not None:self.effects.setCurrentItem(first)
        self.count.setText(f'{visible} de {len(self.catalog)} tipos de efeito • catálogo Ragnarok; nomes NRO quando recebidos')

    def select_effect(self,item,previous=None):
        if item is None:return
        self.current=item.data(Qt.UserRole);self.show_effect()

    @staticmethod
    def general_skill_id(unit_type):
        skills=[s['skill_id'] for row in rcx_settings.catalog() if row['unit_type']==unit_type for s in row['skills']]
        return skills[0] if len(skills)==1 else 0

    def show_effect(self):
        self.loading=True
        row=self.rows[self.current];style=rcx_settings.style_for(self.config,row['unit_type'],row['skills'][0]['skill_id'] if row['skills'] else None)
        if row['skills'] and not style['area_override']:
            skill=row['skills'][0];level=self.learned.get(skill['skill_id'],{}).get('level')
            style.update(radius=skill.get('radius_by_level',{}).get(str(level),skill['radius']),shape=skill['shape'])
        self.effect_title.setText(self.effects.currentItem().text())
        self.effect_help.setText('Efeito '+str(row['unit_type'])+' • '+row['code']+'\nHabilidades: '+(', '.join(f"{s['skill_id']} ({s['code']})" for s in row['skills']) or 'sem vínculo confirmado; configure o ID para habilitar a sua prévia'))
        if row['skills'] and row['skills'][0].get('ground',True):
            self.effect_help.setText(self.effect_help.text()+'\nSelecione a habilidade no jogo e mova o cursor pelo chao: a previa acompanha a celula antes de clicar. Cancele a selecao para ocultar.')
        if row['skills'] and row['skills'][0]['skill_id']==117:
            self.effect_help.setText(self.effect_help.text()+'\nArmadilha: previa da area de ativacao (padrao Ragnarok 3x3), distinta da celula onde ela e instalada. Ajuste se o NRO usar outra area.')
        if row['skills'] and not row['skills'][0].get('ground',True):
            self.effect_help.setText(self.effect_help.text()+'\nUso em si: a area aparece ao usar, ao redor do personagem. Nao espera selecionar uma celula com o mouse.')
        self.effect_enabled.setChecked(style['enabled']);self.set_color(self.fill,style['fill']);self.set_color(self.outline,style['outline'])
        self.opacity.setValue(style['opacity']);self.symbol.setCurrentIndex(self.symbol.findData(style['symbol']));self.area_override.setChecked(style['area_override']);self.radius.setEnabled(True);self.shape.setEnabled(True);self.radius.setValue(style['radius']);self.shape.setCurrentIndex(self.shape.findData(style['shape']));self.skill_id.setValue(row['skills'][0]['skill_id'] if row['skills'] else self.general_skill_id(row['unit_type']))
        count=len(list(rcx_settings.footprint(100,100,style['radius'],style['shape'])))
        self.area_dimensions.setText('Area visual: '+str(count)+' celulas'+(' ('+str(2*style['radius']+1)+'x'+str(2*style['radius']+1)+')' if style['shape']=='square' else ''))
        self.selection_preview.setChecked(style['selection_preview']);self.cast_preview.setChecked(style['cast_preview'])
        self.set_color(self.preview_color,style['preview_fill'] or style['fill'])
        self.set_color(self.preview_outline,style['preview_outline'] or style['outline'])
        self.preview_symbol.setCurrentIndex(self.preview_symbol.findData(style['preview_symbol'] or style['symbol']))
        self.preview_opacity.setValue(style['opacity'] if style['preview_opacity'] is None else style['preview_opacity'])
        self.displayed_preview=dict(preview_fill=self.preview_color.property('rcx_color'),preview_outline=self.preview_outline.property('rcx_color'),preview_symbol=self.preview_symbol.currentData(),preview_opacity=self.preview_opacity.value())
        self.loading=False;self.update_sample()

    def update_sample(self):
        self.sample.setText(rcx_settings.SYMBOLS[self.symbol.currentData()]+'  •  '+str(self.opacity.value())+' %')
        self.sample.setStyleSheet(f"background:{self.fill.property('rcx_color')};color:{self.outline.property('rcx_color')};border:2px solid {self.outline.property('rcx_color')};border-radius:6px;font-size:16pt")

    def edited(self,*args,appearance=False):
        if self.loading:return
        if self.sender() in (self.radius,self.shape):
            self.loading=True
            self.area_override.setChecked(True)
            if self.sender() is self.radius and self.radius.value()>0 and self.shape.currentData()=='point':
                self.shape.setCurrentIndex(self.shape.findData('square'))
            self.loading=False
        if self.current is not None:
            section='skill_styles' if self.current.startswith('skill:') else 'effects'
            identity=self.current.split(':')[1]
            previous=self.config[section].get(identity,{})
            self.config[section][identity]=dict(**{k:previous.get(k) for k in ('preview_fill','preview_outline','preview_symbol','preview_opacity')},enabled=self.effect_enabled.isChecked(),fill=self.fill.property('rcx_color'),outline=self.outline.property('rcx_color'),opacity=self.opacity.value(),symbol=self.symbol.currentData(),radius=self.radius.value(),shape=self.shape.currentData(),skill_id=int(self.current.split(':')[1]) if section=='skill_styles' else 0,area_override=self.area_override.isChecked(),selection_preview=self.selection_preview.isChecked(),cast_preview=self.cast_preview.isChecked())
            visible=dict(preview_fill=self.preview_color.property('rcx_color'),preview_outline=self.preview_outline.property('rcx_color'),preview_symbol=self.preview_symbol.currentData(),preview_opacity=self.preview_opacity.value())
            for key,value in visible.items():
                if value!=self.displayed_preview.get(key):self.config[section][identity][key]=value
        self.radius.setEnabled(True);self.shape.setEnabled(True)
        self.update_sample();self.persist()

    def save_now(self, *args):
        # A typed spinbox value may still be in the editor when the save button is pressed.
        previous_radius=self.radius.value()
        self.loading=True
        try:
            for field in (self.radius,self.skill_id,self.opacity,self.preview_opacity):field.interpretText()
            if self.radius.value()!=previous_radius:
                self.area_override.setChecked(True)
                if self.radius.value()>0 and self.shape.currentData()=='point':
                    self.shape.setCurrentIndex(self.shape.findData('square'))
        finally:self.loading=False
        self.edited()

    def persist(self):
        self.save_timer.stop()
        try:
            self.config=rcx_settings.save_changes(self.config,self.saved_config)
            self.saved_config=copy.deepcopy(self.config)
            if self.current is not None:self.show_effect()
        except (OSError,ValueError,TypeError) as exc:
            self.save_status.setText('Falha ao salvar em '+str(rcx_settings.FILE)+': '+str(exc))
            return False
        try:
            self.renderer.configure(self.config)
            self.save_status.setText('Preferencias RCX salvas no arquivo acima.')
        except (OSError,ValueError,TypeError) as exc:
            self.save_status.setText('Preferencias salvas; falha ao aplicar no desenho: '+str(exc))
        return True

    def reset_effect(self):
        if self.current is None:return
        section='skill_styles' if self.current.startswith('skill:') else 'effects'
        self.config[section].pop(self.current.split(':')[1],None);self.show_effect();self.persist()

    def set_enabled(self,enabled):
        if enabled:
            try:
                self.renderer.configure(self.config);self.renderer.start();self.started_at=time.monotonic();self.toggle.setText('Desativar RCX');self.status.setText('Conectando ao desenho nativo...');self.timer.start()
            except (OSError,ValueError,KeyError) as exc:
                self.toggle.blockSignals(True);self.toggle.setChecked(False);self.toggle.blockSignals(False);self.renderer.close();self.status.setText('Nao ativado: '+str(exc));self.toggle.setText('Ativar RCX')
        else:
            self.timer.stop();self.renderer.close();self.status.setText('RCX desativado.');self.toggle.setText('Ativar RCX')

    def refresh_renderer(self):
        # Legacy JSON source remains compatible with a relay from before direct mmap streaming.
        if self.feed_path is not None and not (self.renderer.state.get('ground_cells') or {}).get('feed_ipc'):
            try:
                stamp=self.feed_path.stat().st_mtime_ns
                if stamp!=self.feed_stamp:
                    ground=json.loads(self.feed_path.read_text(encoding='utf-8'));self.renderer.update({**self.renderer.state,'ground_cells':ground});self.feed_stamp=stamp
            except (OSError,ValueError):pass
        info=self.renderer.snapshot()
        if info.get('attached') and info.get('frames'):
            text=f"Ativo • {info['drawn']} células desenhadas • "+('canal direto' if info.get('direct_stream') else 'fonte do painel')
            if info.get('selected_skill'):text+=f" • mirando habilidade {info['selected_skill']}"
            self.status.setText(text if not info['error'] else 'Erro no desenho: '+str(info['error']))
        elif time.monotonic()-self.started_at>8 or info.get('error'):
            self.set_enabled(False);self.toggle.blockSignals(True);self.toggle.setChecked(False);self.toggle.blockSignals(False);self.status.setText('Nao ativado: cliente não confirmou o desenho. Confira permissões de jogo e painel.')

    def shutdown(self):
        fields=(self.radius,self.skill_id,self.opacity,self.preview_opacity)
        if any(field.lineEdit().isModified() for field in fields):self.save_now()
        elif self.config!=self.saved_config:self.persist()
        self.timer.stop();self.renderer.close()

    def closeEvent(self,event):
        self.shutdown()
        super().closeEvent(event)

    def update_state(self,state):
        ground=state.get('ground_cells') or {};feed=ground.get('feed_file');path=Path(feed) if feed else None
        if path!=self.feed_path:self.feed_path,self.feed_stamp=path,None
        self.renderer.update(state)
        self.learned={s['skill_id']:s for s in state.get('learned_skills',[]) if s.get('level',0)>0}
        self.seen={e['effect_type'] for e in ground.get('effects',[])}
        signature=(tuple((i,s.get('name')) for i,s in self.learned.items()),tuple(sorted(self.seen)))
        if signature!=self.catalog_signature:self.catalog_signature=signature;self.build_list()
        self.observed.setText(f"Mapa: {ground.get('map') or 'aguardando'} | Habilidades de terreno: {len(ground.get('cells',[]))} celulas recebidas")


def main():
    import sys
    from PySide6.QtWidgets import QApplication
    app=QApplication(sys.argv);panel=RcxPanel();panel.setWindowTitle('NRO — RCX no chão');panel.resize(1040,760)
    root=Path(__file__).resolve().parents[1]/'logs/relay'
    def refresh():
        try:
            files=list(root.glob('*/estado.json'))
            if files:
                path=max(files,key=lambda p:p.stat().st_mtime)
                if time.time()-path.stat().st_mtime<3:panel.update_state(json.loads(path.read_text(encoding='utf-8')));return
        except (OSError,ValueError):pass
        panel.update_state({})
    timer=QTimer(panel);timer.timeout.connect(refresh);timer.start(500);app.aboutToQuit.connect(panel.shutdown);panel.show();sys.exit(app.exec())


if __name__=='__main__':main()
