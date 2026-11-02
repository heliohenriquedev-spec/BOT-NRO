"""REDE-41: character skill catalog and explicitly configured rotation."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
                              QCheckBox, QSpinBox, QDoubleSpinBox, QComboBox, QHeaderView, QPushButton, QHBoxLayout)
from .combat_rotation import skill_category
import time


class SkillPanel(QWidget):
    apply_requested = Signal()
    probe_requested = Signal(int, int)
    summon_finished = Signal()
    changed = Signal()  # any edit: the panel saves it by itself
    def __init__(self, profiles=None):
        super().__init__()
        self.saved = profiles or []
        self.signature = None
        self.rows = {}
        self.display_names = {}
        self.candidates = {}
        self.learning_result_id = None
        try:
            from .catalog import load
            catalog = load() or {}
            self.local_names = {key: value['nome'] for key, value in catalog.get('habilidades', {}).items()}
        except (OSError, ValueError, KeyError):
            self.local_names = {}
        layout = QVBoxLayout(self)
        explanation = QLabel('Selecione um buff e clique em Aprender e ativar buff. Com a caça pausada, o bot usa a habilidade, identifica o efeito e salva a renovação automática.\nNenhum vínculo é criado se a resposta for ambígua.')
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        modes_help = QLabel('Papel: ofensivas em si ativam perto do alvo; buffs renovam pelo efeito; invocacoes seguem uma fila exclusiva e aguardam o fim da anterior. Alcance: Jogo usa o padrao recebido; selecione um numero para alterar e volte ao minimo para restaurar o padrao. Em si com alcance 0 usa proximidade de 2 celulas, pois o servidor nao informa o raio de dano.')
        modes_help.setWordWrap(True)
        layout.addWidget(modes_help)
        self.summon_label = QLabel('Invocacoes: fila vazia')
        self.summon_label.setWordWrap(True)
        layout.addWidget(self.summon_label)
        self.effects_label = QLabel('Efeitos próprios: aguardando conexão')
        self.effects_label.setWordWrap(True)
        layout.addWidget(self.effects_label)
        fill = QPushButton('Preencher vínculos observados • revisar antes de aplicar')
        fill.clicked.connect(self.fill_candidates)
        fill.hide()
        offensives = QPushButton('Marcar ofensivas de alvo único compatíveis')
        offensives.clicked.connect(self.enable_offensives)
        layout.addWidget(offensives)
        apply = QPushButton('Salvar e aplicar habilidades • pausa a caça')
        apply.clicked.connect(self.apply_requested.emit)
        layout.addWidget(apply)
        probe = QPushButton('Aprender e ativar buff selecionado • exige caça pausada')
        probe.clicked.connect(self.probe_selected)
        layout.addWidget(probe)
        kuchiyose = QPushButton('Marcar Kuchiyose aprendidas para a fila')
        kuchiyose.clicked.connect(self.enable_kuchiyose)
        summon_buttons = QHBoxLayout()
        summon_buttons.addWidget(kuchiyose)
        self.finish_summon = QPushButton('A invocacao terminou no jogo: confirmar fim e aprender duracao')
        self.finish_summon.setToolTip('Use somente apos verificar que ela realmente desapareceu. Mede o tempo desta invocacao para os proximos usos quando o servidor nao informa seu termino.')
        self.finish_summon.clicked.connect(self.summon_finished.emit)
        self.finish_summon.setEnabled(False)
        summon_buttons.addWidget(self.finish_summon)
        layout.addLayout(summon_buttons)
        queue_note = QLabel('Fila Kuchiyose: menor prioridade numerica primeiro; ao terminar, usa a proxima disponivel. Duracao 0 acompanha o efeito. Sem sinal de termino, informe a duracao ou confirme o fim observado uma vez para aprender. CD nao e duracao.')
        queue_note.setWordWrap(True)
        layout.addWidget(queue_note)
        self.table = QTableWidget(0, 14)
        self.table.setHorizontalHeaderLabels(['Usar', 'ID', 'Nome recebido', 'Tipo do servidor', 'Aprendida',
                                             'Nível usado', 'SP / alcance', 'Papel', 'CD local (s)', 'B?nus monitorado', 'Situa??o', 'Alcance (celulas)', 'Duracao invocacao (s)', 'Prioridade invocacao'])
        self.table.setColumnWidth(11, 130)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for column, width in {0:42, 1:52, 3:185, 4:72, 5:90, 6:80, 7:102, 8:98, 9:115, 10:160}.items():
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setColumnHidden(9, True)
        self.table.setColumnHidden(10, True)
        layout.addWidget(self.table)

    def receive_buff_learning(self, result):
        """REDE-52: synchronize a learning result once, never overwrite live edits."""
        if not result or result.get('id') == self.learning_result_id:
            return
        self.learning_result_id = result['id']
        profile = dict(result['profile'])
        self.saved = [p for p in self.saved if p['skill_id'] != profile['skill_id']]+[profile]
        row = self.rows.get(profile['skill_id'])
        if row is not None:
            row['effect'].setValue(profile['effect_id'])
            row['level'].setValue(profile['level'])
            row['role'].setCurrentIndex(1)
            row['enabled'].setChecked(profile['enabled'])

    def profiles(self):
        if self.signature is None:
            return self.saved
        shown = [{'skill_id': identity, 'enabled': row['enabled'].isChecked(), 'role': row['role'].currentData(),
                  'level': row['level'].value(), 'interval': row['interval'].value(), 'effect_id': row['effect'].value(),
                  'range_override': None if row['range'].value() == -1 else row['range'].value(),
                  'summon_duration': row['duration'].value(), 'summon_priority': row['priority'].value()}
                 for identity, row in self.rows.items()]
        # Skills this character does not have (another character's setup) stay saved.
        return shown+[p for p in self.saved if p['skill_id'] not in self.rows]

    def update_catalog(self, catalog, effects, candidates=None, rotation=None):
        catalog = [skill for skill in catalog if type(skill.get('level')) is int and skill['level'] > 0]
        catalog.sort(key=lambda skill: skill['skill_id'])
        self.candidates = candidates or {}
        active = [str(identity) for identity, enabled in effects.items() if enabled]
        names = {skill['skill_id']: self.local_names.get(skill.get('name'), skill.get('name')) or str(skill['skill_id']) for skill in catalog}
        links = ', '.join(f"{names.get(int(identity), identity)} → efeito {effect}" for identity, effect in self.candidates.items())
        effects_text = f'{len(catalog)} habilidades aprendidas • Efeitos ativos: '+(', '.join(active) or 'nenhum informado')+' • Vínculos: '+(links or 'nenhum observado')
        if self.effects_label.text() != effects_text:
            self.effects_label.setText(effects_text)
        signature = tuple((s['skill_id'], s['level'], s['sp_cost'], s['range'], s.get('target_flags'), s.get('name')) for s in catalog)
        if signature == self.signature:
            self.update_states(effects, rotation or {})
            return
        configured = {p['skill_id']: p for p in self.profiles()}
        self.saved = list(configured.values())
        self.signature = signature
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.build_rows(catalog, configured)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)
        self.update_states(effects, rotation or {})

    def build_rows(self, catalog, configured):
        self.rows.clear()
        self.display_names.clear()
        for row in range(self.table.rowCount()):
            for column in (0, 5, 7, 8, 9, 11, 12, 13):
                if self.table.cellWidget(row, column) is not None:
                    self.table.removeCellWidget(row, column)
        self.table.clearContents()
        self.table.setRowCount(len(catalog))
        for index, metadata in enumerate(catalog):
            identity = metadata['skill_id']
            flags = metadata.get('target_flags')
            compatible = metadata['level'] > 0 and (flags in (1, 2, 4, 16) or identity == 524)
            received_name = metadata.get('name')
            display_name = self.local_names.get(received_name, received_name) or ('Arremessar Kunai' if identity == 524 else 'Nome não recebido')
            self.display_names[identity] = display_name
            values = {1: identity, 2: display_name, 3: skill_category(metadata), 4: metadata['level'],
                      6: f"{metadata['sp_cost']} / {metadata['range']}"}
            for column, value in values.items():
                self.table.setItem(index, column, QTableWidgetItem(str(value)))
            if not compatible:
                for column in (0, 5, 7, 8, 9, 11, 12, 13):
                    self.table.setItem(index, column, QTableWidgetItem('—'))
                self.table.setItem(index, 10, QTableWidgetItem('Não executável no bot'))
                continue
            profile = configured.get(identity, {'enabled': identity == 524 and compatible, 'role': 'summon' if 'kuchiyose' in display_name.casefold() else 'buff' if flags in (4, 16) else 'offensive',
                'level': min(10, metadata['level']) if identity == 524 else max(1, metadata['level']), 'interval': 30 if flags == 2 else .5, 'effect_id': 0})
            enabled = QCheckBox()
            enabled.setChecked(profile['enabled'] and compatible)
            enabled.setEnabled(compatible)
            level = QSpinBox()
            level.setRange(1, max(1, min(metadata['level'], 100)))
            level.setValue(profile['level'])
            level.setEnabled(compatible)
            role = QComboBox()
            role.addItem('Ofensiva em si' if flags in (4, 16) else 'Ofensiva no alvo', 'offensive')
            role.addItem('Buff em si', 'buff')
            role.addItem('Invocacao no chao', 'summon')
            role.model().item(0).setEnabled(flags in (1, 4, 16) or identity == 524)
            role.model().item(1).setEnabled(flags in (4, 16))
            role.model().item(2).setEnabled(flags in (2, 4, 16))
            role.setCurrentIndex(max(0, role.findData(profile['role'])))
            role.setEnabled(compatible)
            interval = QDoubleSpinBox()
            interval.setRange(.1, 300)
            interval.setDecimals(2)
            interval.setSingleStep(.1)
            interval.setValue(profile['interval'])
            effect = QSpinBox()
            effect.setRange(0, 65535)
            effect.setSpecialValueText('Não identificado')
            effect.setToolTip('Efeito informado pelo servidor; diferente do ID da habilidade. Use Testar buff e Preencher vínculos para identificar.')
            effect.setValue(profile['effect_id'])
            distance = QSpinBox()
            distance.setRange(-1, 32)
            distance.setSpecialValueText(f"Jogo ({metadata['range']})")
            distance.setValue(-1 if profile.get('range_override') is None else profile['range_override'])
            distance.setToolTip('Automatico usa os dados do jogo. Alterar este limite nao aumenta o alcance permitido pelo servidor. Em si: raio de proximidade para ativar (se o jogo informa 0, o bot usa 2 para ativacao; nao e o raio de dano). Chao: alcance da conjuracao.')
            duration = QDoubleSpinBox()
            duration.setRange(0, 86400)
            duration.setDecimals(1)
            duration.setSpecialValueText('Observar efeito')
            duration.setValue(profile.get('summon_duration', 0))
            duration.setToolTip('0: aguarda termino do efeito vinculado. Um numero usa duracao configurada quando nao ha efeito vinculado. Cooldown e duracao sao controles diferentes.')
            queue_priority = QSpinBox()
            queue_priority.setRange(0, 999)
            queue_priority.setValue(profile.get('summon_priority', 0))
            queue_priority.setToolTip('Menor numero invoca primeiro. Ao terminar, passa para a proxima disponivel da fila e depois recomeca.')
            self.rows[identity] = {'duration': duration, 'priority': queue_priority, 'range': distance, 'enabled': enabled, 'level': level, 'role': role, 'interval': interval, 'effect': effect,
                                   'target_flags': flags, 'index': index}
            for column, widget in ((0, enabled), (5, level), (7, role), (8, interval), (9, effect), (11, distance), (12, duration), (13, queue_priority)):
                self.table.setCellWidget(index, column, widget)
            def update_summon_fields(index=None, role=role, duration=duration, queue_priority=queue_priority):
                duration.setEnabled(role.currentData() == 'summon')
                queue_priority.setEnabled(role.currentData() == 'summon')
            role.currentIndexChanged.connect(update_summon_fields)
            update_summon_fields()
            enabled.toggled.connect(self.changed.emit)
            role.currentIndexChanged.connect(self.changed.emit)
            for spin in (level, interval, effect, distance, duration, queue_priority):
                spin.valueChanged.connect(self.changed.emit)

    def update_states(self, effects, rotation):
        summons = rotation.get('summons', {})
        active = summons.get('active') or {}
        entry = summons.get('durations', {}).get(f"{active.get('skill_id')}:{active.get('level')}", {})
        self.finish_summon.setEnabled(bool(active))
        queue_names = [self.display_names.get(i, str(i)) for i in summons.get('queue', [])]
        active_name = self.display_names.get(active.get('skill_id'), str(active.get('skill_id', '-')))
        text = (f"Fila de invocacoes: {' > '.join(queue_names)} | ativa/acompanhada: {active_name} | "
                f"{summons.get('reason', '')} | ultima duracao observada: {entry.get('last_observed_duration', '-')} s")
        if self.summon_label.text() != text:
            self.summon_label.setText(text)

        pending = {entry['skill_id'] for entry in rotation.get('pending', [])}
        ready = rotation.get('ready_at', {})
        for identity, row in self.rows.items():
            text = 'Desligada'
            if row['enabled'].isChecked():
                effect = row['effect'].value()
                delay = max(0, ready.get(identity, ready.get(str(identity), 0))-time.monotonic())
                if identity in pending:
                    text = 'Aguardando resposta'
                elif row['role'].currentData() == 'buff':
                    active = effects.get(effect, effects.get(str(effect)))
                    text = ('Vincular efeito' if not effect else 'Ativo (efeito observado)' if active else
                            'Efeito ausente' if active is False else 'Efeito não recebido')
                elif delay > 0:
                    text = f'Intervalo: {delay:.1f} s'
                else:
                    text = 'Habilitada'
            item = self.table.item(row['index'], 10)
            if item is None:
                self.table.setItem(row['index'], 10, QTableWidgetItem(text))
            elif item.text() != text:
                item.setText(text)

    def fill_candidates(self):
        for identity, effect in self.candidates.items():
            row = self.rows.get(int(identity))
            if row is not None and row['role'].currentData() == 'buff' and row['effect'].value() == 0:
                row['effect'].setValue(effect)

    def enable_kuchiyose(self):
        for identity, row in self.rows.items():
            if 'kuchiyose' in self.display_names.get(identity, '').casefold() and row['target_flags'] in (2, 4, 16):
                row['role'].setCurrentIndex(row['role'].findData('summon'))
                row['enabled'].setChecked(True)

    def enable_offensives(self):
        for identity, row in self.rows.items():
            if row['enabled'].isEnabled() and (row['target_flags'] == 1 or identity == 524):
                row['enabled'].setChecked(True)
                row['role'].setCurrentIndex(0)

    def probe_selected(self):
        index = self.table.currentRow()
        item = self.table.item(index, 1) if index >= 0 else None
        if item is None:
            self.effects_label.setText('Selecione a linha de um buff para testar.')
            return
        identity = int(item.text())
        row = self.rows.get(identity)
        if row is None:
            self.effects_label.setText('Essa habilidade é aprendida, mas não é executável pelo bot.')
            return
        if row['role'].currentData() != 'buff' or row['target_flags'] not in (4, 16) or not row['enabled'].isEnabled():
            self.effects_label.setText('O teste exige habilidade aprendida de uso em si/suporte configurada como Buff em si.')
            return
        self.probe_requested.emit(identity, row['level'].value())
