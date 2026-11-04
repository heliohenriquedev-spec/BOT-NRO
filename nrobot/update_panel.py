"""Aba Atualização: verificar/atualizar pelo GitHub e, na cópia do desenvolvedor, publicar."""
import json
import sys

from PySide6.QtCore import QProcess, QProcessEnvironment, Signal
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)

from . import updater


class UpdatePanel(QWidget):
    restart_requested = Signal()

    def __init__(self, relay_running=lambda: False):
        super().__init__()
        self.relay_running = relay_running
        self.action = None
        self.output = ''
        layout = QVBoxLayout(self)

        update_box = QGroupBox('Atualizar o bot')
        update_layout = QVBoxLayout(update_box)
        self.status = QLabel(f"Versão instalada: {updater.local_version().get('version', '?')}")
        self.status.setWordWrap(True)
        update_layout.addWidget(self.status)
        row = QHBoxLayout()
        self.check_button = QPushButton('Verificar atualização')
        self.check_button.clicked.connect(lambda: self.run('check'))
        row.addWidget(self.check_button)
        self.apply_button = QPushButton('Atualizar agora')
        self.apply_button.setToolTip('Baixa a versão nova do GitHub e reinicia o painel. '
                                     'Configurações, buffs aprendidos, conexão local e logs são preservados.')
        self.apply_button.clicked.connect(self.apply)
        row.addWidget(self.apply_button)
        row.addStretch()
        update_layout.addLayout(row)
        layout.addWidget(update_box)

        self.publish_box = QGroupBox('Publicar atualização no GitHub (cópia do desenvolvedor)')
        publish_layout = QVBoxLayout(self.publish_box)
        publish_layout.addWidget(QLabel('Descreva o que mudou. Os testes rodam antes; se falharem, nada é enviado.'))
        row = QHBoxLayout()
        self.message = QLineEdit()
        self.message.setPlaceholderText('Ex.: patrulha evita cantos; Kunai respeita o delay do servidor')
        row.addWidget(self.message, 1)
        self.publish_button = QPushButton('Publicar atualização')
        self.publish_button.clicked.connect(self.publish)
        row.addWidget(self.publish_button)
        publish_layout.addLayout(row)
        row = QHBoxLayout()
        from PySide6.QtWidgets import QCheckBox
        self.restart_after_publish = QCheckBox('Reiniciar sozinho depois de publicar (com a conexão fechada)')
        self.restart_after_publish.setChecked(True)
        row.addWidget(self.restart_after_publish)
        self.restart_button = QPushButton('Reiniciar o bot')
        self.restart_button.setToolTip('Fecha e abre o painel de novo, já com o código atual.')
        self.restart_button.clicked.connect(self.restart)
        row.addWidget(self.restart_button)
        row.addStretch()
        publish_layout.addLayout(row)
        layout.addWidget(self.publish_box)
        self.publish_box.setVisible(updater.can_publish())

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)

        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(updater.ROOT))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert('PYTHONUTF8', '1')
        environment.insert('PYTHONIOENCODING', 'utf-8')
        self.process.setProcessEnvironment(environment)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.finished)

    def busy(self, value):
        for button in (self.check_button, self.apply_button, self.publish_button, self.restart_button):
            button.setEnabled(not value)

    def run(self, action, *args):
        if self.process.state() != QProcess.NotRunning:
            return
        self.action, self.output = action, ''
        self.busy(True)
        if action != 'check':
            self.log.appendPlainText(f'--- {action} ---')
        self.process.start(sys.executable, ['-u', '-m', 'nrobot.updater', action, *args])

    def apply(self):
        if self.relay_running():
            self.status.setText('Feche a conexão (botão Fechar conexão) antes de atualizar.')
            return
        self.run('apply')

    def restart(self):
        if self.relay_running():
            from PySide6.QtWidgets import QMessageBox
            if QMessageBox.question(self, 'Reiniciar o bot', 'A conexão está aberta: reiniciar desconecta o personagem. '
                                    'Reiniciar mesmo assim?') != QMessageBox.Yes:
                return
        self.status.setText('Reiniciando o painel...')
        self.restart_requested.emit()

    def publish(self):
        if not self.message.text().strip():
            self.status.setText('Escreva o que mudou antes de publicar.')
            return
        self.run('publish', '--message', self.message.text().strip())

    def read_output(self):
        text = bytes(self.process.readAllStandardOutput()).decode('utf-8', 'replace')
        self.output += text
        if self.action != 'check':
            self.log.appendPlainText(text.rstrip())

    def finished(self, code, _status=None):
        action = self.action
        self.busy(False)
        if action == 'check':
            line = self.output.strip().splitlines()[-1] if self.output.strip() else ''
            try:
                info = json.loads(line)
            except ValueError:
                self.status.setText(line or 'Não foi possível verificar a atualização.')
                return
            if info['newer']:
                self.status.setText(f"Nova versão disponível: {info['remote']} (instalada: {info['local']}). "
                                    f"{info.get('notes') or ''}  Clique em Atualizar agora.")
            else:
                self.status.setText(f"O bot está atualizado (versão {info['local']}).")
        elif action == 'apply' and code == 0:
            self.status.setText('Atualizado. Reiniciando o painel...')
            self.restart_requested.emit()
        elif action == 'publish' and code == 0:
            self.message.clear()
            self.status.setText(f"Publicado. Versão instalada: {updater.local_version().get('version')}")
            if self.restart_after_publish.isChecked():
                if self.relay_running():
                    self.status.setText(self.status.text()+' • Feche a conexão e clique em Reiniciar o bot para usar a versão nova.')
                else:
                    self.status.setText(self.status.text()+' • Reiniciando o painel...')
                    self.restart_requested.emit()
        elif code:
            self.status.setText('A operação falhou; veja o registro abaixo.')
