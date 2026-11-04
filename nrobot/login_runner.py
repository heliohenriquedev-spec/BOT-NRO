"""Background login supervisor: recognized UI steps, real credentials only in relay packets."""
import json
from pathlib import Path
import threading
import time
import uuid

from . import auto_login
from .login_screens import ScreenMatcher, LoginFlow, local_connection_row
_MARKER_LOCK = threading.Lock()


class LoginRunner:
    def __init__(self, game, session, report, backend=None):
        self.game, self.session, self.report = Path(game), Path(session), report
        self.stop_event = threading.Event()
        self.identity = uuid.uuid4().hex
        self.backend = backend
        self.marker = self.session/'login_bootstrap.json'
        self.flow = LoginFlow()
        self.thread = None

    def stopped(self):
        config = auto_login.load()
        return self.stop_event.is_set() or config.get('paused') or not config['enabled']

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True, name='NRO-login')
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def prepare_bootstrap(self):
        config = auto_login.load()
        auto_login.LoginPacketAdapter.field(config.get('user', ''))
        auto_login.LoginPacketAdapter.field(auto_login.unprotect(config.get('password', '')))
        data = dict(id=self.identity, until=time.monotonic()+60)
        with _MARKER_LOCK:
            if self.stopped():
                return False
            temporary = self.marker.with_name(self.marker.name+'.'+self.identity+'.tmp')
            temporary.write_text(json.dumps(data), encoding='utf-8')
            temporary.replace(self.marker)
        return True

    def clear_bootstrap(self):
        with _MARKER_LOCK:
            try:
                if json.loads(self.marker.read_text(encoding='utf-8')).get('id') == self.identity:
                    self.marker.unlink(missing_ok=True)
            except (OSError, ValueError):
                pass

    def run(self):
        from .login_window import GameLoginWindow
        try:
            matcher = ScreenMatcher()
            connection_row = local_connection_row(self.game)
            self.backend = self.backend or GameLoginWindow(self.stopped)
            self.report('Login automatico: deixe a janela do jogo em primeiro plano. Telas desconhecidas nao recebem comandos.')
            last_message = None
            while not self.stop_event.wait(.35):
                config = auto_login.load()
                if config.get('paused') or not config['enabled'] or not config.get('screen_login', True):
                    self.flow.observed = self.flow.acted = None
                    self.flow.local_selected = False
                    self.clear_bootstrap()
                    continue
                status = self.session/'estado.json'
                try:
                    if time.time()-status.stat().st_mtime > 3:
                        continue
                    state = json.loads(status.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                if state.get('stage') == 'stopped':
                    return
                if state.get('login_phase') in ('world', 'characters', 'map'):
                    self.clear_bootstrap()
                if (state.get('login_phase') == 'authenticating' and self.flow.acted is not None
                    and time.monotonic()-self.flow.acted_at > max(15, config.get('login_wait', 8))):
                    raise ValueError('Servidor nao respondeu a autenticacao; tentativa pausada')
                if state.get('stage') == 'map' and state.get('player_position') is not None:
                    self.flow.observed = self.flow.acted = None
                    continue
                frame = self.backend.capture()
                if frame is None:
                    continue
                dialog = matcher.dialog(frame)
                action = self.flow.plan(dialog, state, config, time.monotonic(), connection_row)
                if action is None:
                    continue
                kind = 'connect' if action['kind'] == 'authenticate' else 'ok'
                button = matcher.button(frame, dialog, kind)
                if button is None:
                    continue
                if action['kind'] in ('connection', 'authenticate'):
                    if not self.prepare_bootstrap():
                        continue
                def verify():
                    if self.stopped():
                        return False
                    current = self.backend.capture()
                    if current is None:
                        return False
                    match = matcher.find(current, {dialog.kind},
                        (dialog.x-2, dialog.y-2, dialog.x+round(580*dialog.scale), dialog.y+round(24*dialog.scale)),
                        scale=dialog.scale)
                    return match is not None and abs(match.x-dialog.x) <= 2 and abs(match.y-dialog.y) <= 2
                try:
                    self.backend.apply(action, dialog, button, verify)
                except InterruptedError:
                    self.flow.observed = None
                    continue
                self.flow.sent(action, time.monotonic())
                message = {'connection': 'Conexao NRO - BOT LOCAL selecionada.',
                           'authenticate': 'Inicializacao ficticia enviada ao cliente; credenciais reais somente no pacote do relay.',
                           'world': 'Servidor selecionado; aguardando lista para escolher o personagem por pacote.',
                           'confirm_disconnect': 'Aviso de desconexao confirmado; aguardando selecao de conexao.'}[action['kind']]
                if message != last_message:
                    self.report('Login automatico: '+message)
                    last_message = message
        except (OSError, ValueError) as exc:
            if self.stop_event.is_set():
                return
            config = auto_login.load(); config['paused'] = True
            auto_login.save(config)
            self.report('Login automatico pausado: '+str(exc))
        except Exception as exc:
            if self.stop_event.is_set():
                return
            config = auto_login.load(); config['paused'] = True
            auto_login.save(config)
            self.report('Login automatico pausado por erro interno: '+type(exc).__name__)
        finally:
            self.clear_bootstrap()
