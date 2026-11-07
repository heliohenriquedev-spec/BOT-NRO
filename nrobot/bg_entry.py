"""Battleground entry (aba BG): 5x5, 4x4 and 3x3.

Each BG has its own NPC, recorded once with "Gravar NPC": the walk, the NPC talked to and every
option chosen (same recorder as the quest routes). The NPC messages are the same for all of
them, so they are set once for every BG:
- the error message (registration closed / not possible now), and
- the queue message (registered, waiting in the queue).
NPC lines seen while recording are offered in both fields. "Gravar mensagem de erro" / "Gravar
mensagem de sucesso" take the next line the NPC says in the game (talk to it after clicking).

"Entrar na BG" replays the recording from wherever the character is and keeps trying, every few
seconds, until it gets in: it stops only on a positive registration message.
Only the player stops it before that.
Saved per PC in data/rede/bg_entradas.json:
{'entradas': {mode: {'steps', 'target_map', 'recorded_at'}},
 'mensagens': {'error', 'queue', 'retry_seconds', 'seen'}}.
"""
from __future__ import annotations

import copy
from datetime import datetime
import json
import math
import re
from pathlib import Path
import uuid

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QDoubleSpinBox, QVBoxLayout,
                               QWidget)

FILE = Path(__file__).resolve().parents[1]/'data'/'rede'/'bg_entradas.json'
MODES = ('5x5', '4x4', '3x3')
RETRY = 2  # s between two attempts while the NPC refuses
POLL_SECONDS = .05  # local state checks only; never the network retry interval
RESPONSE_TIMEOUT = 10  # no answer after the recorded trip: stop rather than duplicate a registration
MESSAGES = dict(error='', queue='', retry_seconds=RETRY, seen=[], stationary=False)


def retry_interval(value):
    try:value=float(value)
    except (TypeError,ValueError):return RETRY
    return round(max(.05,min(120,value)),2) if math.isfinite(value) else RETRY


def plain(text):
    from .npc_labels import plain as normalized
    return normalized(text or '')


def npc_lines(texts):
    """NPC messages, cleaned and without repeats."""
    from .npc_labels import clean
    lines = []
    for text in texts:
        line = clean(text)[:200]
        if line and line not in lines:
            lines.append(line)
    return lines


def _read(path=None):
    try:
        data = json.loads(Path(path or FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'entradas': {}, 'mensagens': dict(MESSAGES)}
    if 'entradas' not in data:  # first version: modes at the top, messages per mode
        old = {m: e for m, e in data.items() if m in MODES and isinstance(e, dict)}
        text = next((e.get('success_text') for e in old.values() if e.get('success_text')), '')
        data = {'entradas': old, 'mensagens': dict(MESSAGES, queue=text)}
    data['mensagens'] = {**MESSAGES, **(data.get('mensagens') or {})}
    data['mensagens']['retry_seconds']=retry_interval(data['mensagens']['retry_seconds'])
    return data


def _write(data, path=None):
    path = Path(path or FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    temporary.replace(path)


def load(path=None):
    """{mode: recorded entry} of the BGs already recorded."""
    return {m: e for m, e in _read(path)['entradas'].items() if m in MODES and isinstance(e, dict) and e.get('steps')}


def messages(path=None):
    return _read(path)['mensagens']


def save_entry(mode, entry, seen=(), path=None):
    data = _read(path)
    data['entradas'][check_mode(mode)] = entry
    known = data['mensagens']['seen']
    data['mensagens']['seen'] = (known+[line for line in seen if line not in known])[-20:]
    _write(data, path)


def save_messages(error, queue, retry_seconds, path=None, *, stationary=None):
    data = _read(path)
    data['mensagens'].update(error=(error or '').strip()[:200], queue=(queue or '').strip()[:200],
                             retry_seconds=retry_interval(retry_seconds))
    if stationary is not None:data['mensagens']['stationary']=bool(stationary)
    _write(data, path)


CAPTURE_SECONDS = 120  # to go to the NPC and talk after clicking "Gravar mensagem"


def save_message(which, text, path=None):
    """One message captured from the NPC (error or queue), kept for every BG."""
    if which not in ('error', 'queue'):
        raise ValueError('Mensagem desconhecida')
    data = _read(path)
    line = npc_lines([text])[0] if npc_lines([text]) else ''
    data['mensagens'][which] = line
    seen = data['mensagens']['seen']
    data['mensagens']['seen'] = (seen+[line] if line and line not in seen else seen)[-20:]
    _write(data, path)
    return line


def message_line(text):
    """A line worth keeping: not the "[NPC name]" header, not empty."""
    from .npc_labels import clean
    line = clean(text or '')
    return line if line and not (line.startswith('[') and line.endswith(']')) else ''


def recorded_entry(steps, map_name, position):
    """What is kept of a recording: NPCs, options chosen, each map's way out and where it ended."""
    from .map_routes import compact
    from .quest_library import validate_steps
    steps = copy.deepcopy(steps)
    if not any(s['kind'] == 'npc' for s in steps):
        raise ValueError('Fale com o NPC da BG durante a gravacao antes de salvar')
    # Manual retries are observations, not a request to replay the whole sequence.
    # Keep the last interaction with that NPC, preserving the route before its first visit.
    last = max(i for i, step in enumerate(steps) if step['kind'] == 'npc')
    npc = steps[last]
    first = next(i for i, step in enumerate(steps) if step['kind'] == 'npc'
                 and step.get('map') == npc.get('map') and step.get('position') == npc.get('position'))
    steps = steps[:first]+steps[last:]
    if position is not None and steps[-1].get('position') != list(position):
        steps.append(dict(kind='walk', map=map_name, position=list(position)))
    steps = validate_steps(compact(steps))
    return dict(steps=steps, target_map=map_name, recorded_at=datetime.now().isoformat(timespec='seconds'))


def check_mode(mode):
    if mode not in MODES:
        raise ValueError('Escolha 5x5, 4x4 ou 3x3')
    return mode


def registered_mode(text):
    match=re.search(r'voce ja se registrou no battleground\s+(3x3|4x4|5x5)\b',plain(text))
    return match[1] if match else None


def answer(text, config):
    """Positive registration, temporary refusal, named registration or no known result."""
    line = plain(text)
    # These are observed NRO replies shared by all three BG NPCs. Ignore accents,
    # colour markup and terminal punctuation instead of requiring an exact capture.
    if any(reply in line for reply in ('ha um evento em andamento','evento esta em espera','evento em espera')):
        return 'error'
    if registered_mode(text):return 'registered_mode'
    if 'registro feito com sucesso' in line or 'voce ja se registrou no evento' in line:
        return 'queue'
    if config.get('queue') and plain(config['queue']) in line:
        return 'queue'
    if config.get('error') and plain(config['error']) in line:
        return 'error'
    return None


class BgPanel(QWidget):
    command_requested = Signal(str, dict)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        intro = QLabel('1) Para cada BG, clique em "Gravar entrada na BG", faça no jogo o que você faz para se inscrever (andar, falar '
                       'com o NPC, escolher as opções) e clique em "Salvar gravação".\n'
                       '2) Escolha abaixo a mensagem de erro e a mensagem de fila: valem para todas as BGs. As falas do '
                       'NPC vistas nas gravações aparecem na lista.\n'
                       '3) Clique em "Entrar na 3x3", "4x4" ou "5x5": o bot fala com o NPC daquela BG e tenta de novo '
                       'até a inscrição dar certo; aí para sozinho.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        recording_help = QLabel('Durante a gravação, selecione manualmente as opções de entrada no jogo. '
                               'Pode repetir a conversa com o mesmo NPC: ao salvar, fica a última tentativa, '
                               'sem acumular as anteriores. Grave somente a inscrição, sem cancelar o registro depois.')
        recording_help.setWordWrap(True)
        layout.addWidget(recording_help)
        row = QHBoxLayout()
        row.addWidget(QLabel('BG para gravar/ver:'))
        self.mode = QComboBox()
        self.mode.addItems(MODES)
        self.mode.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.mode)
        row.addStretch(1)
        layout.addLayout(row)
        enter = QHBoxLayout()
        self.enter_buttons = {}
        for mode in MODES:
            button = QPushButton('Entrar na '+mode)
            button.setToolTip(f'Fala com o NPC da BG {mode} e tenta de novo até a inscrição dar certo.')
            button.clicked.connect(lambda checked=False, m=mode: self.request('quest_bg_enter', mode=m))
            self.enter_buttons[mode] = button
            enter.addWidget(button)
        layout.addLayout(enter)
        buttons = QHBoxLayout()
        self.stop = QPushButton('Parar tentativas')
        self.stop.clicked.connect(lambda: self.request('quest_stop'))
        self.record = QPushButton('Gravar entrada na BG')
        self.record.clicked.connect(lambda: self.request('quest_bg_record', mode=self.mode.currentText()))
        self.save = QPushButton('Salvar gravação')
        self.save.clicked.connect(lambda: self.request('quest_bg_save'))
        self.cancel = QPushButton('Descartar gravação')
        self.cancel.clicked.connect(lambda: self.request('quest_bg_cancel'))
        for button in (self.stop, self.record, self.save, self.cancel):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.info = QLabel()
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        form = QFormLayout()
        self.error = QComboBox(); self.error.setEditable(True)
        self.queue = QComboBox(); self.queue.setEditable(True)
        for box, tip in ((self.error, 'Um trecho da mensagem do NPC quando não dá para se inscrever.'),
                         (self.queue, 'Um trecho da mensagem do NPC quando a inscrição dá certo (entrou na fila).')):
            box.setToolTip(tip)
            box.lineEdit().editingFinished.connect(self.store_messages)
            box.activated.connect(self.store_messages)
        form.addRow('Mensagem de erro (todas as BGs):', self.error)
        form.addRow('Mensagem de fila (todas as BGs):', self.queue)
        self.retry = QDoubleSpinBox(); self.retry.setDecimals(2); self.retry.setRange(.05, 120); self.retry.setSingleStep(.05); self.retry.setSuffix(' s'); self.retry.setValue(RETRY)
        self.retry.setToolTip('Espera entre tentativas concluidas. A proxima so comeca apos a resposta e o fechamento do dialogo anterior.')
        self.retry.valueChanged.connect(self.store_messages)
        form.addRow('Tentar de novo a cada:', self.retry)
        layout.addLayout(form)
        self.stationary=QCheckBox('Tentar da posicao atual, sem caminhar ate o NPC')
        self.stationary.setToolTip('Requer o NPC da BG recebido no mapa atual. O servidor decide se a distancia permite interagir. Nao executa a viagem gravada.')
        self.stationary.toggled.connect(self.store_messages)
        layout.addWidget(self.stationary)
        polling = QLabel('Verificação local: 0,05 s. Uma inscrição por vez; novas tentativas aguardam a resposta e o intervalo acima.')
        polling.setWordWrap(True)
        layout.addWidget(polling)
        capture = QHBoxLayout()
        self.capture_error = QPushButton('Gravar mensagem de erro')
        self.capture_error.setToolTip('Clique e fale com o NPC quando ele NÃO deixar se inscrever: a fala dele vira a mensagem de erro.')
        self.capture_error.clicked.connect(lambda: self.request('quest_bg_capture', which='error'))
        self.capture_queue = QPushButton('Gravar mensagem de sucesso')
        self.capture_queue.setToolTip('Clique e fale com o NPC quando a inscrição DER CERTO: a fala dele vira a mensagem de fila.')
        self.capture_queue.clicked.connect(lambda: self.request('quest_bg_capture', which='queue'))
        capture.addWidget(self.capture_error)
        capture.addWidget(self.capture_queue)
        layout.addLayout(capture)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch(1)
        self.recording = False
        self.refresh()

    def request(self, command, **values):
        self.command_requested.emit(command, values)

    def store_messages(self, *args):
        save_messages(self.error.currentText(), self.queue.currentText(), self.retry.value(),stationary=self.stationary.isChecked())
        self.refresh()

    def refresh(self, *args):
        config = messages()
        for box, key in ((self.error, 'error'), (self.queue, 'queue')):
            box.blockSignals(True)
            box.clear()
            box.addItems(config['seen'])
            box.setEditText(config[key])
            box.blockSignals(False)
        self.retry.blockSignals(True)
        self.retry.setValue(config['retry_seconds'])
        self.retry.blockSignals(False)
        self.stationary.blockSignals(True);self.stationary.setChecked(config['stationary']);self.stationary.blockSignals(False)
        self.mode.setEnabled(not self.recording)
        entry = load().get(self.mode.currentText())
        recorded = ', '.join(m for m in MODES if m in load()) or 'nenhuma'
        if entry:
            npcs = [s.get('name') or 'NPC' for s in entry['steps'] if s['kind'] == 'npc']
            choices = [s.get('option') for s in entry['steps'] if s['kind'] == 'select']
            text = (f"NPC da BG {self.mode.currentText()} gravado em {entry['recorded_at'].replace('T', ' ')} • "
                    f"termina em {entry['target_map']} • NPC: {', '.join(npcs)} • opções: "
                    f"{', '.join(c for c in choices if c) or 'nenhuma'}")
        else:
            text = f'O NPC da BG {self.mode.currentText()} ainda não foi gravado.'
        text += f'\nBGs gravadas: {recorded}.'
        if not (config['error'] or config['queue']):
            text += '\nEscolha a mensagem de erro e/ou a de fila para poder entrar.'
        self.info.setText(text)
        recorded_modes = load()
        for mode, button in self.enter_buttons.items():
            button.setEnabled(mode in recorded_modes and bool(config['error'] or config['queue']) and not self.recording)
        self.record.setEnabled(not self.recording)
        self.save.setEnabled(self.recording)
        self.cancel.setEnabled(self.recording)

    def update_state(self, state):
        q = (state or {}).get('quests') or {}
        recording = q.get('recording_scope') == 'bg'
        if recording != self.recording:
            self.recording = recording
            self.refresh()
        reason = q.get('reason') or ''
        if reason != self.status.text():
            if reason.startswith('Mensagem de'):
                self.refresh()  # a message was just captured: show it in its field
            self.status.setText(reason)
