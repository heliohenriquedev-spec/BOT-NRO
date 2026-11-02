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
    monkeypatch.setattr(monster_db, 'CAPTURED', tmp_path/'monstros'/'capturados.json')
    monkeypatch.setattr(monster_db, 'SPRITES', tmp_path/'monstros'/'sprites')
