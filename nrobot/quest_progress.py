"""Progress of the quest queue, kept on disk so a stop (player around, disconnect) can be resumed."""
import json
import uuid
from datetime import datetime
from pathlib import Path

FILE = Path(__file__).resolve().parents[1]/'data/rede/progresso_quests.json'


def load(path=None):
    try:
        data = json.loads(Path(path or FILE).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) and data.get('route_id') else None
    except (OSError, ValueError):
        return None


def save(state, path=None):
    path = Path(path or FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps({**state, 'saved_at': datetime.now().isoformat(timespec='seconds')},
                                    ensure_ascii=False, indent=1), encoding='utf-8')
    from .quest_daily import replace
    replace(temporary, path)
    for stale in path.parent.glob(path.name+'.*.tmp'):  # left by refused replaces before
        if stale != temporary:
            stale.unlink(missing_ok=True)


def clear(path=None):
    try:
        Path(path or FILE).unlink()
    except OSError:
        pass


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
