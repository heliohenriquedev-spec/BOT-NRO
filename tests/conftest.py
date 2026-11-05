import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_monster_data(tmp_path, monkeypatch):
    """Tests never write the monsters learned on this PC (data/monstros)."""
    from nrobot import monster_db
    from nrobot import drop_db
    from nrobot import quest_progress
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
