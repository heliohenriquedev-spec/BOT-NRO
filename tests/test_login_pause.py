import asyncio

from nrobot import auto_login


def test_pause_during_fragmented_auth_preserves_native_request():
    from test_login_packets import request
    config = dict(auto_login.DEFAULTS, enabled=True, user='saved', password='DPAPI')
    adapter = auto_login.LoginPacketAdapter(config, {0x64: 55}, decrypt=lambda _: 'secret')
    packet = request()
    assert adapter.feed(packet[:20]) == b''
    config['paused'] = True
    assert adapter.feed(packet[20:]) == packet
    assert not adapter.buffer


def test_pause_cancels_scheduled_character_and_resume_uses_same_list(tmp_path):
    from nrobot.session_relay import SessionRelay
    from test_auto_login_and_routes import char_list
    class Writer:
        def __init__(self): self.sent = []
        def is_closing(self): return False
        def write(self, data): self.sent.append(bytes(data))
        async def drain(self): pass
    async def scenario():
        config = dict(auto_login.DEFAULTS, enabled=True, character='Ninja')
        auto_login.save(config)
        relay = SessionRelay('127.0.0.1', folder=tmp_path)
        relay.stage = 'char'
        writer = Writer()
        relay.schedule_character_choice(char_list((123, 'Ninja', 1)), writer)
        await asyncio.sleep(0)
        config['paused'] = True; auto_login.save(config)
        relay.sync_auto_login_pause()
        await asyncio.sleep(.15)
        assert relay.character_choice_task.cancelled()
        assert not writer.sent
        config['paused'] = False; auto_login.save(config)
        relay.sync_auto_login_pause()
        await relay.character_choice_task
        assert writer.sent == [auto_login.select_packet(1)]
        # Resuming after a successful choice must never choose the character again.
        config['paused'] = True; auto_login.save(config); relay.sync_auto_login_pause()
        config['paused'] = False; auto_login.save(config); relay.sync_auto_login_pause()
        await asyncio.sleep(.15)
        assert len(writer.sent) == 1
    asyncio.run(scenario())


def test_login_pause_button_persists_without_replacing_account_or_password():
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
    from nrobot.packet_panel import PacketPanel
    app = QApplication.instance() or QApplication([])
    auto_login.save(dict(auto_login.DEFAULTS, enabled=True, user='saved', password='DPAPI', character='Ninja'))
    class Harness(QWidget):
        toggle_auto_login_pause = PacketPanel.toggle_auto_login_pause
        save_auto_login = PacketPanel.save_auto_login
    widget = Harness()
    widget.notice = QLabel()
    try:
        PacketPanel.build_auto_login(widget, QVBoxLayout(widget))
        widget.pause_login_button.click()
        paused = auto_login.load()
        assert paused['paused'] and paused['enabled'] and paused['password'] == 'DPAPI' and paused['character'] == 'Ninja'
        assert 'Retomar' in widget.pause_login_button.text()
        widget.pause_login_button.click()
        assert not auto_login.load()['paused']
        assert 'Pausar' in widget.pause_login_button.text()
    finally:
        widget.close()
