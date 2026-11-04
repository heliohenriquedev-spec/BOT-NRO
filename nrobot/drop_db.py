"""Passive item database. Proximity suggests a drop source; it never proves one."""
from collections import deque
from contextlib import closing
from datetime import datetime, timezone
from functools import lru_cache
import json
import math
import re
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT/'data/database/observacoes.sqlite3'
NAMES = ROOT/'data/recursos/itens.json'


@lru_cache(maxsize=1)
def item_names():
    try:
        return {int(k): v for k, v in json.loads(NAMES.read_text(encoding='utf-8')).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def prepare_item_names(grfs, target=None):
    """Developer extraction only; runtime names come from the published catalog."""
    text = grfs.read('data\\idnum2itemdisplaynametable.txt').decode('cp1252', 'replace')
    names = {int(identity): name.replace('_', ' ').strip() for identity, name in
             re.findall(r'(?:^|\n)\s*(\d+)#([^#\r\n]+)#', text) if int(identity) > 0}
    if not names:
        raise ValueError('Tabela de nomes de itens vazia; catalogo anterior preservado')
    path = Path(target or NAMES); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(names, ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf-8')
    temporary.replace(path)
    item_names.cache_clear()
    return len(names)


def open_database(path=None):
    path = Path(path or FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=.2)
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS deaths(
      id INTEGER PRIMARY KEY, species INTEGER NOT NULL, name TEXT NOT NULL, map TEXT NOT NULL,
      x INTEGER, y INTEGER, stamp TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS floor(
      id INTEGER PRIMARY KEY, item INTEGER NOT NULL, amount INTEGER NOT NULL, map TEXT NOT NULL,
      x INTEGER, y INTEGER, fresh INTEGER NOT NULL, stamp TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'floor');
    CREATE TABLE IF NOT EXISTS links(
      floor_id INTEGER NOT NULL, death_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'candidate',
      PRIMARY KEY(floor_id,death_id));
    CREATE TABLE IF NOT EXISTS mob_info(
      species INTEGER PRIMARY KEY, name TEXT NOT NULL, stamp TEXT NOT NULL, raw TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS mob_drops(
      species INTEGER NOT NULL, position INTEGER NOT NULL, mvp INTEGER NOT NULL, item INTEGER NOT NULL,
      item_name TEXT NOT NULL, rate REAL NOT NULL, PRIMARY KEY(species,mvp,position));
    CREATE INDEX IF NOT EXISTS floor_item ON floor(item,map);
    CREATE INDEX IF NOT EXISTS death_species ON deaths(species,map);
    ''')
    if 'source' not in {row[1] for row in db.execute('PRAGMA table_info(floor)')}:
        db.execute("ALTER TABLE floor ADD COLUMN source TEXT NOT NULL DEFAULT 'floor'")
        db.commit()
    return db


class DropObserver:
    WINDOW = 1.5
    RADIUS = 3

    def __init__(self):
        from .entity_inventory import EntityInventory
        self.inventory = EntityInventory()
        self.db = None
        self.active = {}
        self.deaths = deque()
        self.pending = deque()
        self.dead = set()
        self.links_seen = set()
        self.error = None

    def close(self):
        if self.db is not None:
            self.db.close(); self.db = None

    def reset(self):
        self.active.clear(); self.deaths.clear(); self.pending.clear(); self.dead.clear()
        self.links_seen.clear()
        self.inventory.reset()

    def observe(self, events, player_id, now, map_name):
        if self.error:
            return
        from .map_monsters import is_confirmed_monster
        from .monster_origin import excluded_spawn, map_key
        from .network_targets import Entity
        if self.inventory.map_name is None:
            self.inventory.map_name = map_name
        changed = False
        for event in events:
            kind = event['kind']
            if kind in ('map_change', 'map_transfer'):
                self.reset(); self.inventory.map_name = event.get('map')
                continue
            if kind == 'appearance':
                self.dead.discard(event['entity_id'])
            if kind == 'floor_item_removed':
                self.active.pop(event['object_id'], None)
            relevant = kind == 'floor_item' or kind == 'remove' and event.get('reason') == 1 or kind == 'inventory_added' and event.get('success')
            key = map_key(self.inventory.map_name)
            if relevant and key:
                stamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
                if kind == 'remove':
                    actor = self.inventory.entities.get(event['entity_id'])
                    if (actor and event['entity_id'] not in self.dead and is_confirmed_monster(actor, player_id)
                        and not excluded_spawn(actor['species_id'], key, actor.get('name'))):
                        self.db = self.db or open_database()
                        moving = Entity(actor['entity_id'], actor['species_id'], *actor['position'], actor['last_seen'],
                                        'monster', destination=tuple(actor['destination']) if actor.get('destination') else None,
                                        walk_speed_ms=actor.get('walk_speed_ms'))
                        point = moving.combat_bounds(now)[0][0]
                        cursor = self.db.execute('INSERT INTO deaths(species,name,map,x,y,stamp) VALUES(?,?,?,?,?,?)',
                            (actor['species_id'], actor.get('name') or '', key, *point, stamp))
                        self.deaths.append((now, cursor.lastrowid, point))
                        self.dead.add(event['entity_id']); changed = True
                elif kind == 'inventory_added' and event.get('item_id', 0) > 0 and event.get('amount', 0) > 0:
                    self.db = self.db or open_database()
                    self.db.execute("INSERT INTO floor(item,amount,map,fresh,stamp,source) VALUES(?,?,?,0,?,'inventory')",
                                    (event['item_id'], event['amount'], key, stamp))
                    changed = True
                elif kind == 'floor_item' and event.get('item_id', 0) > 0 and event.get('amount', 0) > 0 and event['object_id'] not in self.active:
                    self.db = self.db or open_database()
                    point = event['position']
                    cursor = self.db.execute('INSERT INTO floor(item,amount,map,x,y,fresh,stamp) VALUES(?,?,?,?,?,?,?)',
                        (event['item_id'], event['amount'], key, *point, int(event['newly_dropped']), stamp))
                    self.active[event['object_id']] = cursor.lastrowid
                    if len(self.active) > 5000:
                        self.active.pop(next(iter(self.active)))
                    if event['newly_dropped']:
                        self.pending.append((now, cursor.lastrowid, point))
                    changed = True
            self.inventory.observe([event], now)
        while self.deaths and now-self.deaths[0][0] > self.WINDOW:
            self.deaths.popleft()
        while self.pending and now-self.pending[0][0] > self.WINDOW:
            self.pending.popleft()
        floor_ids, death_ids = {row[1] for row in self.pending}, {row[1] for row in self.deaths}
        self.links_seen = {(f, d) for f, d in self.links_seen if f in floor_ids and d in death_ids}
        if self.db is not None:
            for drop_at, floor_id, point in self.pending:
                for died_at, death_id, monster_point in self.deaths:
                    if ((floor_id, death_id) not in self.links_seen and abs(drop_at-died_at) <= self.WINDOW
                        and math.dist(point, monster_point) <= self.RADIUS):
                        self.db.execute('INSERT OR IGNORE INTO links(floor_id,death_id) VALUES(?,?)', (floor_id, death_id))
                        self.links_seen.add((floor_id, death_id))
                        changed = True
            if changed:
                self.db.commit()


def rows(search='', species=None, path=None):
    path = Path(path or FILE)
    if not path.exists():
        return []
    names = item_names()
    with closing(sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True, timeout=.2)) as db:
        data = db.execute('''WITH observations AS (
          SELECT DISTINCT f.id,f.item,f.map,f.amount,f.fresh,f.source,COALESCE(d.species,0) AS species,
                 COALESCE(d.name,'') AS name,COALESCE(l.status,'unlinked') AS status
          FROM floor f LEFT JOIN links l ON l.floor_id=f.id AND l.status!='rejected'
          LEFT JOIN deaths d ON d.id=l.death_id)
          SELECT item,map,species,name,status,COUNT(*),SUM(amount),MIN(fresh),source FROM observations
          GROUP BY item,map,species,name,status,source ORDER BY MAX(id) DESC LIMIT 2000''').fetchall()
    result = []
    for item, map_name, identity, name, status, count, quantity, fresh, source in data:
        label = names.get(item, f'Item {item}')
        if species is not None and identity != species:
            continue
        if search.casefold() not in f'{item} {label} {identity} {name} {map_name}'.casefold():
            continue
        result.append(dict(item_id=item, item_name=label, map=map_name, species_id=identity,
                           monster_name=name, status=status, observations=count, quantity=quantity, fresh=bool(fresh), source=source))
    return result[:500]


def review(entry, path=None):
    if not entry['species_id']:
        raise ValueError('Selecione uma associacao candidata com monstro identificado')
    with closing(open_database(path)) as db, db:
        ids = db.execute('''SELECT l.floor_id,l.death_id FROM links l JOIN floor f ON f.id=l.floor_id
             JOIN deaths d ON d.id=l.death_id WHERE f.item=? AND f.map=? AND d.species=? AND d.name=?''',
             (entry['item_id'], entry['map'], entry['species_id'], entry['monster_name'])).fetchall()
        for floor_id, death_id in ids:
            db.execute("UPDATE links SET status='rejected' WHERE floor_id=?", (floor_id,))
            db.execute("UPDATE links SET status='reviewed' WHERE floor_id=? AND death_id=?", (floor_id, death_id))


def save_mob_info(species, info, lines, path=None):
    """The server's @mi sheet replaces the previous one of that species."""
    stamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
    with closing(open_database(path)) as db, db:
        db.execute('INSERT OR REPLACE INTO mob_info(species,name,stamp,raw) VALUES(?,?,?,?)',
                   (species, info['name'], stamp, '\n'.join(lines)))
        db.execute('DELETE FROM mob_drops WHERE species=?', (species,))
        for mvp, entries in ((0, info['drops']), (1, info['mvp'])):
            for position, entry in enumerate(entries):
                db.execute('INSERT INTO mob_drops(species,position,mvp,item,item_name,rate) VALUES(?,?,?,?,?,?)',
                           (species, position, mvp, entry['item_id'], entry['item_name'], entry['rate']))


def mob_info_species(path=None):
    path = Path(path or FILE)
    if not path.exists():
        return set()
    try:
        with closing(sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True, timeout=.2)) as db:
            return {row[0] for row in db.execute('SELECT species FROM mob_info')}
    except sqlite3.Error:
        return set()


def server_drops(search='', species=None, path=None):
    """Drops informed by the server (@mi), with how many of each item were seen dropping here."""
    path = Path(path or FILE)
    if not path.exists():
        return []
    names = item_names()
    with closing(sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True, timeout=.2)) as db:
        try:
            data = db.execute('''SELECT d.species,i.name,d.item,d.item_name,d.rate,d.mvp,i.stamp,
                (SELECT COUNT(*) FROM links l JOIN floor f ON f.id=l.floor_id JOIN deaths m ON m.id=l.death_id
                 WHERE l.status!='rejected' AND f.item=d.item AND m.species=d.species)
                FROM mob_drops d JOIN mob_info i ON i.species=d.species
                ORDER BY d.species,d.mvp,d.position''').fetchall()
        except sqlite3.OperationalError:
            return []
    result = []
    for identity, monster, item, label, rate, mvp, stamp, seen in data:
        label = names.get(item) or label if item else label
        if species is not None and identity != species:
            continue
        if search.casefold() not in f'{item} {label} {identity} {monster}'.casefold():
            continue
        result.append(dict(species_id=identity, monster_name=monster, item_id=item, item_name=label,
                           rate=rate, mvp=bool(mvp), stamp=stamp, seen=seen))
    return result


def item_overview(search='', species=None, path=None):
    """One entry per item: every monster that drops it, highest chance first.

    Chances come from the server's @mi sheets; items only seen falling (no sheet yet) list the
    monsters they were linked to, by how many times."""
    items = {}

    def entry(item_id, label):
        return items.setdefault(item_id or label, dict(item_id=item_id, item_name=label, sources={}))
    for row in server_drops(path=path):
        source = entry(row['item_id'], row['item_name'])['sources'].setdefault(
            row['species_id'], dict(species_id=row['species_id'], monster_name=row['monster_name'], rate=None, mvp=False, seen=0))
        if source['rate'] is None or row['rate'] > source['rate']:
            source.update(rate=row['rate'], mvp=row['mvp'])
        source['seen'] = max(source['seen'], row['seen'])
    for row in rows(path=path):
        item = entry(row['item_id'], row['item_name'])
        if row['species_id'] and row['status'] != 'rejected':
            source = item['sources'].setdefault(
                row['species_id'], dict(species_id=row['species_id'], monster_name=row['monster_name'], rate=None, mvp=False, seen=0))
            if source['rate'] is None:
                source['seen'] += row['observations']
    result = []
    folded = search.casefold().strip()
    for item in items.values():
        sources = sorted(item['sources'].values(),
                         key=lambda s: (s['rate'] is None, -(s['rate'] or 0), -s['seen'], s['species_id']))
        if species is not None and not any(s['species_id'] == species for s in sources):
            continue
        text = ' '.join([str(item['item_id']), item['item_name'], *(f"{s['species_id']} {s['monster_name']}" for s in sources)])
        if folded and folded not in text.casefold():
            continue
        result.append(dict(item_id=item['item_id'], item_name=item['item_name'], sources=sources))
    result.sort(key=lambda i: (not i['sources'] or i['sources'][0]['rate'] is None,
                               -((i['sources'] or [{}])[0].get('rate') or 0), i['item_name'].casefold()))
    return result


def data_stamp(path=None):
    """Changes whenever the database (or its write-ahead log) is written."""
    path = Path(path or FILE)
    stamp = []
    for name in (path, path.with_name(path.name+'-wal')):
        try:
            info = name.stat()
            stamp.append((info.st_mtime_ns, info.st_size))
        except OSError:
            stamp.append(None)
    return tuple(stamp)
