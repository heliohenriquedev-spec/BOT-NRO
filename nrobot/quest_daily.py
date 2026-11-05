"""Board missions already done today (daily missions), per character: seen as "Status : Completa",
refused as "Voce ja completou esta missao", or delivered by the bot.

The queue skips them without walking to the board again (a disconnect used to send the character
back to boards whose missions it had already finished). Each character keeps its own list."""
import json
import time
import uuid
from datetime import date
from pathlib import Path

FILE = Path(__file__).resolve().parents[1]/'data/rede/missoes_concluidas.json'
CHARACTER = None  # the character playing in this process (panel or relay)


def key(board_id, label):
    from .npc_labels import plain, rank
    return board_id+'|'+plain(rank(label) or label)


def load_all(path=None):
    """{character: {mission key: date}}. The old file had no character: kept under ''."""
    try:
        data = json.loads(Path(path or FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    if 'personagens' not in data:
        return {'': {k: v for k, v in data.items() if isinstance(v, str)}}
    people = data['personagens']
    return {str(name): dict(marks) for name, marks in people.items() if isinstance(marks, dict)} if isinstance(people, dict) else {}


def load(path=None, character=None):
    """Marks of one character (the one playing when not given)."""
    return load_all(path).get(character if character is not None else (CHARACTER or ''), {})


def mark(board_id, label, path=None, character=None):
    today = date.today().isoformat()
    name = character if character is not None else (CHARACTER or '')
    people = {who: {k: v for k, v in marks.items() if v == today}  # older days drop out
              for who, marks in load_all(path).items()}
    people = {who: marks for who, marks in people.items() if marks}
    people.setdefault(name, {})[key(board_id, label)] = today
    write_json(Path(path or FILE), {'personagens': people})


def today_keys(character, path=None):
    """Mission keys this character finished today; nothing for an unknown character."""
    if not character:
        return set()
    today = date.today().isoformat()
    return {k for k, v in load(path, character).items() if v == today}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    replace(temporary, path)


def replace(temporary, path, attempts=20):
    """Windows refuses a replace while another process reads the file ("Acesso negado"): the
    queue progress was lost that way before a disconnect. Try again for a moment."""
    for attempt in range(attempts):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == attempts-1:
                temporary.unlink(missing_ok=True)
                raise
            time.sleep(.05)


SLOTS = FILE.with_name('slots_missoes.json')


def load_slots(path=None):
    """Which registered mission each board slot holds ({slot: mission id})."""
    try:
        data = json.loads(Path(path or SLOTS).read_text(encoding='utf-8'))
        return {int(k): v for k, v in data.items() if isinstance(v, str)}
    except (OSError, ValueError, AttributeError):
        return {}


def save_slots(owners, path=None):
    write_json(Path(path or SLOTS), {str(k): v for k, v in owners.items()})


def done_today(board_id, label, data=None):
    data = load() if data is None else data
    return data.get(key(board_id, label)) == date.today().isoformat()
