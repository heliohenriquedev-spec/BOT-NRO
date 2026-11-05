"""Progress of the quest queue, kept on disk so a stop (player around, disconnect) can be resumed."""
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

FILE = Path(__file__).resolve().parents[1]/'data/rede/progresso_quests.json'


def load(path=None):
    path = Path(path or FILE)
    for candidate in (path, path.with_suffix(path.suffix+'.bak')):
        try:
            data = json.loads(candidate.read_text(encoding='utf-8'))
            if isinstance(data, dict) and data.get('route_id'):
                return data
        except (OSError, ValueError):
            continue
    return None


def atomic_write(path, state):
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(state, stream, ensure_ascii=False, indent=1)
            stream.flush()
            os.fsync(stream.fileno())
        from .quest_daily import replace
        replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save(state, path=None):
    path = Path(path or FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = load(path)
    if previous:
        atomic_write(path.with_suffix(path.suffix+'.bak'), previous)
    atomic_write(path, {**state, 'saved_at': datetime.now().isoformat(timespec='seconds')})


def clear(path=None):
    path = Path(path or FILE)
    # Both must disappear: a completed queue must not be restored from its backup.
    path.with_suffix(path.suffix+'.bak').unlink(missing_ok=True)
    path.unlink(missing_ok=True)


def describe(state):
    if not state:
        return 'Nenhum progresso salvo.'
    stage = {'pickup': 'pegando missoes', 'travel': 'indo ao mapa', 'hunt': 'cacando', 'delivery': 'entregando'}.get(
        state.get('stage') or state.get('phase'), state.get('stage') or state.get('phase'))
    if state.get('map'):
        stage += ' em '+str(state['map']).removesuffix('.gat')
    from .npc_labels import plain
    counts, named = state.get('kill_counts') or {}, state.get('name_counts') or {}
    kills = ', '.join(f"{t['name']} {min(named.get(plain(t['name']), 0)+sum(counts.get(str(s), 0) for s in t['species']), t['count'])}/{t['count']}"
                      for t in state.get('kill_targets') or [])
    return (f"Progresso salvo ({state.get('saved_at', '')[11:16]}): {state.get('route_name')} - {stage}"
            + (f" - {kills}" if kills else ''))
