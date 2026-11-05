"""Lista de observação: characters (by id or name) that raise an on-screen alert when found.

Every way the bot knows a character is around counts, @hide included:
  - visible on screen, or disguised as a monster;
  - hide / cloak / @hide switched on inside our view (option bits);
  - invisible next to us, revealed by an action the server relays (chat, skill, emote...);
  - vanished close by without logging out or teleporting (may have gone into @hide).
A hidden character often shows only its id, so names are matched through the player
registry (every id ever seen with its name).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .presence_guard import normalize_player_name

FILE = Path(__file__).resolve().parents[1]/'data'/'jogadores'/'observacao.json'

# (priority, text) per detection kind; the highest priority wins when several apply.
STATUS = {'invisible': (6, 'INVISÍVEL ao seu lado'), 'gm_hide': (5, 'em @hide ao seu lado'),
          'hide': (4, 'escondido (hide/cloak) ao seu lado'), 'disguised': (3, 'disfarçado de monstro na tela'),
          'visible': (2, 'na tela'), 'vanished': (1, 'sumiu perto de você (pode ter entrado em @hide)')}


def load(path=None):
    try:
        entries = json.loads(Path(path or FILE).read_text(encoding='utf-8'))
        return [str(e).strip() for e in entries if str(e).strip()]
    except (OSError, ValueError, TypeError):
        return []


def save(entries, path=None):
    path = Path(path or FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(temporary, path)


def enabled():
    try:
        data = json.loads(FILE.with_name('observacao_opcoes.json').read_text(encoding='utf-8'))
        return data.get('enabled', True) is not False
    except (OSError, ValueError, AttributeError):
        return True


def set_enabled(value):
    path = FILE.with_name('observacao_opcoes.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'enabled': bool(value)}), encoding='utf-8')
    os.replace(temporary, path)


def watched(entry_text, identity, name):
    text = entry_text.strip()
    if text.isdigit():
        return int(text) == identity
    return bool(name) and normalize_player_name(text) == normalize_player_name(name)


def detections(entries, state, registry=None, match_all=False):
    """[{'entity_id', 'name', 'kind', 'text', 'detail', 'position', 'entry'}] for watched characters
    (match_all: every character around, for the @hide stop)."""
    if not entries or not state:
        return []
    registry = registry or {}
    presence = state.get('presence') or {}
    found = {}

    def add(identity, kind, name=None, detail=None, position=None):
        name = name or (registry.get(str(identity)) or {}).get('name')
        entry = '*' if match_all else next((e for e in entries if watched(e, identity, name)), None)
        if entry is None:
            return
        old = found.get(identity)
        if old is None or STATUS[kind][0] > STATUS[old['kind']][0]:
            found[identity] = {'entity_id': identity, 'name': name, 'kind': kind, 'text': STATUS[kind][1],
                               'detail': detail, 'position': position, 'entry': entry}
        elif name and not old['name']:
            old['name'] = name

    rows = {row['entity_id']: row for row in state.get('players_nearby', [])}
    disguised = set(presence.get('disguised', []))
    for identity in set(presence.get('players', [])) | set(rows):
        row = rows.get(identity, {})
        detail = f"{row['distance']} células" if row.get('distance') is not None else None
        add(identity, 'disguised' if identity in disguised else 'visible', row.get('name'), detail, row.get('position'))
    for shadow in presence.get('shadow_details', presence.get('hidden_details', [])):
        if shadow.get('invisible_signal'):
            kind, detail = 'invisible', f"sem aparecer na tela: {shadow['invisible_signal']}"
        elif shadow.get('possible_hidden'):
            kind, detail = 'vanished', 'saiu da tela perto, sem deslogar nem teleportar'
        elif shadow.get('gm_invisible'):
            kind, detail = 'gm_hide', 'ativou o @hide perto de você'
        else:
            kind, detail = 'hide', 'ativou hide/cloak perto de você'
        add(shadow['entity_id'], kind, shadow.get('name'), detail, shadow.get('position'))
    return sorted(found.values(), key=lambda d: (-STATUS[d['kind']][0], d['entity_id']))
