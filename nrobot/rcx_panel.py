"""Native floor-rendering controls; checked state means a verified renderer request."""
import time
import json
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QGroupBox

from .ground_cells import GRAY_STYLE


class RcxPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel('RCX / M2E — celulas de habilidades no chao do jogo')
        title.setWordWrap(True)
        layout.addWidget(title)
        self.toggle = QPushButton('Ativar RCX')
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(self.set_enabled)
        from .rcx_renderer import RcxRenderer
        self.renderer = RcxRenderer()
        self.feed_path = None
        self.feed_stamp = None
        self.started_at = 0
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.refresh_renderer)
        layout.addWidget(self.toggle)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        box = QGroupBox('Modelo de cor solicitado')
        preview = QVBoxLayout(box)
        swatch = QLabel('Cinza — preenchimento das celulas afetadas, com contorno')
        swatch.setWordWrap(True)
        swatch.setStyleSheet(f"background:{GRAY_STYLE['fill']};color:white;border:1px solid {GRAY_STYLE['outline']};padding:12px")
        preview.addWidget(swatch)
        layout.addWidget(box)
        self.observed = QLabel('Aguardando unidades de terreno do servidor.')
        self.observed.setWordWrap(True)
        layout.addWidget(self.observed)
        detail = QLabel('A captura usa as celulas informadas pelo servidor e remove a marcacao ao receber o fim '
                        'da unidade ou uma troca de mapa. Alcance e tempo de conjuracao nao criam celulas presumidas. '
                        'O desenho usa a camera, as alturas do terreno e o Direct3D do proprio cliente. '
                        'A desativacao remove a pintura sem reiniciar o jogo.')
        detail.setWordWrap(True)
        layout.addWidget(detail)
        layout.addStretch()
        self.set_enabled(False)

    def set_enabled(self, enabled):
        if enabled:
            try:
                self.renderer.start()
                self.started_at = time.monotonic()
                self.toggle.setText('Desativar RCX')
                self.status.setText('Conectando o desenho nativo ao NRO...')
                self.timer.start()
            except (OSError, ValueError, KeyError) as exc:
                self.toggle.blockSignals(True)
                self.toggle.setChecked(False)
                self.toggle.blockSignals(False)
                self.renderer.close()
                self.status.setText('Nao ativado: '+str(exc))
                self.toggle.setText('Ativar RCX')
        else:
            self.timer.stop()
            self.renderer.close()
            self.status.setText('RCX desativado.')
            self.toggle.setText('Ativar RCX')

    def refresh_renderer(self):
        if self.feed_path is not None:
            try:
                stamp = self.feed_path.stat().st_mtime_ns
                if stamp != self.feed_stamp:
                    ground = json.loads(self.feed_path.read_text(encoding='utf-8'))
                    self.renderer.update({**self.renderer.state, 'ground_cells': ground})
                    self.feed_stamp = stamp
            except (OSError, ValueError):
                pass
        info = self.renderer.snapshot()
        if info.get('attached') and info.get('frames'):
            self.status.setText(f"RCX ativo no chao do jogo | celulas desenhadas: {info['drawn']} | recebidas: {info.get('received', 0)}")
            if info['error']:
                self.status.setText('Falha de desenho RCX (codigo '+str(info['error'])+'); desative e confira o diagnostico.')
        elif time.monotonic()-self.started_at > 8 or info.get('error'):
            self.set_enabled(False)
            self.toggle.blockSignals(True);self.toggle.setChecked(False);self.toggle.blockSignals(False)
            self.status.setText('Nao ativado: o cliente nao confirmou o desenho Direct3D. Confira se jogo e painel usam a mesma permissao.')

    def shutdown(self):
        self.timer.stop()
        self.renderer.close()

    def update_state(self, state):
        feed = (state.get("ground_cells") or {}).get("feed_file")
        path = Path(feed) if feed else None
        if path != self.feed_path:
            self.feed_path, self.feed_stamp = path, None
        ground = state.get('ground_cells') or {}
        if self.feed_path is not None:
            try:
                ground = json.loads(self.feed_path.read_text(encoding='utf-8'))
                self.feed_stamp = self.feed_path.stat().st_mtime_ns
            except (OSError, ValueError):
                pass
        self.renderer.update({**state, 'ground_cells': ground})
        cells = ground.get('cells') or []
        self.observed.setText(f"Mapa: {ground.get('map') or 'aguardando'} | Habilidades de terreno: {len(cells)} celulas recebidas"
                              + (' | leitura incompleta' if ground.get('incomplete') else ''))


def main():
    """Optional independent control, usable without disconnecting the running relay."""
    import json
    from pathlib import Path
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    panel = RcxPanel()
    panel.setWindowTitle('NRO — RCX no chao')
    panel.resize(650, 380)
    root = Path(__file__).resolve().parents[1]/'logs/relay'
    def refresh():
        try:
            files = list(root.glob('*/estado.json'))
            if files:
                path = max(files, key=lambda p: p.stat().st_mtime)
                if time.time()-path.stat().st_mtime < 3:
                    panel.update_state(json.loads(path.read_text(encoding='utf-8')))
                    return
        except (OSError, ValueError):
            pass
        panel.update_state({})
    timer = QTimer(panel)
    timer.timeout.connect(refresh)
    timer.start(200)
    app.aboutToQuit.connect(panel.shutdown)
    panel.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
