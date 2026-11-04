"""Board missions already done today (daily missions): seen as "Status : Completa", refused as
"Voce ja completou esta missao", or delivered by the bot."""
import json
import uuid
from datetime import date
from pathlib import Path

FILE = Path(__file__).resolve().parents[1]/'data/rede/missoes_concluidas.json'


def key(board_id, label):
    from .npc_labels import plain, rank
    return board_id+'|'+plain(rank(label) or label)


def load(path=None):
    try:
        data = json.loads(Path(path or FILE).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def mark(board_id, label, path=None):
    data = {k: v for k, v in load(path).items() if v == date.today().isoformat()}  # older days drop out
    data[key(board_id, label)] = date.today().isoformat()
    path = Path(path or FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    temporary.replace(path)


SLOTS = FILE.with_name('slots_missoes.json')


def load_slots(path=None):
    """Which registered mission each board slot holds ({slot: mission id})."""
    try:
        data = json.loads(Path(path or SLOTS).read_text(encoding='utf-8'))
        return {int(k): v for k, v in data.items() if isinstance(v, str)}
    except (OSError, ValueError, AttributeError):
        return {}


def save_slots(owners, path=None):
    path = Path(path or SLOTS)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps({str(k): v for k, v in owners.items()}, indent=1), encoding='utf-8')
    temporary.replace(path)


def done_today(board_id, label, data=None):
    data = load() if data is None else data
    return data.get(key(board_id, label)) == date.today().isoformat()
