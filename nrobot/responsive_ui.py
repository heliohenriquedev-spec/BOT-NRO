"""Responsive native Qt layouts, shared theme and non-compressing form pages."""
from PySide6.QtCore import Qt, QSize, QRect, QObject, QEvent, QCoreApplication
from PySide6.QtGui import QPainter, QPalette, QGuiApplication
from PySide6.QtWidgets import (QLayout, QWidgetItem, QWidget, QCheckBox, QStyleOptionButton, QStyle,
    QSizePolicy, QScrollArea, QVBoxLayout, QHBoxLayout, QBoxLayout, QFormLayout, QTabWidget,
    QListWidget, QAbstractItemView, QLabel, QPushButton, QGroupBox, QTableWidget, QToolButton,
    QApplication, QAbstractSpinBox, QComboBox, QAbstractScrollArea)


THEME = '''
QMainWindow, QDialog, QMessageBox, QWidget#AppRoot { background: #0c1423; color: #e5edf7; }
QWidget { color: #e5edf7; font-family: 'Segoe UI'; font-size: 10pt; }
QLabel { background: transparent; }
QLabel#AppTitle { font-size: 22pt; font-weight: 650; color: #f4f8ff; }
QLabel#Muted, QLabel#Version { color: #91a4bd; font-size: 9pt; }
QLabel#Status { background: #132c35; color: #91edda; border: 1px solid #244b50; border-radius: 8px; padding: 8px 12px; }
QGroupBox { background: #121f33; border: 1px solid #283950; border-radius: 10px; margin-top: 15px; padding: 18px 14px 12px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 16px; padding: 0 5px; color: #9eb6d3; }
QLineEdit, QAbstractSpinBox, QComboBox { background: #0c1728; border: 1px solid #31445e; border-radius: 6px; min-height: 24px; padding: 4px 8px; selection-background-color: #136d70; }
QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus { border-color: #46cbb5; }
QPlainTextEdit, QListWidget { background: #0d192b; border: 1px solid #2a3b53; border-radius: 7px; padding: 5px; }
QPushButton, QToolButton { background: #20314a; border: 1px solid #354b67; border-radius: 6px; padding: 7px 12px; min-height: 22px; font-weight: 600; }
QPushButton:hover, QToolButton:hover { background: #2c4260; border-color: #5b7899; }
QPushButton:disabled { color: #687d96; background: #152236; border-color: #25364b; }
QPushButton#StartAction { background: #48d6b3; color: #08251e; border-color: #48d6b3; }
QPushButton#StopAction { color: #ffc391; border-color: #986846; }
QPushButton#CloseAction { color: #f3a5ae; }
QCheckBox { spacing: 8px; font-weight: 400; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #536982; border-radius: 4px; background: #101d30; }
QCheckBox::indicator:checked { background: #38bda2; border-color: #68e3c9; image: none; }
QTabWidget::pane { background: #0f1a2b; border: 1px solid #24364e; border-radius: 8px; }
QTabBar::tab { background: #18263b; color: #a8bad0; padding: 10px 14px; border: 0; margin: 1px; }
QTabBar::tab:selected { background: #22433f; color: #8fe8d1; }
QScrollArea { border: 0; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: #101c2d; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #3a526f; min-height: 26px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QTableWidget { background: #101d30; alternate-background-color: #14243a; gridline-color: #263951; border: 1px solid #2c4059; selection-background-color: #24594f; }
QHeaderView::section { background: #1d2e46; color: #b7cbe2; border: 0; border-right: 1px solid #2c415e; padding: 8px; font-weight: 600; }
QListWidget#Navigation { background: #0f1a2b; border: 0; padding: 8px 4px; }
QListWidget#Navigation::item { padding: 12px 14px; border-radius: 7px; margin: 3px; }
QListWidget#Navigation::item:selected { background: #1e4b43; color: #8ce9d2; }
QListWidget#Navigation::item:hover { background: #20334b; }
'''

# Softer slate surfaces, mint accents and clear keyboard/pressed feedback.
for old, new in {
    '#0c1423':'#171e27', '#0f1a2b':'#202934', '#121f33':'#242f3c',
    '#0c1728':'#18212c', '#0d192b':'#1b2531', '#101d30':'#1d2835',
    '#14243a':'#253341', '#20314a':'#344659', '#18263b':'#293746',
    '#1d2e46':'#304255', '#0f1a2b':'#202b37', '#e5edf7':'#e8eef2',
    '#48d6b3':'#78d8bc', '#08251e':'#102d25', '#2c4260':'#435d72',
}.items():
    THEME = THEME.replace(old, new)
THEME += '''
QPushButton:pressed, QToolButton:pressed { background: #1c6d65; border-color: #8de2ca; }
QPushButton:focus, QToolButton:focus, QCheckBox:focus { border: 1px solid #94e4d0; }
QPushButton:checked { background: #28584f; border-color: #70c9b3; }
QPushButton#StartAction:hover { background: #a1ead4; }
QComboBox::drop-down { width: 24px; border-left: 1px solid #405569; }
QToolTip { color: #eef6f5; background: #304653; border: 1px solid #76bcaf; padding: 8px; }
QTableWidget::item:hover { background: #304c56; }
'''


class FieldWheelGuard(QObject):
    """Wheel scrolls the surrounding page, never changes a form value.

    An application filter also covers table editors and dialogs created later.
    Keyboard arrows, clicks, typing and opened combo lists retain normal behavior.
    """
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and isinstance(obj, (QAbstractSpinBox, QComboBox)):
            parent = obj.parentWidget()
            while parent is not None:
                if isinstance(parent, QAbstractScrollArea):
                    QCoreApplication.sendEvent(parent.viewport(), event)
                    return True
                parent = parent.parentWidget()
            event.ignore()
            return True
        return False


def install_field_wheel_guard():
    app = QApplication.instance()
    if app is not None and not hasattr(app, '_field_wheel_guard'):
        app._field_wheel_guard = FieldWheelGuard(app)
        app.installEventFilter(app._field_wheel_guard)


class WrappingCheckBox(QCheckBox):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        policy=QSizePolicy(QSizePolicy.Expanding,QSizePolicy.Preferred)
        policy.setHeightForWidth(True);self.setSizePolicy(policy)
    def heightForWidth(self,width):
        indicator=self.style().pixelMetric(QStyle.PM_IndicatorWidth)
        return max(30,self.fontMetrics().boundingRect(QRect(0,0,max(40,width-indicator-14),10000),Qt.TextWordWrap,self.text()).height()+10)
    def sizeHint(self):return QSize(420,self.heightForWidth(420))
    def minimumSizeHint(self):return QSize(140,30)
    def hitButton(self,pos):return self.rect().contains(pos)
    def paintEvent(self,event):
        painter=QPainter(self);option=QStyleOptionButton();self.initStyleOption(option)
        option.text='';self.style().drawControl(QStyle.CE_CheckBox,option,painter,self)
        if self.isChecked():
            indicator = self.style().subElementRect(QStyle.SE_CheckBoxIndicator, option, self)
            pen = painter.pen();pen.setColor(Qt.white);pen.setWidth(2);painter.setPen(pen)
            x,y = indicator.x(),indicator.center().y()
            painter.drawLine(x+4,y,x+7,y+3);painter.drawLine(x+7,y+3,x+13,y-4)
        offset=self.style().pixelMetric(QStyle.PM_IndicatorWidth)+10
        painter.setPen(self.palette().color(QPalette.Active if self.isEnabled() else QPalette.Disabled,QPalette.WindowText))
        painter.drawText(self.rect().adjusted(offset,2,-3,-2),Qt.TextWordWrap|Qt.AlignVCenter,self.text())


class FlowLayout(QLayout):
    def __init__(self,parent=None,spacing=8):
        super().__init__(parent);self.items=[];self.setContentsMargins(0,0,0,0);self.setSpacing(spacing)
    def addItem(self,item):self.items.append(item)
    def count(self):return len(self.items)
    def itemAt(self,index):return self.items[index] if 0<=index<len(self.items) else None
    def takeAt(self,index):return self.items.pop(index) if 0<=index<len(self.items) else None
    def expandingDirections(self):return Qt.Orientations()
    def hasHeightForWidth(self):return True
    def heightForWidth(self,width):return self.arrange(QRect(0,0,width,0),True)
    def sizeHint(self):return self.minimumSize()
    def minimumSize(self):
        size=QSize(0,0)
        for item in self.items:size=size.expandedTo(item.minimumSize())
        return size
    def setGeometry(self,rect):super().setGeometry(rect);self.arrange(rect,False)
    def arrange(self,rect,test):
        x,y,line=rect.x(),rect.y(),0
        for item in self.items:
            size=item.sizeHint();width=min(size.width(),max(1,rect.width()))
            if x>rect.x() and x+width>rect.right()+1:x=rect.x();y+=line+self.spacing();line=0
            if not test:item.setGeometry(QRect(x,y,width,size.height()))
            x+=width+self.spacing();line=max(line,size.height())
        return y+line-rect.y()


def scroll_page(widget):
    scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QScrollArea.NoFrame)
    if widget.layout():widget.layout().setSizeConstraint(QLayout.SetMinimumSize)
    scroll.setWidget(widget)
    return scroll


class PanelLayout(QObject):
    def __init__(self,panel,c):
        super().__init__(panel);self.panel=panel;self.busy=False
        install_field_wheel_guard()
        panel.centralWidget().setObjectName('AppRoot');panel.setStyleSheet(THEME)
        self.layout=c['layout'];self.layout.setContentsMargins(18,14,18,12);self.layout.setSpacing(10)
        c['title'].setText('NRO  /  Central de caça');c['title'].setObjectName('AppTitle');c['title'].setStyleSheet('')
        c['revision'].setToolTip(c['revision'].text());c['revision'].setText(c['revision'].text().split('|')[0].strip());c['revision'].setObjectName('Version')
        header=QHBoxLayout();self.layout.removeWidget(c['title']);self.layout.removeWidget(c['revision'])
        header.addWidget(c['title'],1);header.addWidget(c['revision']);self.layout.insertLayout(0,header)
        panel.status_label.setObjectName('Status')
        # Connection paths are useful in setup, not as a permanent large header row.
        self.layout.removeItem(c['game_row'])
        connection=QWidget();connection_layout=QVBoxLayout(connection)
        card=QGroupBox('Instalacao e pasta do jogo');card_layout=QVBoxLayout(card);card_layout.addLayout(c['game_row'])
        info=QLabel('Selecione a pasta que contem DATA.INI e NRO.exe. As configuracoes deste computador sao preservadas nas atualizacoes.')
        info.setWordWrap(True);card_layout.addWidget(info);connection_layout.addWidget(card);connection_layout.addStretch()
        self.layout.removeItem(c['buttons']);action_widget=QWidget();actions=FlowLayout(action_widget)
        index=0
        while c['buttons'].count():
            item=c['buttons'].takeAt(0);w=item.widget()
            if w:
                w.setMinimumWidth(110);actions.addWidget(w)
                if index==1:w.setObjectName('StartAction')
                elif index==3:w.setObjectName('StopAction')
                elif index==4:w.setObjectName('CloseAction')
                index+=1
        self.layout.insertWidget(2,action_widget)
        # Each configuration category has its own scrollable content, never a compressed form row.
        self.config_layout=c['config_layout'];self.species=c['species_scroll']
        self.species.setMinimumWidth(250);self.species.setMaximumWidth(330)
        parameters=c['parameters'];form=c['form'];settings_tabs=QTabWidget()
        for widget in (c['group_box'],c['presence_box'],c['keys_box'],c['apply']):form.removeWidget(widget)
        settings_tabs.addTab(scroll_page(parameters),'Navegacao')
        for key,label in (('group_box','Grupo'),('presence_box','Presenca'),('keys_box','Atalhos')):
            page=QWidget();box=QVBoxLayout(page);box.addWidget(c[key]);box.addStretch()
            settings_tabs.addTab(scroll_page(page),label)
        self.config_layout.removeWidget(parameters)
        right=QWidget();right_layout=QVBoxLayout(right);right_layout.setContentsMargins(0,0,0,0)
        right_layout.addWidget(settings_tabs,1);right_layout.addWidget(c['apply']);self.config_layout.addWidget(right,1)
        self.configuration=c['configuration'];self.settings_tabs=settings_tabs
        self.species.setMinimumHeight(280);right.setMinimumHeight(350)
        for form_layout in panel.findChildren(QFormLayout):
            for row in range(form_layout.rowCount()):
                item = form_layout.itemAt(row, QFormLayout.LabelRole)
                if item and isinstance(item.widget(), QLabel):
                    item.widget().setMinimumWidth(130)
                    item.widget().setMaximumWidth(240)
            form_layout.setRowWrapPolicy(QFormLayout.WrapLongRows);form_layout.setSpacing(12)
        for field in (panel.radius,panel.step,panel.resume_delay,panel.group_distance,*panel.combat_fields.values()):
            field.setMaximumWidth(280)
        panel.group_members.setMinimumHeight(74);panel.allowed_players.setMinimumHeight(92)
        tabs=panel.tabs
        # Preserve the tab indexes/signals used by the existing controller.
        scroll_indexes=[0,1,2,3,6]
        if hasattr(panel,'quest_panel'):
            quest_index=tabs.indexOf(panel.quest_panel)
            if quest_index>=0 and quest_index not in scroll_indexes:scroll_indexes.append(quest_index)
        for index in scroll_indexes:
            page=tabs.widget(index);text=tabs.tabText(index)
            tabs.removeTab(index);tabs.insertTab(index,scroll_page(page),text)
        tabs.addTab(scroll_page(connection),'Conexao')
        self.layout.removeWidget(tabs)
        body=QHBoxLayout();body.setSpacing(12);self.nav=QListWidget();self.nav.setObjectName('Navigation')
        self.nav.setFixedWidth(185)
        for i in range(tabs.count()):self.nav.addItem(tabs.tabText(i))
        self.nav.currentRowChanged.connect(tabs.setCurrentIndex);tabs.currentChanged.connect(self.nav.setCurrentRow)
        self.nav.setCurrentRow(tabs.currentIndex());body.addWidget(self.nav);body.addWidget(tabs,1)
        self.layout.insertLayout(self.layout.count()-2,body,1)
        for label in panel.findChildren(QLabel):
            label.setWordWrap(True)
            policy=QSizePolicy(QSizePolicy.Preferred,QSizePolicy.Preferred)
            policy.setHeightForWidth(True)
            label.setSizePolicy(policy)
        for table in panel.findChildren(QTableWidget):
            table.setAlternatingRowColors(True);table.verticalHeader().setDefaultSectionSize(42)
            table.setMinimumHeight(190)
        for button in panel.findChildren(QPushButton):
            button.setCursor(Qt.PointingHandCursor)
        # Long group titles do not support wrapping in Qt.
        for group in panel.findChildren(QGroupBox):
            if len(group.title())>75:group.setToolTip(group.title());group.setTitle('Ordem de habilidades')
        panel.installEventFilter(self);self.reflow()

    def reflow(self):
        if self.busy:return
        self.busy=True
        try:
            wide=self.panel.width()>=1120
            self.nav.setVisible(wide);self.panel.tabs.tabBar().setVisible(not wide)
            self.panel.tabs.setUsesScrollButtons(True);self.panel.tabs.setElideMode(Qt.ElideNone)
            self.config_layout.setDirection(QBoxLayout.LeftToRight)
            species_index = self.settings_tabs.indexOf(self.species)
            if wide and species_index >= 0:
                self.settings_tabs.removeTab(species_index)
                self.config_layout.insertWidget(0, self.species)
                self.species.show()
            elif not wide and species_index < 0:
                self.config_layout.removeWidget(self.species)
                self.settings_tabs.insertTab(0, self.species, 'Monstros alvo')
            self.configuration.setMinimumHeight(350)
            self.species.setMaximumWidth(330 if wide else 16777215)
            self.species.setMaximumHeight(16777215)
        finally:self.busy=False

    def fit_to_screen(self):
        screen=QGuiApplication.screenAt(self.panel.frameGeometry().center()) or QGuiApplication.primaryScreen()
        if screen is None:return
        area=screen.availableGeometry()
        self.panel.setMinimumSize(min(740,area.width()),min(480,area.height()))
        self.panel.resize(min(self.panel.width(),area.width()),min(self.panel.height(),area.height()))
        self.panel.move(max(area.left(),min(self.panel.x(),area.right()-self.panel.width()+1)),
                        max(area.top(),min(self.panel.y(),area.bottom()-self.panel.height()+1)))
        self.reflow()

    def eventFilter(self,obj,event):
        if obj is self.panel and event.type()==QEvent.Resize:self.reflow()
        return False


def dialogs_block_only_their_window():
    """Dialogs opened with exec() were application-modal: while one was open (the item database,
    the hunt window), Qt blocked the mouse on every other window of the bot, so the minimap and the
    quest counter over the game could not be dragged or clicked. With a parent they are now
    window-modal: they block only the window they came from; the overlays stay usable."""
    from PySide6.QtWidgets import QDialog
    if getattr(QDialog, '_window_modal_exec', False):
        return
    original = QDialog.exec

    def exec_window_modal(self, *args):
        if self.windowModality() == Qt.NonModal and self.parentWidget() is not None:
            self.setWindowModality(Qt.WindowModal)
        return original(self, *args)
    QDialog.exec = exec_window_modal
    QDialog._window_modal_exec = True
