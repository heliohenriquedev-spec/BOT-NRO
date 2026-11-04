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
    temporary.replace(path)


def clear(path=None):
    try:
        Path(path or FILE).unlink()
    except OSError:
        pass


def describe(state):
    if not state:
        return 'Nenhum progresso salvo.'
    stage = {'pickup': 'pegando missoes', 'travel': 'indo ao mapa', 'hunt': 'cacando', 'delivery': 'entregando'}.get(
        state.get('phase'), state.get('phase'))
    counts = state.get('kill_counts') or {}
    kills = ', '.join(f"{t['name']} {min(sum(counts.get(str(s), 0) for s in t['species']), t['count'])}/{t['count']}"
                      for t in state.get('kill_targets') or [])
    return (f"Progresso salvo ({state.get('saved_at', '')[11:16]}): {state.get('route_name')} - {stage}"
            + (f" - {kills}" if kills else ''))
