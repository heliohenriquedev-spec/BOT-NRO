"""REDE-37: local dashboard for the packet relay; no game input simulation."""
from datetime import datetime
import html
import json
from pathlib import Path
import sys
import uuid

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QSpinBox, QDoubleSpinBox, QFormLayout, QGroupBox, QPlainTextEdit,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QScrollArea)

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
        self.auto_map_targets.setToolTip('No modo automatico, os monstros confirmados do mapa sao incluidos. Para escolher especies manualmente, desative esta opcao.')
        from .monster_panel import MapTargets
        self.targets = MapTargets()  # REDE-79: only the monsters of the current map
        species_layout.addWidget(self.targets, 1)
        self.auto_map_targets.toggled.connect(lambda enabled: self.targets.setEnabled(not enabled))
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
        self.priority_panel.capture_requested.connect(self.start_player_selection)
        self.priority_panel.minimap.toggled.connect(lambda checked: self.update_overlay())
        self.priority_panel.release_requested.connect(lambda: self.command('release_player'))
        self.priority_panel.target_requested.connect(lambda identity: self.command('set_player_target', entity_id=identity))
        tabs.addTab(self.priority_panel, 'Prioridade')
        from .monster_panel import MonsterPanel
        self.monster_panel = MonsterPanel()
        tabs.addTab(self.monster_panel, 'Monstros')
        from .update_panel import UpdatePanel
        self.update_panel = UpdatePanel(relay_running=lambda: self.process.state() != QProcess.NotRunning)
        self.update_panel.restart_requested.connect(self.restart_after_update)
        tabs.addTab(self.update_panel, 'Atualização')
        QTimer.singleShot(1500, lambda: self.update_panel.run('check'))  # tell about new versions on start
        self.strict_map = QCheckBox('Exigir mapa de colisão válido antes de iniciar')
        form.insertRow(0, self.strict_map)
        keys_box = QGroupBox('Teclas (valem com o jogo em primeiro plano)')
        keys_form = QFormLayout(keys_box)
        from PySide6.QtWidgets import QComboBox
        from .packet_settings import HOTKEYS
        self.hotkey_hunt, self.hotkey_minimap = QComboBox(), QComboBox()
        for combo in (self.hotkey_hunt, self.hotkey_minimap):
            combo.addItems([name for name in HOTKEYS if name != 'F12'])
        keys_form.addRow('Iniciar / parar o bot', self.hotkey_hunt)
        keys_form.addRow('Esconder / mostrar o minimapa', self.hotkey_minimap)
        keys_form.addRow(QLabel('F12 continua bloqueando todos os envios do bot.'))
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
        presence_layout.addWidget(QLabel('Os alertas em vermelho no Diagnóstico aparecem sempre.'))
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
        self.notice = QLabel('Home inicia/pausa • F12 bloqueia envios • Alt+Tab mantém a caça')
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        layout.addWidget(QLabel('Fechar este painel ou encerrar a conexão desconecta o jogo ligado a este relay.'))
        try:
            settings = read()
        except (OSError, ValueError) as exc:
            self.notice.setText('Configuração inválida: '+str(exc))
            settings = DEFAULTS.copy()
        self.targets.selected = set(settings['species'])
        self.auto_map_targets.setChecked(settings['auto_map_targets'])
        self.radius.setValue(settings['radius'])
        self.step.setValue(settings['patrol_step'])
        self.patrol.setChecked(settings['patrol'])
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
        self.pause_disguised.setChecked(settings['pause_on_disguised'])
        self.pause_hidden.setChecked(settings['pause_on_hidden'])
        self.skill_panel.saved = settings['skill_profiles']
        self.skill_panel.summon_queue_mode = settings['summon_queue_mode']
        self.priority_panel.saved = settings['skill_priority']
        for key, field in self.combat_fields.items():
            field.setValue(settings[key])
        self.watch_settings()
        self.load_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(700)
        self.overlay_timer = QTimer(self)
        self.overlay_timer.timeout.connect(self.refresh_overlays)
        self.overlay_timer.start(100)
        tabs.currentChanged.connect(lambda index: self.refresh())

    def settings(self):
        return {'species': sorted(self.targets.selected),
                'radius': self.radius.value(), 'patrol_step': self.step.value(),
                'patrol': self.patrol.isChecked(), 'skills': self.skills.isChecked(), 'auto_map_targets': self.auto_map_targets.isChecked(),
                'require_collision': self.strict_map.isChecked(), 'advanced_combat': self.advanced.isChecked(),
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
        except (OSError, ValueError) as exc:
            self.notice.setText(str(exc))

    def command(self, command, **values):
        if self.process.state() == QProcess.NotRunning or self.session is None:
            self.notice.setText('Abra a conexão primeiro.')
            return
        if self.pending_command and command not in ('pause', 'stop'):
            self.notice.setText('Aguardando confirmação do comando anterior. F12 continua disponível.')
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

    def refresh(self):
        if self.session is None or self.process.state() == QProcess.NotRunning:
            return
        try:
            state = json.loads((self.session/'estado.json').read_text(encoding='utf-8'))
            hunt = state.get('hunt', {})
            self.targets.show_map(state.get('map_name'), {m['species_id']: m for m in state.get('map_monsters', [])})
            if self.monster_panel.isVisible():
                self.monster_panel.reload()

            if self.skill_panel.isVisible():
                self.skill_panel.update_catalog(state.get('learned_skills', []), state.get('own_effects', {}), state.get('buff_candidates', {}), state.get('rotation'))
            self.skill_panel.receive_buff_learning(state.get('buff_learning_result'))
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
            self.details.setText('\n\n'.join([
                f"Posição: {state.get('player_position') or '—'}     SP: {state['player_sp'] if state.get('player_sp') is not None else '—'}     Alvo: {hunt.get('target_id') or '—'}",
                'Alvo em combate: '+(f"{state['combat_target']['name']} • {state['combat_target']['distance']} células • posição {state['combat_target']['position']}"+
                                      (' (posição estimada)' if state['combat_target'].get('position_estimated', state['combat_target']['arrival_estimated']) else '') if state.get('combat_target') else 'nenhum'),
                'Posicao do alvo recebida: '+str((state.get('combat_target') or {}).get('last_received_position', '-'))+
                    ' | Destino anunciado: '+str((state.get('combat_target') or {}).get('announced_destination', '-')),
                f"Ataques confirmados: {hunt.get('confirmed_attacks', 0)}     Habilidades ofensivas confirmadas: {hunt.get('confirmed_skills', 0)}",
                f"Candidatos recentes: {len(state.get('recent_entities', []))}     Mensagens recebidas: {state.get('messages', 0)}",
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
        if self.session is None or self.process.state() == QProcess.NotRunning:
            return
        if not (self.game_overlay.isVisible() or self.overlay.isVisible() or self.priority_panel.minimap.isChecked()):
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
        if bool(state) and self.priority_panel.minimap.isChecked():
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
        if state.get('own_hidden'):
            self.game_overlay.follow_game()
            if not self.game_overlay.isVisible():
                self.game_overlay.show()
        elif self.game_overlay.isVisible():
            self.game_overlay.hide()

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
        self.targets.changed.connect(self.schedule_save)
        for combo in (self.hotkey_hunt, self.hotkey_minimap):
            combo.currentTextChanged.connect(self.schedule_save)
            combo.currentTextChanged.connect(lambda text: self.update_key_notice())
        for field in (self.resume_delay, self.burst_interval):
            field.valueChanged.connect(self.schedule_save)
        for box in (self.auto_map_targets, self.patrol, self.skills, self.strict_map, self.fast_offensives,
                    self.sit_on_players, self.limit_failures, self.defer_failed, self.skill_burst,
                    self.advanced, self.auto_attacks, self.pause_players, self.pause_disguised, self.pause_hidden):
            box.toggled.connect(self.schedule_save)
        for field in (self.radius, self.step, *self.combat_fields.values()):
            field.valueChanged.connect(self.schedule_save)
        self.skill_panel.changed.connect(self.schedule_save)
        self.priority_panel.changed.connect(self.schedule_save)
        self.priority_panel.minimap.toggled.connect(lambda checked: self.save_ui())
        self.overlay.on_change = self.save_ui

    def update_key_notice(self):
        self.notice.setText(f'{self.hotkey_hunt.currentText()} inicia/pausa • {self.hotkey_minimap.currentText()} '
                            'esconde/mostra o minimapa • F12 bloqueia envios • Alt+Tab mantém a caça')

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
        except (TypeError, ValueError):
            pass

    def save_ui(self):
        ui = {'geometry': bytes(self.saveGeometry().toBase64()).decode('ascii'), 'tab': self.tabs.currentIndex(),
              'minimap': self.priority_panel.minimap.isChecked(), 'minimap_layout': self.overlay.layout_state(),
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
