"""Log of where the quest queue is, started over at midnight (only today's lines are kept).

One line each time the progress changes (route, stage, mission, map or a kill), never on every
tick, so the file stays small and reads as the history of the day."""
from datetime import datetime
from pathlib import Path

FILE = Path(__file__).resolve().parents[1]/'logs'/'progresso_quests.log'
STAMP = '%Y-%m-%d %H:%M:%S'
PHASES = {'pickup': 'pegando missões', 'travel': 'indo para a caça', 'hunt': 'caçando',
          'delivery': 'entregando', 'return': 'retornando', 'paused': 'parada', 'done': 'fila concluída'}


def describe(snapshot, map_name=None):
    """One readable line from the queue snapshot; None while the queue has no route."""
    if not snapshot.get('quest'):
        return None
    parts = [snapshot['quest'], PHASES.get(snapshot['phase'], snapshot['phase'])]
    if snapshot.get('mission') and snapshot['phase'] in ('pickup', 'delivery'):
        parts.append(f"missão {snapshot['mission_index']}: {snapshot['mission']}")
    if snapshot['phase'] in ('pickup', 'delivery', 'travel', 'return') and snapshot.get('step'):
        parts.append(f"etapa {snapshot['step']}")
    kills = snapshot.get('kill_progress') or []
    if kills:
        parts.append(', '.join(f"{k['name']} {k['done']}/{k['count']}" for k in kills))
    if map_name:
        parts.append('mapa '+str(map_name).removesuffix('.gat'))
    if snapshot['phase'] == 'paused' and snapshot.get('reason'):
        parts.append(snapshot['reason'])
    return ' | '.join(parts)


class QuestProgressLog:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else FILE
        self.last = None

    def note(self, line, now=None):
        """Writes the line if it differs from the last one; lines from before midnight go away."""
        now = now or datetime.now()
        if not line or line == self.last:
            return False
        self.last = line
        self.write(self.recent(now)+[f'{now.strftime(STAMP)} | {line}'])
        return True

    def prune(self, now=None):
        """Drops yesterday's lines even when nothing new happened (queue stopped overnight)."""
        rows = self.read()
        kept = self.recent(now or datetime.now(), rows)
        if len(kept) != len(rows):
            self.write(kept)

    def recent(self, now, rows=None):
        rows = self.read() if rows is None else rows
        today = now.strftime('%Y-%m-%d')
        return [row for row in rows if self.age(row, now) is not None and row.startswith(today)]

    def write(self, rows):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            self.path.unlink(missing_ok=True)
            return
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text('\n'.join(rows)+'\n', encoding='utf-8')
        temporary.replace(self.path)

    def read(self):
        try:
            return [row for row in self.path.read_text(encoding='utf-8').splitlines() if row.strip()]
        except OSError:
            return []

    @staticmethod
    def age(row, now):
        try:
            return now-datetime.strptime(row[:19], STAMP)
        except ValueError:
            return None
