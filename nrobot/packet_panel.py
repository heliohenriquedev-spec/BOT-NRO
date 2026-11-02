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
        layout.addWidget(tabs)
        configuration = QWidget()
        config_layout = QHBoxLayout(configuration)
        species_box = QGroupBox('Monstros alvo')
        species_layout = QVBoxLayout(species_box)
        self.species_layout = species_layout
        self.auto_map_targets = QCheckBox('Identificar monstros pelos dados recebidos do mapa')
        species_layout.addWidget(self.auto_map_targets)
        self.auto_map_targets.setToolTip('No modo automatico, os monstros confirmados do mapa sao incluidos. Para escolher especies manualmente, desative esta opcao.')
        self.species = {}
        for identity, name in SPECIES.items():
            box = QCheckBox(name)
            self.species[identity] = box
            species_layout.addWidget(box)
        self.auto_map_targets.toggled.connect(lambda enabled: [box.setEnabled(not enabled) for box in self.species.values()])
        species_layout.addStretch()
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
        self.skills = QCheckBox('Ativar habilidades configuradas (Kunai no modo simples)')
        form.addRow(self.skills)
        explanation = QLabel('Kunai exige nível, custo e SP recebidos do servidor.\nSem colisão legível, os obstáculos são descobertos pelas respostas de movimento.')
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
                  ('skill_interval', 'Intervalo padrão da Kunai (sem perfil específico)', .25, 3, ' s'),
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
            if not key.startswith('switch_'):
                combat_form.addRow(label, box)
        explanation = QLabel('O alvo atual e mantido enquanto estiver presente e valido. Kunai e Shuriken exigem municao equipada e confirmada pelo servidor.\nCD individual, delay global, alcance e SP continuam obrigatorios. Salvar e aplicar pausa a caca.')
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
        from .update_panel import UpdatePanel
        self.update_panel = UpdatePanel(relay_running=lambda: self.process.state() != QProcess.NotRunning)
        self.update_panel.restart_requested.connect(self.restart_after_update)
        tabs.addTab(self.update_panel, 'Atualização')
        QTimer.singleShot(1500, lambda: self.update_panel.run('check'))  # tell about new versions on start
        self.strict_map = QCheckBox('Exigir mapa de colisão válido antes de iniciar')
        form.insertRow(0, self.strict_map)
        presence_box = QGroupBox('Pausar o bot quando aparecer')
        presence_layout = QVBoxLayout(presence_box)
        self.pause_players = QCheckBox('Qualquer jogador por perto (até 14 células)')
        self.pause_disguised = QCheckBox('Jogador disfarçado de monstro')
        self.pause_hidden = QCheckBox('Jogador escondido ou em @hide')
        for box in (self.pause_players, self.pause_disguised, self.pause_hidden):
            presence_layout.addWidget(box)
        presence_layout.addWidget(QLabel('Os alertas em vermelho no Diagnóstico aparecem sempre.'))
        form.insertRow(form.rowCount()-1, presence_box)
        self.advanced = QCheckBox('Combinar habilidades configuradas e buffs por intervalos individuais')
        combat_form.addRow(self.advanced)
        self.auto_attacks = QCheckBox('Intercalar ataques básicos nos intervalos')
        combat_form.addRow(self.auto_attacks)
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
        for identity in settings['species']:
            if identity not in self.species:
                box = QCheckBox(f'Aparencia {identity}')
                self.species[identity] = box
                self.species_layout.insertWidget(self.species_layout.count()-1, box)
        for identity, box in self.species.items():
            box.setChecked(identity in settings['species'])
        self.auto_map_targets.setChecked(settings['auto_map_targets'])
        self.radius.setValue(settings['radius'])
        self.step.setValue(settings['patrol_step'])
        self.patrol.setChecked(settings['patrol'])
        self.skills.setChecked(settings['skills'])
        self.strict_map.setChecked(settings['require_collision'])
        self.advanced.setChecked(settings['advanced_combat'])
        self.auto_attacks.setChecked(settings['auto_attacks'])
        self.pause_players.setChecked(settings['pause_on_players'])
        self.pause_disguised.setChecked(settings['pause_on_disguised'])
        self.pause_hidden.setChecked(settings['pause_on_hidden'])
        self.skill_panel.saved = settings['skill_profiles']
        self.priority_panel.saved = settings['skill_priority']
        for key, field in self.combat_fields.items():
            field.setValue(settings[key])
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(700)
        self.overlay_timer = QTimer(self)
        self.overlay_timer.timeout.connect(self.refresh_overlays)
        self.overlay_timer.start(100)
        tabs.currentChanged.connect(lambda index: self.refresh())

    def settings(self):
        return {'species': [i for i, box in self.species.items() if box.isChecked()],
                'radius': self.radius.value(), 'patrol_step': self.step.value(),
                'patrol': self.patrol.isChecked(), 'skills': self.skills.isChecked(), 'auto_map_targets': self.auto_map_targets.isChecked(),
                'require_collision': self.strict_map.isChecked(), 'advanced_combat': self.advanced.isChecked(),
                'auto_attacks': self.auto_attacks.isChecked(), 'skill_profiles': self.skill_panel.profiles(),
                'skill_priority': self.priority_panel.priority(),
                'pause_on_players': self.pause_players.isChecked(), 'pause_on_disguised': self.pause_disguised.isChecked(),
                'pause_on_hidden': self.pause_hidden.isChecked(),
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

    def open_relay(self):
        if self.process.state() != QProcess.NotRunning:
            return
        try:
            save(self.settings())
            self.session = ROOT/'logs/relay'/datetime.now().strftime('%Y%m%d-%H%M%S-%f-painel')
            self.session.mkdir(parents=True)
            self.pending_command = None
            self.log.clear()
            self.process.start(sys.executable, ['-u', '-m', 'nrobot.session_relay', '--hunt', '--session-dir', str(self.session)])
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
            for monster in state.get('map_monsters', []):
                identity = monster['species_id']
                if identity not in self.species:
                    box = QCheckBox()
                    self.species[identity] = box
                    self.species_layout.insertWidget(self.species_layout.count()-1, box)
                self.species[identity].setText(f"{monster['name']} (ID {identity}, presentes: {monster['present']})")
                self.species[identity].setEnabled(not self.auto_map_targets.isChecked())

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
                                      (' (posição estimada)' if state['combat_target']['arrival_estimated'] else '') if state.get('combat_target') else 'nenhum'),
                f"Ataques confirmados: {hunt.get('confirmed_attacks', 0)}     Habilidades ofensivas confirmadas: {hunt.get('confirmed_skills', 0)}",
                f"Candidatos recentes: {len(state.get('recent_entities', []))}     Mensagens recebidas: {state.get('messages', 0)}",
                'Fase: '+hunt.get('phase', 'aguardando')+f" • Espera atual: {hunt.get('wait_seconds', 0)} s • Intervalo da Kunai: {hunt.get('skill_cooldown_seconds', 0)} s",
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
            return f"Kunai confirmada no alvo {event['target_id']}, dano {event.get('damage_raw')}"
        return f"Alvo {event.get('target_id', '—')}: {event.get('reason', event['kind'])}"

    def refresh_overlays(self):
        """10 Hz state for the in-game drawings; the dashboard keeps its own slower refresh."""
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

    def closeEvent(self, event):
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
