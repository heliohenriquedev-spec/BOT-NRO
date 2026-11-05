"""Panel commands (settings included) are never lost between the panel and the relay."""
import json
import time


def test_relay_keeps_a_command_it_could_not_read(tmp_path, monkeypatch):
    from pathlib import Path
    from nrobot.session_relay import SessionRelay
    from nrobot.packet_hunt import PacketHunt
    relay = SessionRelay('127.0.0.1', folder=tmp_path)
    relay.hunt = PacketHunt()
    path = tmp_path/'comando.json'
    path.write_text(json.dumps({'id': 'a1', 'command': 'pause'}), encoding='utf-8')
    original = Path.read_text

    def busy(self, *args, **kwargs):
        if self.name == 'comando.json':
            raise PermissionError('em uso pelo painel')
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', busy)
    relay.process_control(lambda: True)
    assert path.exists() and relay.control_result is None  # not lost: read again next tick
    monkeypatch.setattr(Path, 'read_text', original)
    relay.process_control(lambda: True)
    assert not path.exists() and relay.control_result['id'] == 'a1'


def test_panel_sends_an_unconfirmed_command_again_then_gives_up(tmp_path):
    from PySide6.QtWidgets import QApplication, QLabel
    app = QApplication.instance() or QApplication([])
    from nrobot.packet_panel import PacketPanel
    panel = PacketPanel.__new__(PacketPanel)
    panel.session, panel.notice = tmp_path, QLabel()
    request = {'id': 'b2', 'command': 'apply'}
    panel.pending_command, panel.pending_request = 'b2', request
    panel.pending_at, panel.pending_sends = time.monotonic()-5, 1
    panel.retry_command()
    assert json.loads((tmp_path/'comando.json').read_text(encoding='utf-8')) == request and panel.pending_sends == 2
    panel.pending_at = time.monotonic()-5; panel.retry_command()
    panel.pending_at = time.monotonic()-5; panel.retry_command()
    assert panel.pending_command is None and 'não confirmou' in panel.notice.text()
