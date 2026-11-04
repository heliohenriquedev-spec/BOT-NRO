"""Recognize the shipped NRO skin and plan one login step at a time, without secrets."""
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

ASSETS = Path(__file__).resolve().parents[1]/'data/recursos/login'


def pixels(image):
    image = image.convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())[:, :image.width()*4].reshape(image.height(), image.width(), 4)[..., :3].copy()


@dataclass(frozen=True)
class Match:
    kind: str
    x: int
    y: int
    scale: float
    error: float


class ScreenMatcher:
    def __init__(self, folder=ASSETS, scales=(.5, .75, 1., 1.25, 1.5, 2.)):
        self.templates = []
        for kind, name in (('login', 'win_login'), ('service', 'win_service'),
                           ('characters', 'win_select'), ('message', 'win_msgbox'),
                           ('ok', 'btn_ok'), ('connect', 'btn_connect')):
            source = QImage(str(Path(folder)/(name+'.png')))
            if source.isNull():
                raise ValueError('Imagem de login ausente: '+name+'; atualize os recursos do bot')
            for scale in scales:
                image = source.scaled(round(source.width()*scale), round(source.height()*scale),
                                      Qt.IgnoreAspectRatio, Qt.FastTransformation)
                if name.startswith('win_'):
                    image = image.copy(0, 0, image.width(), round(18*scale))
                template = pixels(image)
                white = np.argwhere(template.min(axis=2) > 175)
                if len(white) < 8:
                    continue
                anchors = white[np.linspace(0, len(white)-1, 8, dtype=int)]
                red = np.argwhere((template[..., 0] > 60) & (template[..., 1] < 90) & (template[..., 2] < 90))
                if len(red):
                    anchors = np.concatenate((anchors, red[np.linspace(0, len(red)-1, 4, dtype=int)]))
                self.templates.append((kind, scale, template, anchors))

    def find(self, frame, kinds, region=None, scale=None):
        left, top, right, bottom = region or (0, 0, frame.shape[1], frame.shape[0])
        left, top = max(0, left), max(0, top)
        right, bottom = min(frame.shape[1], right), min(frame.shape[0], bottom)
        roi = frame[top:bottom, left:right, :3].astype(np.int16)
        best = None
        for kind, factor, template, anchors in self.templates:
            if kind not in kinds or scale is not None and factor != scale:
                continue
            h, w = template.shape[:2]
            height, width = roi.shape[0]-h+1, roi.shape[1]-w+1
            if height <= 0 or width <= 0:
                continue
            y, x = anchors[0]
            delta = np.abs(roi[y:y+height, x:x+width]-template[y, x])
            ys, xs = np.nonzero(delta.max(axis=2) <= 28)
            for y, x in anchors[1:]:
                keep = np.abs(roi[ys+y, xs+x]-template[y, x]).max(axis=1) <= 28
                ys, xs = ys[keep], xs[keep]
                if not len(xs):
                    break
            # Bounded work on text-heavy or unrelated screens. Ambiguous screens never click.
            if len(xs) > 200:
                continue
            for y, x in zip(ys, xs):
                sampled = template[::2, ::2]
                valid = ~((sampled[..., 0] > 240) & (sampled[..., 2] > 240) & (sampled[..., 1] < 20))
                error = float(np.abs(roi[y:y+h:2, x:x+w:2]-sampled)[valid].mean())
                if error <= 10 and (best is None or error < best.error):
                    best = Match(kind, int(left+x), int(top+y), factor, error)
        return best

    def dialog(self, frame):
        return self.find(frame, {'login', 'service', 'characters', 'message'})

    def button(self, frame, dialog, kind):
        s = dialog.scale
        return self.find(frame, {kind}, (dialog.x, dialog.y+round(65*s),
                         dialog.x+round(280*s), dialog.y+round(480*s)), scale=s)


def local_connection_row(game):
    from .relay_profile import connections, installed_port
    port = installed_port()
    found = set()
    for name in ('clientinfo.xml', 'sclientinfo.xml'):
        path = Path(game)/'data'/name
        try:
            entries = connections(path.read_bytes())
        except OSError:
            continue
        indices = [i for i, (label, host, value) in enumerate(entries)
                   if 'BOT LOCAL' in label.upper() and host in ('127.0.0.1', 'localhost') and str(port) == value]
        if len(indices) == 1:
            found.add(indices[0])
    if len(found) != 1:
        raise ValueError('Nao foi possivel confirmar a linha NRO - BOT LOCAL; reinstale o perfil local')
    return found.pop()


class LoginFlow:
    """Visual evidence plus protocol state; never confirms an arbitrary message box."""
    def __init__(self):
        self.observed = None
        self.stable_at = 0
        self.acted = None
        self.acted_at = 0
        self.local_selected = False

    def plan(self, match, state, config, now, connection_row):
        if config.get('paused') or not config.get('enabled') or not config.get('screen_login', True):
            self.observed = self.acted = None
            return None
        if state.get('login_phase') == 'failed':
            raise ValueError('Servidor recusou o login; confira os dados no painel antes de retomar')
        if match is None:
            self.observed = None
            return None
        key = (match.kind, match.x, match.y, match.scale, state.get('login_phase'))
        if self.observed != key:
            self.observed, self.stable_at = key, now
            return None
        if now-self.stable_at < .4:
            return None
        if self.acted == key:
            if now-self.acted_at > max(8, config.get('login_wait', 8)) and match.kind != 'characters':
                raise ValueError('Tela nao avancou apos a acao; login pausado para evitar repeticoes')
            return None
        phase, stage = state.get('login_phase'), state.get('stage')
        if match.kind == 'message':
            if stage != 'map_disconnected' or phase != 'disconnected':
                return None
            return {'kind': 'confirm_disconnect', 'evidence': key}
        if match.kind == 'service':
            if phase == 'world':
                row = 0 if state.get('login_world_selected') else config.get('server_index', 1)-1
                if not 0 <= row < state.get('login_world_count', 0):
                    raise ValueError('Servidor escolhido nao existe na lista recebida')
                return {'kind': 'world', 'row': row, 'evidence': key}
            if phase in (None, 'disconnected', 'waiting') and stage in ('waiting_login', 'map_disconnected', 'login'):
                return {'kind': 'connection', 'row': connection_row, 'evidence': key}
        if match.kind == 'login' and phase in (None, 'waiting', 'disconnected'):
            if not self.local_selected and stage != 'login':
                raise ValueError('Volte a selecao de conexao e escolha NRO - BOT LOCAL antes de autenticar')
            if not config.get('user') or not config.get('password'):
                raise ValueError('Salve conta e senha no painel antes de iniciar')
            if state.get('login_transport') == 'unsupported':
                raise ValueError('Autenticacao do cliente nao reconhecida; volte a selecao de conexao')
            return {'kind': 'authenticate', 'evidence': key}
        # Character selection belongs exclusively to the relay, using the server's list.
        return None

    def sent(self, action, now):
        self.acted, self.acted_at = action['evidence'], now
        if action['kind'] == 'connection':
            self.local_selected = True
        elif action['kind'] == 'confirm_disconnect':
            self.local_selected = False
