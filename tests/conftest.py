import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

_qt_application = None


@pytest.fixture(scope='session', autouse=True)
def keep_qt_application_alive():
    """UI tests share one application; temporary Python refs must not destroy Qt mid-suite."""
    global _qt_application
    from PySide6.QtWidgets import QApplication
    _qt_application = QApplication.instance() or QApplication([])
    yield _qt_application


@pytest.fixture(autouse=True)
def isolated_monster_data(tmp_path, monkeypatch):
    """Tests never write the monsters learned on this PC (data/monstros)."""
    from nrobot import monster_db
    from nrobot import drop_db
    from nrobot import quest_progress
    from nrobot import quest_routes
    monkeypatch.setattr(quest_routes, "FILE", tmp_path/"rede"/"rotas_quests.json")
    from nrobot import watchlist
    from nrobot import rcx_settings
    monkeypatch.setattr(rcx_settings, "FILE", tmp_path/"rede"/"rcx_config.json")
    monkeypatch.setattr(rcx_settings, "SHARED_FILE", tmp_path/"recursos"/"rcx"/"config_enviada.json")
    from nrobot import npc_map, map_routes, bg_entry
    from nrobot import auto_routes
    from nrobot import npc_transports
    from nrobot import database_hunt
    monkeypatch.setattr(database_hunt, "SHOWMOBS_FILE", tmp_path/"rede"/"showmobs_monstros.json")
    from nrobot import hunt_share
    monkeypatch.setattr(hunt_share, "FILE", tmp_path/"rede"/"caca_patrulha.json")
    monkeypatch.setattr(npc_transports, "FILE", tmp_path/"mapas"/"npc_transportes.json")
    monkeypatch.setattr(npc_transports, "SHARED_FILE", tmp_path/"compartilhado"/"npc_transportes.json")
    monkeypatch.setattr(auto_routes, "FILE", tmp_path/"mapas"/"portais_destinos.json")
    monkeypatch.setattr(bg_entry, "FILE", tmp_path/"rede"/"bg_entradas.json")
    monkeypatch.setattr(npc_map, "FILE", tmp_path/"mapas"/"npcs.json")
    monkeypatch.setattr(map_routes, "FILE", tmp_path/"rede"/"rotas_mapas.json")
    monkeypatch.setattr(watchlist, 'FILE', tmp_path/'jogadores'/'observacao.json')
    monkeypatch.setattr(quest_progress, 'FILE', tmp_path/'rede'/'progresso_quests.json')
    monkeypatch.setattr(drop_db, 'FILE', tmp_path/'database'/'observacoes.sqlite3')
    monkeypatch.setattr(monster_db, 'CAPTURED', tmp_path/'monstros'/'capturados.json')
    monkeypatch.setattr(monster_db, 'SPRITES', tmp_path/'monstros'/'sprites')
    monkeypatch.setattr(monster_db, 'BASE_INFO', tmp_path/'monstros_base'/'monstros.json')
    monkeypatch.setattr(monster_db, 'BASE_SPRITES', tmp_path/'monstros_base'/'sprites')


def pytest_sessionfinish(session, exitstatus):
    """Close every Qt window while Python still runs: tearing Qt down at interpreter exit
    crashes now and then (0xC0000409) after all tests passed, failing the publish button."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    app.processEvents()
    app.sendPostedEvents(None, 0)  # run the pending deleteLater calls
    app.processEvents()
