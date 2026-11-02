"""Pasta do jogo encontrada sozinha, salva por PC e validada."""
import pytest

import nrobot.game_folder as game_folder


def fake_game(folder):
    folder.mkdir(parents=True)
    (folder/'DATA.INI').write_text('[Data]\n0=data.grf\n')
    (folder/'data.grf').write_bytes(b'grf')
    return folder


def test_game_in_a_common_place_is_found_and_saved(monkeypatch, tmp_path):
    game = fake_game(tmp_path/'Desktop'/'NRO Jogo')
    monkeypatch.setattr(game_folder, 'SETTINGS', tmp_path/'perfis'/'jogo.json')
    monkeypatch.setattr(game_folder, 'running_game', lambda: None)
    monkeypatch.setattr(game_folder, 'candidates', lambda: iter([tmp_path/'nada', game]))
    assert game_folder.find() == game
    monkeypatch.setattr(game_folder, 'candidates', lambda: iter([]))
    assert game_folder.find() == game  # remembered on this PC


def test_folder_without_the_game_is_refused_and_chooser_is_used(monkeypatch, tmp_path):
    monkeypatch.setattr(game_folder, 'SETTINGS', tmp_path/'jogo.json')
    monkeypatch.setattr(game_folder, 'running_game', lambda: None)
    monkeypatch.setattr(game_folder, 'candidates', lambda: iter([]))
    with pytest.raises(ValueError):
        game_folder.save(tmp_path)
    game = fake_game(tmp_path/'Jogos'/'Naruto')
    assert game_folder.require(ask=lambda: game_folder.save(game)) == game
    assert game_folder.saved() == game


def test_candidates_look_inside_folders_named_like_the_game(monkeypatch, tmp_path):
    game = fake_game(tmp_path/'Desktop'/'NRO-main'/'NRO - Jogo')
    monkeypatch.setattr(game_folder.Path, 'home', staticmethod(lambda: tmp_path))
    monkeypatch.setattr(game_folder, 'DEFAULT', tmp_path/'ausente')
    assert game in list(game_folder.candidates())


def test_pasted_path_with_quotes_or_pointing_to_the_exe_is_accepted(monkeypatch, tmp_path):
    game = fake_game(tmp_path/'Meus Jogos'/'NRO')
    (game/'NRO.exe').write_bytes(b'exe')
    monkeypatch.setattr(game_folder, 'SETTINGS', tmp_path/'jogo.json')
    assert game_folder.save(f'  "{game}"  ') == game
    assert game_folder.save(str(game/'NRO.exe')) == game
    with pytest.raises(ValueError, match='não existe'):
        game_folder.save(str(tmp_path/'errado'))


def test_panel_field_saves_the_pasted_folder(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    game = fake_game(tmp_path/'NRO')
    monkeypatch.setattr(game_folder, 'SETTINGS', tmp_path/'jogo.json')
    monkeypatch.setattr(game_folder, 'running_game', lambda: None)
    monkeypatch.setattr(game_folder, 'candidates', lambda: iter([]))
    from nrobot.packet_panel import PacketPanel
    panel = PacketPanel()
    assert 'não encontrada' in panel.game_label.text()
    panel.game_field.setText(str(tmp_path/'errado'))
    assert panel.save_game_field() is None and 'inválida' in panel.game_label.text()
    panel.game_field.setText(f'"{game}"')
    assert panel.save_game_field() == game and game_folder.saved() == game
    assert 'encontrada' in panel.game_label.text()
    panel.close()
