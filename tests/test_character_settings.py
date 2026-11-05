"""Hunt, combat, skill and PvP settings are kept per character on each PC (never published)."""
from nrobot import packet_settings
from nrobot.packet_settings import DEFAULTS


def test_each_character_has_its_own_file(tmp_path):
    assert packet_settings.read_character('Uadaweu2', tmp_path) is None
    packet_settings.save_character('Uadaweu2', {**DEFAULTS, 'radius': 9}, tmp_path)
    packet_settings.save_character('Outro/Char', {**DEFAULTS, 'radius': 20}, tmp_path)
    assert packet_settings.read_character('Uadaweu2', tmp_path)['radius'] == 9
    assert packet_settings.read_character('Outro/Char', tmp_path)['radius'] == 20
    assert all(path.parent == tmp_path for path in tmp_path.iterdir())  # odd names stay inside the folder


def test_panel_switches_to_the_settings_of_the_character_that_logged_in(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from nrobot import packet_panel
    config = tmp_path/'painel_config.json'
    real_save = packet_settings.save
    monkeypatch.setattr(packet_panel, 'save', lambda data, path=config: real_save(data, config))
    monkeypatch.setattr(packet_panel, 'read', lambda: packet_settings.read(config))
    monkeypatch.setattr(packet_settings, 'CHARACTERS', tmp_path/'personagens')
    panel = packet_panel.PacketPanel()
    try:
        panel.radius.setValue(15)
        panel.switch_character('Primeiro')  # no file yet: starts from the current setup
        assert packet_settings.read_character('Primeiro')['radius'] == 15
        packet_settings.save_character('Segundo', {**DEFAULTS, 'radius': 25, 'kite': True, 'melee_approach': False})
        panel.switch_character('Segundo')
        assert panel.radius.value() == 25 and panel.kite.isChecked()
        panel.radius.setValue(12)
        panel.store(panel.settings())
        assert packet_settings.read_character('Segundo')['radius'] == 12
        assert packet_settings.read_character('Primeiro')['radius'] == 15  # the other one untouched
        panel.switch_character('Primeiro')
        assert panel.radius.value() == 15
    finally:
        panel.save_timer.stop()
        panel.close()
