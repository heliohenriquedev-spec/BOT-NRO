"""Catálogo do cliente (nomes de monstros e habilidades) lido de data/catalogo/catalogo.json."""
from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_DIR = os.path.join(ROOT, "data", "catalogo")
DEFAULT_GAME_DIR = r"C:\NRO - Jogo COMPLETO"


def load(out: str = CATALOG_DIR) -> dict | None:
    path = os.path.join(out, "catalogo.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
