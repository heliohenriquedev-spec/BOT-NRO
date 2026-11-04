import json
from types import SimpleNamespace

import numpy as np
from PySide6.QtGui import QImage

from nrobot import auto_login
from nrobot.login_screens import ASSETS, pixels, local_connection_row


def screen(name, button=None):
    frame = np.full((600, 900, 3), [27, 49, 61], dtype=np.uint8)
    patch = pixels(QImage(str(ASSETS/(name+'.png'))))
    x, y = 170, 150
    frame[y:y+patch.shape[0], x:x+patch.shape[1]] = patch
    if button:
        patch = pixels(QImage(str(ASSETS/(button+'.png'))))
        frame[y+96:y+96+patch.shape[0], x+190:x+190+patch.shape[1]] = patch
    return frame


def test_complete_visual_sequence_with_no_real_window_or_secret_typing(tmp_path, monkeypatch):
    from nrobot import login_runner as module
    auto_login.save(dict(auto_login.DEFAULTS, enabled=True, user='real-account', password='DPAPI', character='Ninja'))
    monkeypatch.setattr(auto_login, 'unprotect', lambda _: 'real-secret')
    monkeypatch.setattr(module, 'local_connection_row', lambda _: 1)
    now = [0]
    def clock():
        now[0] += .5
        return now[0]
    import time
    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=clock, time=time.time))
    class Event:
        stopped = False
        count = 0
        def is_set(self): return self.stopped
        def set(self): self.stopped = True
        def wait(self, _):
            self.count += 1
            return self.stopped or self.count > 30
    messages = []
    runner = module.LoginRunner(tmp_path/'game', tmp_path, messages.append)
    runner.stop_event = Event()
    def status(stage, phase, **extra):
        (tmp_path/'estado.json').write_text(json.dumps(dict(stage=stage, login_phase=phase, **extra)))
    class Backend:
        frame = screen('win_msgbox', 'btn_ok')
        actions = []
        character_frames = 0
        def capture(self):
            if self.character_frames:
                self.character_frames += 1
                if self.character_frames >= 3:
                    runner.stop()
            return self.frame
        def apply(self, action, dialog, button, verify):
            assert verify()
            self.actions.append(action['kind'])
            if action['kind'] == 'confirm_disconnect':
                self.frame = screen('win_service', 'btn_ok')
                status('map_disconnected', 'disconnected')
            elif action['kind'] == 'connection':
                assert action['row'] == 1
                assert runner.marker.exists()
                self.frame = screen('win_login', 'btn_connect')
                status('login', 'waiting')
            elif action['kind'] == 'authenticate':
                assert runner.marker.exists()
                self.frame = screen('win_service', 'btn_ok')
                status('login', 'world', login_world_count=1, login_world_selected=True)
            elif action['kind'] == 'world':
                self.frame = screen('win_select')
                self.character_frames = 1
                status('char', 'characters')
    backend = Backend(); runner.backend = backend
    status('map_disconnected', 'disconnected')
    runner.run()
    assert backend.actions == ['confirm_disconnect', 'connection', 'authenticate', 'world'], messages
    assert not runner.marker.exists()
    assert not auto_login.load()['paused']
    assert 'real-secret' not in ' '.join(messages)


def test_local_connection_is_found_by_installed_profile_not_user_index(tmp_path, monkeypatch):
    from nrobot import relay_profile
    monkeypatch.setattr(relay_profile, 'installed_port', lambda: 16900)
    (tmp_path/'data').mkdir()
    (tmp_path/'data/clientinfo.xml').write_text('''<clientinfo>
    <connection><display>Original</display><address>192.0.2.1</address><port>6900</port></connection>
    <connection><display>NRO - BOT LOCAL (TESTE)</display><address>127.0.0.1</address><port>16900</port></connection>
    </clientinfo>''')
    assert local_connection_row(tmp_path) == 1
