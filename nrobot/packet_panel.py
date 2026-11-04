"""REDE-37: local dashboard for the packet relay; no game input simulation."""
from datetime import datetime
import html
import json
from pathlib import Path
import sys
import time
import uuid

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QSpinBox, QDoubleSpinBox, QFormLayout, QGroupBox, QPlainTextEdit,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QScrollArea, QComboBox, QLineEdit, QListWidget, QListWidgetItem)

from .responsive_ui import WrappingCheckBox as QCheckBox
from .packet_settings import ROOT, SPECIES, DEFAULTS, read, save


class PacketPanel(QMainWindow):
    def __init__(self):
        super().__init__()
        font_path = Path('C:/Windows/Fonts/segoeui.ttf')
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))
        self.setFont(QFont('Segoe UI', 10))
        self.setStyleSheet('QPushButton { padding: 8px 12px; } QGroupBox { margin-top: 12px; padding: 12px; } QTabWidget::pane { padding: 8px; }')
        from .updater import local_version
        self.setWindowTitle(f"{local_version().get('version', 'dev')} | NRO • Painel por pacotes")
        self.resize(1260, 820)
        self.session = None
        self.pending_command = None
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(ROOT))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert('PYTHONUTF8', '1')
        environment.insert('PYTHONIOENCODING', 'utf-8')
        self.process.setProcessEnvironment(environment)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        title = QLabel('Caça e patrulha por pacotes')
        title.setStyleSheet('font-size:24px;font-weight:600;padding:8px 0')
        layout.addWidget(title)
        revision = QLabel(f"Versão {local_version().get('version', 'dev')} | Pasta: "+str(ROOT))
        layout.addWidget(revision)
        game_row = QHBoxLayout()
        game_row.addWidget(QLabel('Pasta do jogo:'))
        from PySide6.QtWidgets import QLineEdit
        self.game_field = QLineEdit()
        self.game_field.setPlaceholderText(r'Cole aqui o caminho da pasta do jogo, ex.: D:\Jogos\NRO (a pasta que tem DATA.INI)')
        self.game_field.setClearButtonEnabled(True)
        self.game_field.returnPressed.connect(self.save_game_field)
        game_row.addWidget(self.game_field, 1)
        save_game = QPushButton('Salvar')
        save_game.clicked.connect(self.save_game_field)
        game_row.addWidget(save_game)
        browse_game = QPushButton('Procurar...')
        browse_game.clicked.connect(self.choose_game_folder)
        game_row.addWidget(browse_game)
        self.game_label = QLabel()
        game_row.addWidget(self.game_label)
        layout.addLayout(game_row)
        self.show_game_folder()
        self.build_auto_login(layout)
        self.status_label = QLabel('Conexão fechada • abra a conexão e entre pelo perfil local')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        buttons = QHBoxLayout()
        self.open_button = QPushButton('Abrir conexão')
        self.open_button.clicked.connect(self.open_relay)
        buttons.addWidget(self.open_button)
        for label, command in [('Iniciar', 'start'), ('Pausar', 'pause'), ('Parar envios', 'stop')]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, cmd=command: self.command(cmd))
            buttons.addWidget(button)
        close = QPushButton('Encerrar conexão')
        close.clicked.connect(self.close_relay)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        tabs = QTabWidget()
        self.tabs = tabs
        layout.addWidget(tabs)
        configuration = QWidget()
        config_layout = QHBoxLayout(configuration)
        species_box = QGroupBox('Monstros alvo')
        species_layout = QVBoxLayout(species_box)
        self.species_layout = species_layout
        self.auto_map_targets = QCheckBox('Identificar monstros pelos dados recebidos do mapa')
        species_layout.addWidget(self.auto_map_targets)
        self.auto_map_targets.setToolTip('O modo automático inclui monstros do mapa. Você pode desmarcar cada nome confirmado pelo servidor.')
        from .monster_panel import MapTargets
        self.targets = MapTargets()  # REDE-79: only the monsters of the current map
        species_layout.addWidget(self.targets, 1)
        self.auto_map_targets.toggled.connect(self.targets.set_automatic)
        species_scroll = QScrollArea()
        species_scroll.setWidgetResizable(True)
        species_scroll.setWidget(species_box)
        species_scroll.setMinimumWidth(330)
        config_layout.addWidget(species_scroll)
        parameters = QGroupBox('Navegação e ataque')
        form = QFormLayout(parameters)
        self.radius = QSpinBox()
        self.radius.setRange(8, 60)
        self.radius.setSuffix(' células')
        form.addRow('Raio de busca', self.radius)
        self.step = QSpinBox()
        self.step.setRange(1, 8)
        self.step.setSuffix(' células')
        form.addRow('Trecho da patrulha', self.step)
        self.patrol_spacing = QSpinBox(); self.patrol_spacing.setRange(6, 40); self.patrol_spacing.setSuffix(' células')
        self.patrol_spacing.setToolTip('Distância entre os pontos da patrulha. Pontos por onde já passou perto não são revisitados.')
        form.addRow('Distância entre pontos', self.patrol_spacing)
        self.patrol_coverage = QSpinBox(); self.patrol_coverage.setRange(30, 100); self.patrol_coverage.setSuffix(' %')
        self.patrol_coverage.setToolTip('Quanto do mapa precisa ser percorrido antes de recomeçar a patrulha.')
        form.addRow('Cobrir do mapa antes de recomeçar', self.patrol_coverage)
        self.patrol_avoid_walls = QCheckBox('Ignorar pontos próximos a paredes (não encostar nas paredes)')
        form.addRow(self.patrol_avoid_walls)
        self.patrol_wall_margin = QSpinBox(); self.patrol_wall_margin.setRange(1, 8); self.patrol_wall_margin.setSuffix(' células')
        self.patrol_avoid_walls.toggled.connect(self.patrol_wall_margin.setEnabled)
        form.addRow('Distância mínima da parede', self.patrol_wall_margin)
        self.patrol_give_up = QSpinBox(); self.patrol_give_up.setRange(3, 60); self.patrol_give_up.setSuffix(' s')
        self.patrol_give_up.setToolTip('Proteção contra ponto inacessível: sem chegar mais perto nesse tempo (ou 3 passos '
                                       'recusados seguidos), o ponto é deixado de lado até o próximo ciclo.')
        form.addRow('Desistir de um ponto após', self.patrol_give_up)
        self.ignore_attackers = QSpinBox(); self.ignore_attackers.setRange(0, 20); self.ignore_attackers.setSuffix(' monstros')
        self.ignore_attackers.setToolTip('Monstros atacando o personagem: até este número são ignorados; acima dele, '
                                         'todos são atacados, de qualquer espécie. 0 = sempre ataca quem ataca.')
        form.addRow('Ignorar até (atacando você)', self.ignore_attackers)
        self.auto_movement = QCheckBox('Movimentação automática pelo mapa')
        self.auto_movement.setToolTip('Desmarque para atacar e usar habilidades ao alcance sem caminhada automática.')
        form.addRow(self.auto_movement)
        self.manual_movement = QCheckBox('Movimentação manual: eu ando pelo mapa; o bot só combate e não pausa quando clico no chão')
        self.manual_movement.setToolTip('Desliga a caminhada automática e a patrulha. Ataques, habilidades e buffs continuam; '
                                        'seus cliques no chão não pausam o bot.')
        self.manual_movement.toggled.connect(lambda on: self.auto_movement.setEnabled(not on))
        form.addRow(self.manual_movement)
        self.patrol = QCheckBox('Explorar áreas menos visitadas, variando trajetos e diagonais')
        form.addRow(self.patrol)
        self.skills = QCheckBox('Ativar habilidades configuradas')
        form.addRow(self.skills)
        explanation = QLabel('Sem colisão legível, os obstáculos são descobertos pelas respostas de movimento.')
        explanation.setWordWrap(True)
        form.addRow(explanation)
        apply = QPushButton('Salvar e aplicar • pausa a caça')
        apply.clicked.connect(self.apply)
        form.addRow(apply)
        config_layout.addWidget(parameters, 1)
        tabs.addTab(configuration, 'Configuração')
        combat = QWidget()
        combat_layout = QVBoxLayout(combat)
        combat_form = QFormLayout()
        combat_layout.addLayout(combat_form)
        self.combat_fields = {}
        fields = [('skill_global_delay', 'Delay global local (nao confirma delay do servidor)', .1, 10, ' s'),
                  ('skill_timeout', 'Espera máxima pela resposta', .75, 8, ' s'),
                  ('skill_attempts', 'Falhas permitidas por alvo', 1, 5, ''),
                  ('target_defer', 'Adiar alvo após falhas', 2, 30, ' s'),
                  ('switch_distance', 'Permitir troca quando alvo atual estiver além de', 4, 28, ' células'),
                  ('switch_saving', 'Economia mínima de distância para trocar', 1, 10, ' células'),
                  ('switch_ratio_percent', 'Distância do novo alvo: no máximo esta % da atual', 25, 90, ' %')]
        for key, label, minimum, maximum, suffix in fields:
            box = QDoubleSpinBox() if key in ('skill_interval', 'skill_timeout', 'skill_global_delay') else QSpinBox()
            box.setRange(minimum, maximum)
            if isinstance(box, QDoubleSpinBox):
                box.setDecimals(2)
                box.setSingleStep(.05)
            box.setSuffix(suffix)
            self.combat_fields[key] = box
            if key in ('skill_attempts', 'target_defer'):
                # REDE-82: each failure rule can be turned off.
                toggle = QCheckBox('Ativar')
                setattr(self, 'limit_failures' if key == 'skill_attempts' else 'defer_failed', toggle)
                toggle.toggled.connect(box.setEnabled)
                row = QHBoxLayout()
                row.addWidget(toggle)
                row.addWidget(box, 1)
                combat_form.addRow(label, row)
            elif not key.startswith('switch_'):
                combat_form.addRow(label, box)
        explanation = QLabel('O alvo atual é mantido enquanto estiver presente e válido. Cooldown informado pelo servidor, '
                             'alcance e SP continuam obrigatórios. As alterações são salvas e aplicadas sozinhas.')
        explanation.setWordWrap(True)
        combat_layout.addWidget(explanation)
        combat_buttons = QHBoxLayout()
        combat_apply = QPushButton('Salvar e aplicar • pausa a caça')
        combat_apply.clicked.connect(self.apply)
        combat_buttons.addWidget(combat_apply)
        reset = QPushButton('Restaurar ajustes padrão de combate')
        reset.clicked.connect(self.reset_combat)
        combat_buttons.addWidget(reset)
        combat_layout.addLayout(combat_buttons)
        combat_layout.addStretch()
        tabs.addTab(combat, 'Combate')
        from .skill_panel import SkillPanel
        self.skill_panel = SkillPanel()
        self.skill_panel.summon_finished.connect(lambda: self.command('summon_finished'))
        self.skill_panel.apply_requested.connect(self.apply)
        self.skill_panel.probe_requested.connect(lambda identity, level: self.command('probe_buff', skill_id=identity, level=level))
        tabs.addTab(self.skill_panel, 'Habilidades')
        from .priority_panel import PriorityPanel
        self.priority_panel = PriorityPanel()
        self.priority_panel.apply_requested.connect(self.apply)
        from .minimap_overlay import MinimapOverlay
        from .game_overlay import GameOverlay
        self.overlay = MinimapOverlay()
        self.game_overlay = GameOverlay()
        from .game_overlay import QuestCounter
        self.quest_counter = QuestCounter()
        self.priority_panel.capture_requested.connect(self.start_player_selection)
        self.priority_panel.minimap.toggled.connect(lambda checked: self.update_overlay())
        self.priority_panel.release_requested.connect(lambda: self.command('release_player'))
        self.priority_panel.target_requested.connect(lambda identity: self.command('set_player_target', entity_id=identity))
        tabs.addTab(self.priority_panel, 'Prioridade')
        from .monster_panel import MonsterPanel
        self.monster_panel = MonsterPanel()
        tabs.addTab(self.monster_panel, 'Monstros')
        pvp = QWidget()
        pvp_layout = QVBoxLayout(pvp)
        self.pvp_enabled = QCheckBox('Ativar PvP')
        self.pvp_all = QCheckBox('Atacar todos os jogadores visíveis')
        self.pvp_first = QCheckBox('Priorizar jogadores sobre monstros')
        self.pvp_list = QListWidget()
        self.pvp_targets = set()
        self.pvp_rows = None
        for box in (self.pvp_enabled, self.pvp_all, self.pvp_first):
            pvp_layout.addWidget(box)
        pvp_layout.addWidget(QLabel('Jogadores visíveis no mapa atual'))
        pvp_layout.addWidget(self.pvp_list)
        self.pvp_list.itemChanged.connect(self.pvp_target_changed)
        from .x1_panel import X1Box
        self.x1_box = X1Box()
        pvp_layout.addWidget(self.x1_box)
        tabs.addTab(pvp, 'PvP')
        from .player_panel import PlayerPanel
        self.player_panel = PlayerPanel()
        tabs.addTab(self.player_panel, 'Jogadores')
        from .watch_alert import WatchAlert
        self.watch_alert = WatchAlert()
        from .update_panel import UpdatePanel
        self.update_panel = UpdatePanel(relay_running=lambda: self.process.state() != QProcess.NotRunning)
        self.update_panel.restart_requested.connect(self.restart_after_update)
        tabs.addTab(self.update_panel, 'Atualização')
        QTimer.singleShot(1500, lambda: self.update_panel.run('check'))  # tell about new versions on start
        self.strict_map = QCheckBox('Exigir mapa de colisão válido antes de iniciar')
        form.insertRow(0, self.strict_map)
        group_box=QGroupBox('Caca em grupo: lider e seguidores')
        group_form=QFormLayout(group_box)
        self.group_enabled=QCheckBox('Ativar modo de grupo')
        self.group_role=QComboBox();self.group_role.addItem('Seguidor','follower');self.group_role.addItem('Lider','leader')
        self.group_leader=QLineEdit();self.group_leader.setPlaceholderText('Nome exato do lider visivel no jogo')
        self.group_only=QCheckBox('Apenas seguir (seguidor): sem ataques, habilidades ou invocacoes')
        self.group_role.currentIndexChanged.connect(lambda: self.group_only.setEnabled(self.group_role.currentData()=='follower'))
        self.group_distance=QSpinBox();self.group_distance.setRange(2,8)
        self.group_members=QPlainTextEdit();self.group_members.setMaximumHeight(65)
        self.group_members.setPlaceholderText('Nomes dos demais membros, um por linha; nao pausam a caca')
        for label,widget in (('',self.group_enabled),('Papel neste computador',self.group_role),('Lider',self.group_leader),
                            ('',self.group_only),('Distancia em celulas',self.group_distance),('Membros permitidos',self.group_members)):
            group_form.addRow(label,widget)
        note=QLabel('Seguidores usam o caminho e o alvo observado do lider. Se ele sair da visao ou do mapa, aguardam. Todos devem configurar os mesmos alvos de monstros.')
        note.setWordWrap(True);group_form.addRow(note)
        form.insertRow(form.rowCount()-1,group_box)
        keys_box = QGroupBox('Teclas (valem com o jogo em primeiro plano)')
        keys_form = QFormLayout(keys_box)
        from .packet_settings import HOTKEYS
        self.hotkey_hunt, self.hotkey_minimap = QComboBox(), QComboBox()
        for combo in (self.hotkey_hunt, self.hotkey_minimap):
            combo.addItems(list(HOTKEYS))
        keys_form.addRow('Iniciar / parar o bot', self.hotkey_hunt)
        keys_form.addRow('Esconder / mostrar o minimapa', self.hotkey_minimap)
        form.insertRow(form.rowCount()-1, keys_box)
        presence_box = QGroupBox('Pausar o bot quando aparecer')
        presence_layout = QVBoxLayout(presence_box)
        self.pause_players = QCheckBox('Qualquer jogador por perto (até 14 células)')
        self.pause_disguised = QCheckBox('Jogador disfarçado de monstro')
        self.pause_hidden = QCheckBox('Jogador escondido ou em @hide')
        for box in (self.pause_players, self.pause_disguised, self.pause_hidden):
            presence_layout.addWidget(box)
        self.sit_on_players = QCheckBox('Sentar enquanto o bot estiver pausado por um jogador por perto')
        presence_layout.addWidget(self.sit_on_players)
        resume_row = QHBoxLayout()
        resume_row.addWidget(QLabel('Voltar a rodar'))
        self.resume_delay = QSpinBox()
        self.resume_delay.setRange(10, 600)
        self.resume_delay.setSuffix(' s')
        resume_row.addWidget(self.resume_delay)
        resume_row.addWidget(QLabel('depois que o jogador sair da tela'), 1)
        presence_layout.addLayout(resume_row)
        presence_layout.addWidget(QLabel('Jogadores permitidos: um nome por linha. N?o pausam a ca?a.'))
        self.allowed_players = QPlainTextEdit()
        self.allowed_players.setMaximumHeight(95)
        self.allowed_players.setReadOnly(True)
        self.edit_allowed_players = QPushButton('Editar jogadores permitidos')
        self.edit_allowed_players.setCheckable(True)
        self.edit_allowed_players.toggled.connect(self.toggle_allowed_players_edit)
        presence_layout.addWidget(self.edit_allowed_players)
        self.allowed_players.setPlaceholderText('Nome exato do personagem')
        presence_layout.addWidget(self.allowed_players)
        presence_layout.addWidget(QLabel('Jogadores permitidos geram aviso informativo; nao suspendem a caca.'))
        form.insertRow(form.rowCount()-1, presence_box)
        self.advanced = QCheckBox('Combinar habilidades configuradas e buffs por intervalos individuais')
        combat_form.addRow(self.advanced)
        self.auto_attacks = QCheckBox('Ataque básico: vai até o monstro e intercala um ataque básico após cada habilidade '
                                      '(desligado: só habilidades, correndo para manter a distância do alcance delas)')
        combat_form.addRow(self.auto_attacks)
        self.fast_offensives = QCheckBox('Habilidades ofensivas na velocidade máxima (cada uma assim que estiver no '
                                         'alcance e fora do cooldown; o bot aprende o menor intervalo que o servidor aceita)')
        combat_form.addRow(self.fast_offensives)
        burst_row = QHBoxLayout()
        self.skill_burst = QCheckBox('Rajada: enviar todas as ofensivas no alcance, uma a cada')
        burst_row.addWidget(self.skill_burst)
        self.burst_interval = QDoubleSpinBox()
        self.burst_interval.setRange(.05, 1)
        self.burst_interval.setDecimals(2)
        self.burst_interval.setSingleStep(.05)
        self.burst_interval.setSuffix(' s')
        burst_row.addWidget(self.burst_interval)
        burst_row.addWidget(QLabel('sem esperar resposta do servidor'), 1)
        combat_form.addRow(burst_row)
        burst_note = QLabel('Na rajada, só o cooldown informado pelo servidor, o alcance de cada habilidade e o SP '
                            'seguram o envio. Pedidos que chegarem durante o delay do servidor são descartados por ele.')
        burst_note.setWordWrap(True)
        combat_form.addRow(burst_note)
        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        self.details = QLabel('Aguardando conexão')
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        overview_layout.addWidget(self.details)
        overview_layout.addStretch()
        tabs.addTab(overview, 'Estado da caça')
        self.entities = QTableWidget(0, 7)
        self.entities.setHorizontalHeaderLabels(['ID', 'Espécie / nome', 'Aparência', 'Posição', 'Destino', 'Idade (s)', 'Presença observada'])
        self.entities.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.entities.setEditTriggers(QTableWidget.NoEditTriggers)
        tabs.addTab(self.entities, 'Aparições recebidas')
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1200)
        tabs.addTab(self.log, 'Diagnóstico')
        from .quest_panel import QuestPanel
        self.quest_panel=QuestPanel()
        self.quest_panel.command_requested.connect(lambda command,values:self.command(command,**values))
        tabs.addTab(self.quest_panel,'Rota de quests')
        self.notice = QLabel('Home inicia/pausa • Alt+Tab mantém a caça')
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        layout.addWidget(QLabel('Fechar este painel ou encerrar a conexão desconecta o jogo ligado a este relay.'))
        try:
            settings = read()
        except (OSError, ValueError) as exc:
            self.notice.setText('Configuração inválida: '+str(exc))
            settings = DEFAULTS.copy()
        self.targets.selected = set(settings['species'])
        self.targets.name_choices = dict(settings['monster_name_choices'])
        self.targets.shown = ()
        self.auto_map_targets.setChecked(settings['auto_map_targets'])
        self.radius.setValue(settings['radius'])
        self.step.setValue(settings['patrol_step'])
        self.patrol_spacing.setValue(settings.get('patrol_spacing', 14))
        self.patrol_coverage.setValue(settings.get('patrol_coverage', 90))
        self.patrol_wall_margin.setValue(settings.get('patrol_wall_margin', 3))
        self.patrol_avoid_walls.setChecked(settings.get('patrol_avoid_walls', True))
        self.patrol_give_up.setValue(settings.get('patrol_give_up', 10))
        self.ignore_attackers.setValue(settings.get('ignore_attackers', 0))
        self.patrol.setChecked(settings['patrol'])
        self.auto_movement.setChecked(settings['auto_movement'])
        self.manual_movement.setChecked(settings.get('manual_movement', False))
        self.pvp_enabled.setChecked(settings['pvp_enabled'])
        self.pvp_all.setChecked(settings['pvp_all'])
        self.pvp_first.setChecked(settings['pvp_first'])
        self.pvp_targets = set(settings['pvp_targets'])
        self.pvp_rows = None
        self.skills.setChecked(settings['skills'])
        self.strict_map.setChecked(settings['require_collision'])
        self.advanced.setChecked(settings['advanced_combat'])
        self.auto_attacks.setChecked(settings['auto_attacks'])
        self.fast_offensives.setChecked(settings['fast_offensives'])
        self.hotkey_hunt.setCurrentText(settings['hotkey_hunt'])
        self.hotkey_minimap.setCurrentText(settings['hotkey_minimap'])
        self.sit_on_players.setChecked(settings['sit_on_players'])
        self.resume_delay.setValue(settings['resume_delay'])
        self.allowed_players.setPlainText('\n'.join(settings['allowed_players']))
        self.limit_failures.setChecked(settings['limit_target_failures'])
        self.defer_failed.setChecked(settings['defer_failed_targets'])
        self.skill_burst.setChecked(settings['skill_burst'])
        self.burst_interval.setValue(settings['skill_burst_interval'])
        self.update_key_notice()
        self.pause_players.setChecked(settings['pause_on_players'])
        self.group_enabled.setChecked(settings['group_enabled'])
        self.group_role.setCurrentIndex(self.group_role.findData(settings['group_role']))
        self.group_leader.setText(settings['group_leader'])
        self.group_only.setChecked(settings['group_follow_only'])
        self.group_distance.setValue(settings['group_distance'])
        self.group_members.setPlainText('\n'.join(settings['group_members']))
        self.pause_disguised.setChecked(settings['pause_on_disguised'])
        self.pause_hidden.setChecked(settings['pause_on_hidden'])
        self.skill_panel.saved = settings['skill_profiles']
        self.skill_panel.summon_queue_mode = settings['summon_queue_mode']
        self.priority_panel.saved = settings['skill_priority']
        for key, field in self.combat_fields.items():
            field.setValue(settings[key])
        from .responsive_ui import PanelLayout
        self.responsive_layout = PanelLayout(self, locals())
        self.watch_settings()
        self.load_ui()
        self.responsive_layout.fit_to_screen()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(700)
        self.overlay_timer = QTimer(self)
        self.overlay_timer.timeout.connect(self.refresh_overlays)
        self.overlay_timer.start(100)
        tabs.currentChanged.connect(lambda index: self.refresh())

    def settings(self):
        return {'group_enabled':self.group_enabled.isChecked(),'group_role':self.group_role.currentData(),
                'group_leader':self.group_leader.text().strip(),'group_follow_only':self.group_only.isChecked(),
                'group_distance':self.group_distance.value(),'group_members':[n.strip() for n in self.group_members.toPlainText().splitlines() if n.strip()],
                'species': sorted(self.targets.selected), 'monster_name_choices': dict(self.targets.name_choices),
                'radius': self.radius.value(), 'patrol_step': self.step.value(),
                'patrol_spacing': self.patrol_spacing.value(), 'patrol_coverage': self.patrol_coverage.value(),
                'patrol_wall_margin': self.patrol_wall_margin.value(), 'patrol_avoid_walls': self.patrol_avoid_walls.isChecked(),
                'patrol_give_up': self.patrol_give_up.value(), 'ignore_attackers': self.ignore_attackers.value(),
                'patrol': self.patrol.isChecked(), 'skills': self.skills.isChecked(), 'auto_map_targets': self.auto_map_targets.isChecked(),
                'require_collision': self.strict_map.isChecked(), 'auto_movement': self.auto_movement.isChecked(),
                'manual_movement': self.manual_movement.isChecked(),
                'pvp_enabled': self.pvp_enabled.isChecked(), 'pvp_all': self.pvp_all.isChecked(),
                'pvp_first': self.pvp_first.isChecked(), 'pvp_targets': sorted(self.pvp_targets), 'advanced_combat': self.advanced.isChecked(),
                'auto_attacks': self.auto_attacks.isChecked(), 'skill_profiles': self.skill_panel.profiles(),
                'skill_priority': self.priority_panel.priority(),
                'summon_queue_mode': self.skill_panel.summon_queue_mode,
                'pause_on_players': self.pause_players.isChecked(), 'pause_on_disguised': self.pause_disguised.isChecked(),
                'pause_on_hidden': self.pause_hidden.isChecked(), 'fast_offensives': self.fast_offensives.isChecked(),
                'hotkey_hunt': self.hotkey_hunt.currentText(), 'hotkey_minimap': self.hotkey_minimap.currentText(),
                'allowed_players': [n.strip() for n in self.allowed_players.toPlainText().splitlines() if n.strip()],
                'sit_on_players': self.sit_on_players.isChecked(), 'resume_delay': self.resume_delay.value(),
                'limit_target_failures': self.limit_failures.isChecked(),
                'defer_failed_targets': self.defer_failed.isChecked(),
                'skill_burst': self.skill_burst.isChecked(), 'skill_burst_interval': self.burst_interval.value(),
                **{key: field.value() for key, field in self.combat_fields.items()}}

    def reset_combat(self):
        for key, field in self.combat_fields.items():
            field.setValue(DEFAULTS[key])
        self.advanced.setChecked(DEFAULTS['advanced_combat'])
        self.auto_attacks.setChecked(DEFAULTS['auto_attacks'])
        self.notice.setText('Padrões de combate restaurados na edição. Clique em Salvar e aplicar para usá-los.')

    def apply(self):
        try:
            settings = save(self.settings())
            self.skill_panel.saved = settings['skill_profiles']
            if self.process.state() != QProcess.NotRunning:
                self.command('apply', settings=settings)
            else:
                self.notice.setText('Configuração salva para a próxima conexão.')
        except (OSError, ValueError) as exc:
            self.notice.setText(str(exc))

    def show_game_folder(self, folder=None):
        from .game_folder import find
        folder = folder or find()
        if folder:
            self.game_field.setText(str(folder))
            self.game_label.setText('encontrada')
            self.game_label.setStyleSheet('color:#2e9e4f;font-weight:600')
        else:
            self.game_label.setText('não encontrada')
            self.game_label.setStyleSheet('color:#d33;font-weight:600')
        return folder

    def save_game_field(self):
        """Save the folder pasted in the field; returns it or None."""
        from .game_folder import save as save_game
        text = self.game_field.text()
        if not text.strip():
            self.notice.setText('Cole o caminho da pasta do jogo no campo "Pasta do jogo".')
            self.game_field.setFocus()
            return None
        try:
            folder = save_game(text)
        except ValueError as exc:
            self.game_label.setText('pasta inválida')
            self.game_label.setStyleSheet('color:#d33;font-weight:600')
            self.notice.setText(str(exc))
            return None
        self.notice.setText(f'Pasta do jogo salva: {folder}')
        return self.show_game_folder(folder)

    def choose_game_folder(self):
        """Pick the game folder in a dialog; returns it or None."""
        from PySide6.QtWidgets import QFileDialog
        chosen = QFileDialog.getExistingDirectory(self, 'Escolha a pasta do jogo NRO (a que tem DATA.INI)')
        if not chosen:
            return None
        self.game_field.setText(chosen)
        return self.save_game_field()

    def open_relay(self):
        if self.process.state() != QProcess.NotRunning:
            return
        from .game_folder import saved
        pasted = self.game_field.text().strip()
        if pasted and (saved() is None or Path(pasted.strip('"')) != saved()):
            game = self.save_game_field()  # a path pasted but not saved yet
        else:
            game = self.show_game_folder()
        if game is None:
            self.notice.setText('Cole o caminho da pasta do jogo (a que tem DATA.INI) no campo "Pasta do jogo" e clique Salvar.')
            self.game_field.setFocus()
            return
        try:
            save(self.settings())
            self.session = ROOT/'logs/relay'/datetime.now().strftime('%Y%m%d-%H%M%S-%f-painel')
            self.session.mkdir(parents=True)
            self.pending_command = None
            self.log.clear()
            self.process.start(sys.executable, ['-u', '-m', 'nrobot.session_relay', '--hunt', '--session-dir', str(self.session),
                                                '--game-dir', str(game)])
            self.open_button.setEnabled(False)
            self.notice.setText('Entre no jogo por NRO - BOT LOCAL (TESTE), depois clique em Iniciar.')
            self.start_auto_login(game)
        except (OSError, ValueError) as exc:
            self.notice.setText(str(exc))

    # -- login automatico ------------------------------------------------------------------
    def build_auto_login(self, layout):
        from . import auto_login
        from PySide6.QtWidgets import QLineEdit as Line, QSpinBox as Spin, QGroupBox as Group, QGridLayout
        config = auto_login.load()
        box = Group('Login automático'); grid = QGridLayout(box)
        self.login_enabled = QCheckBox('Ativar: ao abrir a conexão, abre o jogo (se fechado), entra na conta e escolhe o personagem')
        self.login_enabled.setChecked(config['enabled'])
        self.login_user = Line(config['user']); self.login_user.setPlaceholderText('Login da conta')
        self.login_password = Line(); self.login_password.setEchoMode(Line.Password)
        self.login_password.setPlaceholderText('senha salva (protegida pelo Windows)' if config['password'] else 'Senha')
        self.login_character = Line(config['character']); self.login_character.setPlaceholderText('Nome do personagem')
        self.login_server = Spin(); self.login_server.setRange(1, 10); self.login_server.setValue(config['server_index'])
        self.login_when_open = QCheckBox('Digitar com o jogo já aberto (só se ele estiver na tela de login)')
        self.login_when_open.setChecked(config.get('type_when_open', False))
        self.login_wait = Spin(); self.login_wait.setRange(3, 60); self.login_wait.setSuffix(' s'); self.login_wait.setValue(config['login_wait'])
        self.login_wait.setToolTip('Espera depois de abrir o jogo até a tela de login aparecer')
        self.login_server.setToolTip('Posição do servidor "NRO - BOT LOCAL" na lista de servidores do jogo')
        save_login = QPushButton('Salvar login'); save_login.clicked.connect(self.save_auto_login)
        grid.addWidget(self.login_enabled, 0, 0, 1, 6)
        for column, (title, widget) in enumerate((('Login', self.login_user), ('Senha', self.login_password),
                                                  ('Personagem', self.login_character), ('Servidor nº', self.login_server))):
            grid.addWidget(QLabel(title), 1, column*2 if column < 2 else column*2); grid.addWidget(widget, 1, column*2+1)
        grid.addWidget(self.login_when_open, 2, 0, 1, 4)
        grid.addWidget(QLabel('Espera da tela de login'), 2, 4); grid.addWidget(self.login_wait, 2, 5)
        grid.addWidget(save_login, 2, 7)
        layout.addWidget(box)

    def save_auto_login(self):
        from . import auto_login
        config = auto_login.load()
        try:
            if self.login_password.text():
                config['password'] = auto_login.protect(self.login_password.text())
        except OSError as exc:
            self.notice.setText(str(exc)); return
        config.update(enabled=self.login_enabled.isChecked(), user=self.login_user.text().strip(),
                      character=self.login_character.text().strip(), server_index=self.login_server.value(),
                      type_when_open=self.login_when_open.isChecked(), login_wait=self.login_wait.value())
        auto_login.save(config)
        self.login_password.clear(); self.login_password.setPlaceholderText('senha salva (protegida pelo Windows)' if config['password'] else 'Senha')
        self.notice.setText('Login automático salvo.' if config['enabled'] else 'Login automático desligado.')

    def start_auto_login(self, game):
        """Opens the game when closed and types the login there; an open game is left alone (the
        bot never types into a game it did not open: it could be in chat)."""
        from . import auto_login
        import threading
        config = auto_login.load()
        if not config['enabled']:
            return
        try:
            opened = auto_login.launch_game(game)
        except OSError as exc:
            self.notice.setText('Login automático: '+str(exc)); return
        if not opened and not config.get('type_when_open'):
            self.notice.setText('Jogo já aberto: entre na conta pelo NRO - BOT LOCAL; o personagem '
                                +(config['character'] or '')+' é escolhido sozinho. Para digitar também com o jogo '
                                'aberto, marque "Digitar com o jogo já aberto".')
            return
        if not config['user'] or not config['password']:
            self.notice.setText('Login automático: salve login e senha primeiro.'); return
        self.notice.setText('Abrindo o jogo para o login automático...' if opened else 'Login automático: digitando no jogo aberto...')
        messages = self.login_messages = []

        def run():
            report = messages.append
            if auto_login.wait_game_window() is None:
                report('Login automático: a janela do jogo não apareceu em 90 s.'); return
            if opened:
                report(f"Login automático: jogo aberto; aguardando {config['login_wait']} s a tela de login.")
                time.sleep(config['login_wait'])
            try:
                auto_login.log_in(config, report)
            except OSError as exc:
                report('Login automático: '+str(exc))
        threading.Thread(target=run, daemon=True).start()

    def show_login_messages(self):
        """The login runs in the background: its steps show in Diagnóstico and on the notice line."""
        messages = getattr(self, 'login_messages', None)
        while messages:
            text = messages.pop(0)
            self.log.appendPlainText(text)
            self.notice.setText(text)

    def command(self, command, **values):
        if self.process.state() == QProcess.NotRunning or self.session is None:
            self.notice.setText('Abra a conexão primeiro.')
            return
        if self.pending_command and command not in ('pause', 'stop'):
            self.notice.setText('Aguardando confirmação do comando anterior.')
            return
        try:
            request = {'id': uuid.uuid4().hex, 'command': command, **values}
            temp = self.session/'comando.tmp'
            temp.write_text(json.dumps(request), encoding='utf-8')
            temp.replace(self.session/'comando.json')
            self.pending_command = request['id']
            self.notice.setText('Aguardando confirmação: '+command)
        except OSError as exc:
            self.notice.setText(str(exc))

    def read_output(self):
        text = bytes(self.process.readAllStandardOutput()).decode('utf-8', 'replace')
        for line in text.rstrip().splitlines():
            if line.startswith('[ALERTA]'):
                self.log.appendHtml(f'<span style="color:#ff3b3b;font-weight:600">{html.escape(line)}</span>')
            else:
                self.log.appendHtml(f'<span>{html.escape(line)}</span>')
        if self.session is not None:
            try:
                with (self.session/'saida_relay.log').open('a', encoding='utf-8') as log:
                    log.write(text)
            except OSError:
                pass

    def finished(self, *args):
        self.overlay.hide()
        self.game_overlay.hide()
        self.quest_counter.hide()
        self.open_button.setEnabled(True)
        self.pending_command = None
        self.status_label.setText('Conexão encerrada')
        self.notice.setText('Conexão encerrada. Se a abertura falhou, consulte a aba Diagnóstico (verifique se outro relay está aberto).')

    def process_error(self, error):
        self.notice.setText('Não foi possível executar o relay: '+self.process.errorString())
        if self.process.state() == QProcess.NotRunning:
            self.open_button.setEnabled(True)

    def close_relay(self):
        if self.process.state() != QProcess.NotRunning:
            # The venv python.exe is a launcher: the relay runs in its child process, which
            # would survive and keep port 16900 busy. End the whole process tree.
            pid = self.process.processId()
            if pid and sys.platform == 'win32':
                import subprocess
                subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            else:
                self.process.terminate()
            if not self.process.waitForFinished(1500):
                self.process.kill()
                self.process.waitForFinished(500)

    def pvp_target_changed(self, item):
        identity = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            self.pvp_targets.add(identity)
        else:
            self.pvp_targets.discard(identity)
        self.schedule_save()

    def refresh_pvp(self, players):
        rows = [(row['entity_id'], row.get('name')) for row in players]
        if rows == self.pvp_rows:
            return
        self.pvp_rows = rows
        self.pvp_list.blockSignals(True)
        self.pvp_list.clear()
        for identity, name in rows:
            item = QListWidgetItem(f'{name or "Jogador"} (ID {identity})', self.pvp_list)
            item.setData(Qt.UserRole, identity)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if identity in self.pvp_targets else Qt.Unchecked)
        self.pvp_list.blockSignals(False)

    def refresh(self):
        if self.session is None or self.process.state() == QProcess.NotRunning:
            self.refresh_pvp([])
            if self.player_panel.isVisible():
                self.player_panel.update_state({})  # the history stays readable offline
            return
        try:
            state = json.loads((self.session/'estado.json').read_text(encoding='utf-8'))
            hunt = state.get('hunt', {})
            self.targets.show_map(state.get('map_name'), {m['species_id']: m for m in state.get('map_monsters', [])},
                                  variants=state.get('map_monster_names', []))
            self.refresh_pvp(state.get('players_nearby', []))
            self.player_panel.check_watch(state)  # status line of the lista de observação
            self.x1_box.set_character((state.get('own_look') or {}).get('name'))
            # The relay stops itself on a watched character or anyone in @hide; this shows it.
            emergency = state.get('emergency_stop')
            if emergency and emergency['id'] != getattr(self, 'emergency_seen', None):
                self.emergency_seen = emergency['id']
                if not emergency.get('released'):
                    self.watch_alert.show_alert(emergency['detections'], stopped=emergency['reason'])
                    self.log.appendPlainText(f"[PARADA] {emergency['at']}: {emergency['reason']}")
            if self.monster_panel.isVisible():
                self.monster_panel.reload()

            if self.skill_panel.isVisible():
                self.skill_panel.update_catalog(state.get('learned_skills', []), state.get('own_effects', {}), state.get('buff_candidates', {}), state.get('rotation'))
            self.skill_panel.receive_buff_learning(state.get('buff_learning_result'))
            self.quest_panel.update_state(state)
            self.last_state = state
            self.update_overlay()
            if self.priority_panel.isVisible():
                names = {skill['skill_id']: self.skill_panel.local_names.get(skill.get('name'), skill.get('name'))
                         for skill in state.get('learned_skills', [])}
                self.priority_panel.sync(self.skill_panel.profiles(), names)
                self.priority_panel.update_targets(state)
            result = state.get('control_result') or {}
            if result.get('id') == self.pending_command and self.pending_command:
                self.notice.setText(result['message'])
                self.pending_command = None
            stage = {'waiting_login': 'Aguardando login', 'map': 'Personagem conectado',
                     'login': 'Conectando login', 'char': 'Seleção de personagem',
                     'map_disconnected': 'Personagem desconectado', 'stopped': 'Encerrado'}.get(state['stage'], state['stage'])
            self.status_label.setText(f"{stage} • {'Caça ativa' if hunt.get('enabled') else 'Caça pausada'} • Mapa: {state.get('map_name') or '—'}")
            quest=state.get('quests',{})
            if quest.get('phase') in ('pickup','travel','hunt','delivery','return'):
                phase={'pickup':'Pegando quests','travel':'Viajando','hunt':'Matando monstros','delivery':'Entregando quests','return':'Retornando ao ponto salvo'}[quest['phase']]
                self.status_label.setText(f"{stage} • {phase}: {quest.get('quest') or ''} • Mapa: {state.get('map_name') or '—'}")
            if (datetime.now()-datetime.fromisoformat(state['updated_at'])).total_seconds() > 5:
                self.status_label.setText('Sem atualização recente do relay • verifique Diagnóstico ou encerre a conexão')
            if state.get('native_frame_error'):
                self.status_label.setText('Ca?a bloqueada ? '+state['native_frame_error']+'; reconecte o personagem ap?s atualizar o painel')
            binding = state.get('f2_binding')
            f2_description = 'ainda não recebido'
            if binding:
                level = str(binding['level']) if binding['level'] else 'não informado (0)'
                label = 'Arremessar Kunai' if binding['id'] == 524 and binding['type_raw'] == 1 else f"ID {binding['id']} (tipo {binding['type_raw']})"
                learned = next((skill['level'] for skill in state.get('learned_skills', []) if skill['skill_id'] == 524), 'não recebido')
                f2_description = f"{label}, nível no atalho: {level}. "+('Rotação usa os perfis da aba Habilidades.' if state.get('rotation') is not None else f'Bot: Kunai nível 10; nível aprendido: {learned}')
            sync = state.get('character_sync', {})
            self.details.setText('\n\n'.join([
                f"Posição: {state.get('player_position') or '—'}     SP: {state['player_sp'] if state.get('player_sp') is not None else '—'}     Alvo: {hunt.get('target_id') or '—'}",
                'Alvo em combate: '+(f"{state['combat_target']['name']} • {state['combat_target']['distance']} células • posição {state['combat_target']['position']}"+
                                      (' (posição estimada)' if state['combat_target'].get('position_estimated', state['combat_target']['arrival_estimated']) else '') if state.get('combat_target') else 'nenhum'),
                'Posicao do alvo recebida: '+str((state.get('combat_target') or {}).get('last_received_position', '-'))+
                    ' | Destino anunciado: '+str((state.get('combat_target') or {}).get('announced_destination', '-')),
                'Dados iniciais: lista de habilidades '+('recebida' if sync.get('skills_received') else 'ainda nao recebida')+
                    '; SP '+('recebido' if sync.get('sp_received') else 'ainda nao recebido')+
                    '; identidade '+('recebida' if sync.get('identity_received') else 'ainda nao recebida'),
                f"Ataques confirmados: {hunt.get('confirmed_attacks', 0)}     Habilidades ofensivas confirmadas: {hunt.get('confirmed_skills', 0)}",
                f"Candidatos recentes: {len(state.get('recent_entities', []))}     Mensagens recebidas: {state.get('messages', 0)}",
                'Grupo: '+str((state.get('group') or {}).get('reason') or 'modo normal/lider')+
                    (' | apenas seguir' if (state.get('group') or {}).get('follow_only') else ''),
                'Fase: '+hunt.get('phase', 'aguardando')+f" • Espera atual: {hunt.get('wait_seconds', 0)} s",
                'Motivo: '+(hunt.get('reason') or 'nenhum bloqueio global'),
                f"Falhas no alvo atual: {hunt.get('target_skill_failures', 0)} • Ajustes aplicados: "+self.applied_combat_text(state.get('settings') or {}),
                'Última decisão: '+self.decision_text(hunt.get('last_decision')),
                'Patrulha: '+(f"{hunt['patrol']['visited_sectors']} setores registrados • {hunt['patrol']['completed_steps']} trechos concluídos • {hunt['patrol'].get('loop_escapes', 0)} saídas de repetição" if hunt.get('patrol') else 'desativada'),
                'Ciclo de exploracao: '+str((hunt.get('patrol') or {}).get('cycle', 1))+' | setores: '+str((hunt.get('patrol') or {}).get('cycle_sectors_explored', (hunt.get('patrol') or {}).get('cycle_sectors_visited', 0)))+'/'+str((hunt.get('patrol') or {}).get('cycle_sectors_total', 0)),
                'Navegação: '+hunt.get('navigation', 'aguardando'),
                'Mapa validado: '+(f"{state['map_validation']['width']} × {state['map_validation']['height']} células • {state['map_validation']['reachable_cells']} alcançáveis" if state.get('map_validation') else 'aguardando início'),
                'Rotação: '+str((state.get('rotation') or {}).get('reason', 'modo simples'))+
                f" • Buffs confirmados: {(state.get('rotation') or {}).get('confirmed_buffs', 0)}",
                'Habilidades: '+hunt.get('skill_reason', 'desativadas'),
                'Memoria do mapa: '+str((state.get('map_search') or {}).get('received_species_entities', 0))+' monstros recebidos; destino de busca: '+str((state.get('map_search') or {}).get('goal') or 'explorando areas sem dados'),
                'Municao: '+str((state.get('ammo') or {}).get('reason', 'aguardando'))+' | '+', '.join(str(v.get('name'))+': '+str(v.get('amount'))+(' (equipada)' if v.get('ready') else '') for v in (state.get('ammo') or {}).get('options', {}).values()),
                'F2 recebido do servidor: '+f2_description,
                'Erro da conexão: '+str(state.get('relay_error') or state.get('native_frame_error') or state.get('reason') or 'nenhum'),
                'Registros: '+str(self.session)]))
            if self.entities.isVisible():
                self.refresh_entities()
        except (OSError, ValueError, KeyError):
            pass  # A session file may not exist yet during startup.

    def refresh_entities(self):
        rows = json.loads((self.session/'entidades_mapa.json').read_text(encoding='utf-8'))['entities']
        self.entities.setUpdatesEnabled(False)
        try:
            self.entities.setRowCount(len(rows))
            for row, entity in enumerate(rows):
                values = [entity['entity_id'], entity.get('correlated_name') or entity.get('name') or 'Não identificada',
                          entity['species_id'], entity['position'], entity.get('destination'), entity['position_age_seconds'],
                          'Sim (último registro)' if entity['present_last_observation'] else 'Removida']
                for column, value in enumerate(values):
                    text = str(value)
                    item = self.entities.item(row, column)
                    if item is None:
                        self.entities.setItem(row, column, QTableWidgetItem(text))
                    elif item.text() != text:
                        item.setText(text)
        finally:
            self.entities.setUpdatesEnabled(True)

    @staticmethod
    def applied_combat_text(settings):
        if 'skill_interval' not in settings:
            return 'aguardando versão atualizada do relay'
        return f"Intervalo padrão {settings['skill_interval']} s; resposta {settings['skill_timeout']} s; {settings['skill_attempts']} falhas; adiamento {settings['target_defer']} s"

    @staticmethod
    def decision_text(event):
        if not event:
            return 'nenhuma'
        if event['kind'] == 'target_switched':
            return f"Alvo {event['previous_target']} ({event['previous_distance']} células) trocado por {event['target_id']} ({event['distance']} células)"
        if event['kind'] == 'skill_confirmed':
            return f"Habilidade confirmada no alvo {event['target_id']}, dano {event.get('damage_raw')}"
        return f"Alvo {event.get('target_id', '—')}: {event.get('reason', event['kind'])}"

    def refresh_overlays(self):
        """10 Hz state for the in-game drawings; the dashboard keeps its own slower refresh."""
        self.check_minimap_key()
        self.show_login_messages()
        if self.session is None or self.process.state() == QProcess.NotRunning:
            return
        if not (self.game_overlay.isVisible() or self.overlay.isVisible() or self.quest_counter.isVisible() or self.priority_panel.minimap.isChecked()):
            return
        try:
            self.last_state = json.loads((self.session/'estado.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        self.update_overlay()

    def start_player_selection(self):
        """REDE-76: capture with the game's own mouse: the relay watches the next targeting packets."""
        if self.session is None or self.process.state() == QProcess.NotRunning:
            self.notice.setText('Abra a conexão e entre no personagem antes de capturar um jogador.')
            return
        from .radar_overlay import bring_game_to_front
        self.command('capture_player')
        bring_game_to_front()
        self.notice.setText('Captura armada por 20 s: passe o mouse do jogo sobre o jogador (ou clique nele).')

    def update_overlay(self):
        state = getattr(self, 'last_state', {}) if self.process.state() != QProcess.NotRunning else {}
        from .radar_overlay import game_in_front
        front = game_in_front()  # minimized or Alt+Tab: every overlay hides with the game
        if bool(state) and self.priority_panel.minimap.isChecked() and front:
            self.overlay.update_state(state)
            if self.session is not None:
                self.overlay.load(self.session)
            self.overlay.follow_game()
            if not self.overlay.isVisible():
                self.overlay.show()
        elif self.overlay.isVisible():
            self.overlay.hide()
        # Shadow on the own character while hidden; other hidden characters are on the minimap.
        self.game_overlay.update_state(state)
        if self.game_overlay.has_content() and front:
            self.game_overlay.follow_game()
            if not self.game_overlay.isVisible():
                self.game_overlay.show()
        elif self.game_overlay.isVisible():
            self.game_overlay.hide()
        # Quest kill counter: its own window, dragged apart from the minimap.
        self.quest_counter.update_state(state)
        if self.quest_counter.has_content() and front and self.quest_counter.follow_game():
            if not self.quest_counter.isVisible():
                self.quest_counter.show()
        elif self.quest_counter.isVisible():
            self.quest_counter.hide()

    def restart_after_update(self):
        from .updater import restart_panel
        restart_panel()
        self.close()

    # -- automatic saving (REDE-78) -----------------------------------------------------
    def toggle_allowed_players_edit(self, editing):
        self.allowed_players.setReadOnly(not editing)
        self.edit_allowed_players.setText('Concluir e bloquear lista' if editing else 'Editar jogadores permitidos')
        if editing:
            self.allowed_players.setFocus()
        else:
            self.schedule_save()

    def watch_settings(self):
        """Every edit is saved by itself; no button needed to keep the configuration."""
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(800)
        self.save_timer.timeout.connect(self.autosave)
        self.allowed_players.textChanged.connect(self.schedule_save)
        self.group_enabled.toggled.connect(self.schedule_save)
        self.group_role.currentIndexChanged.connect(self.schedule_save)
        self.group_leader.editingFinished.connect(self.schedule_save)
        self.group_only.toggled.connect(self.schedule_save)
        self.group_distance.valueChanged.connect(self.schedule_save)
        self.group_members.textChanged.connect(self.schedule_save)
        self.targets.changed.connect(self.schedule_save)
        for combo in (self.hotkey_hunt, self.hotkey_minimap):
            combo.currentTextChanged.connect(self.schedule_save)
            combo.currentTextChanged.connect(lambda text: self.update_key_notice())
        for field in (self.resume_delay, self.burst_interval):
            field.valueChanged.connect(self.schedule_save)
        for box in (self.pvp_enabled, self.pvp_all, self.pvp_first, self.auto_map_targets, self.auto_movement, self.manual_movement, self.patrol, self.patrol_avoid_walls, self.skills, self.strict_map, self.fast_offensives,
                    self.sit_on_players, self.limit_failures, self.defer_failed, self.skill_burst,
                    self.advanced, self.auto_attacks, self.pause_players, self.pause_disguised, self.pause_hidden):
            box.toggled.connect(self.schedule_save)
        for field in (self.radius, self.step, self.patrol_spacing, self.patrol_coverage, self.patrol_wall_margin, self.patrol_give_up,
                      self.ignore_attackers, *self.combat_fields.values()):
            field.valueChanged.connect(self.schedule_save)
        self.skill_panel.changed.connect(self.schedule_save)
        self.priority_panel.changed.connect(self.schedule_save)
        self.priority_panel.minimap.toggled.connect(lambda checked: self.save_ui())
        self.overlay.on_change = self.save_ui
        self.quest_counter.on_change = self.save_ui
        self.overlay.on_hover = self.quest_counter.on_hover = self.cursor_over_overlay

    def update_key_notice(self):
        self.notice.setText(f'{self.hotkey_hunt.currentText()} inicia/pausa • {self.hotkey_minimap.currentText()} '
                            'esconde/mostra o minimapa • Alt+Tab mantém a caça')

    def check_minimap_key(self):
        """REDE-82: the minimap key toggles it while the game (or this panel) is in front."""
        if sys.platform != 'win32':
            return
        import ctypes
        from .packet_settings import HOTKEYS
        from .radar_overlay import find_game_window
        down = bool(ctypes.windll.user32.GetAsyncKeyState(HOTKEYS[self.hotkey_minimap.currentText()]) & 0x8000)
        was, self.minimap_key_down = getattr(self, 'minimap_key_down', False), down
        if not down or was:
            return
        front = ctypes.windll.user32.GetForegroundWindow()
        if front in (find_game_window(), int(self.winId())):
            self.priority_panel.minimap.setChecked(not self.priority_panel.minimap.isChecked())

    def schedule_save(self, *args):
        self.save_timer.start()

    def autosave(self):
        try:
            settings = save(self.settings())
        except (OSError, ValueError) as exc:
            self.notice.setText('Configuração não salva: '+str(exc))
            return
        self.skill_panel.saved = settings['skill_profiles']
        self.skill_panel.summon_queue_mode = settings['summon_queue_mode']
        self.priority_panel.saved = settings['skill_priority']
        if self.process.state() != QProcess.NotRunning and self.session is not None:
            if self.pending_command:
                self.save_timer.start()  # apply once the previous command is answered
                return
            self.command('apply', settings=settings)
        self.notice.setText('Configuração salva automaticamente.')

    UI_FILE = ROOT/'perfis'/'painel_ui.json'

    def load_ui(self):
        try:
            ui = json.loads(self.UI_FILE.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        from PySide6.QtCore import QByteArray
        if ui.get('geometry'):
            self.restoreGeometry(QByteArray.fromBase64(ui['geometry'].encode('ascii')))
        if isinstance(ui.get('tab'), int) and 0 <= ui['tab'] < self.tabs.count():
            self.tabs.setCurrentIndex(ui['tab'])
        if ui.get('last_map'):
            self.targets.show_map(ui['last_map'])  # until connected, the last map visited
        if 'minimap' in ui:
            self.priority_panel.minimap.setChecked(bool(ui['minimap']))
        try:
            self.overlay.restore_layout(ui.get('minimap_layout'))
            self.quest_counter.restore_layout(ui.get('counter_layout'))
        except (TypeError, ValueError):
            pass

    def cursor_over_overlay(self, inside):
        """The game reads the mouse even over the bot's windows: while the cursor is on the minimap
        or the counter, the relay drops the game's walk/attack/NPC clicks, so dragging them never
        moves the character."""
        if self.session is None:
            return
        flag = self.session/'cursor_sobre_janela'
        try:
            if inside:
                flag.write_text('1', encoding='ascii')
            elif flag.exists():
                flag.unlink()
        except OSError:
            pass

    def save_ui(self):
        ui = {'geometry': bytes(self.saveGeometry().toBase64()).decode('ascii'), 'tab': self.tabs.currentIndex(),
              'minimap': self.priority_panel.minimap.isChecked(), 'minimap_layout': self.overlay.layout_state(),
              'counter_layout': self.quest_counter.layout_state(),
              'last_map': self.targets.map_name}
        try:
            self.UI_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.UI_FILE.write_text(json.dumps(ui), encoding='utf-8')
        except OSError:
            pass

    def closeEvent(self, event):
        if self.save_timer.isActive():
            self.save_timer.stop()
            self.autosave()
        self.save_ui()
        self.overlay.close()
        self.game_overlay.close()
        self.quest_counter.close()
        self.close_relay()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = PacketPanel()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
