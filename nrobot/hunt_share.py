"""The hunt patrol published by the developer: the same on every PC.

How the character walks while hunting (patrol on, spacing, coverage, wall margin, give-up time,
search radius, attackers ignored...) is taken from the developer's panel settings when publishing
(data/compartilhado/caca_patrulha.json). On the other PCs it is received into
data/rede/caca_patrulha.json and laid over every hunt the bot starts: the common hunt, the quest
hunts and the database hunt. The developer's PC has no such file: its panel is the source.
Skills, targets, PvP and the rest of the combat stay each character's own.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT/'data'/'rede'/'caca_patrulha.json'
KEYS = ('patrol', 'radius', 'patrol_step', 'patrol_spacing', 'patrol_coverage', 'patrol_wall_margin',
        'patrol_avoid_walls', 'patrol_give_up', 'ignore_attackers', 'target_defer', 'auto_movement',
        'require_collision')


def snapshot(root=ROOT):
    """Developer publishing: the patrol part of the panel settings."""
    from .packet_settings import validate
    path = Path(root)/'data'/'rede'/'painel_config.json'
    try:
        settings = validate(json.loads(path.read_text(encoding='utf-8')))
    except (OSError, ValueError):
        return None
    return {'schema': 1, 'settings': {key: settings[key] for key in KEYS}}


def published(path=None):
    """The received patrol ({} when none: the developer's PC, or nothing published yet)."""
    try:
        data = json.loads(Path(path or FILE).read_text(encoding='utf-8'))
        settings = data.get('settings') if isinstance(data, dict) else None
    except (OSError, ValueError):
        return {}
    return {key: settings[key] for key in KEYS if isinstance(settings, dict) and key in settings}


def apply(settings, path=None):
    """settings with the published patrol laid over (already validated by the caller afterwards)."""
    patrol = published(path)
    return {**settings, **patrol} if patrol else settings
